---
title: "feat: Post-Render Validation (I1) — red de seguridad de render"
type: feat
date: 2026-07-06
origin: docs/ideation/2026-07-03-sentinel-10x-ideation.html (idea I1)
reviewed: 2026-07-06 (adversarial 4-lens pass — 10 findings folded in)
---

# feat: Post-Render Validation (I1) — red de seguridad de render

## Summary

Añadir un botón **"Validate Render Output..."** al Render tab que, tras un render, audita los frames en disco contra lo que Sentinel ya conoce de la escena (rango de frames real, output paths con tokens, resolución/formato por Take, AOVs configurados) y reporta: huecos de secuencia, frames de 0 bytes/truncados, frames sospechosos de otra sesión (mtime), AOVs esperados faltantes, cobertura por Take/formato, y frames anómalos por tamaño (SPC >3σ — marca negros/fallidos, **no** sustituye validación de píxeles/EXR). El resultado se escribe como report JSON atómico y se anexa a un sidecar de historial de render **separado** (`<base>_render_history.json`, no toca el history de versiones). La lógica de disco/secuencia/SPC vive en un módulo motor puro nuevo (`plugin/sentinel/postrender.py`), 100% pytest-able sobre carpetas dummy; el único punto que toca C4D es leer los params de escena. Cierra el hueco central de Sentinel: hoy protege todo hasta el botón de render y **nada** después. Target release: siguiente minor tras v1.8.0.

---

## Problem Frame

Sentinel valida la escena antes del render (12 checks QC), pero el fallo de pipeline más caro vive **después**: un hueco en una secuencia de 2000 frames, un frame negro por un fallo de denoiser, o un AOV que no se escribió — descubierto en comp o por el cliente, tras 12h de render, obligando a otro ciclo. Sentinel es la única herramienta con la verdad de referencia (rango de QC #11, AOVs configurados, resoluciones por Take) para saber qué **debería** existir en disco, pero no mira el disco.

**El peor resultado a evitar es un falso verde**: un "render completo" confiado sobre un render realmente incompleto. Tres fuentes de falso-verde guían el diseño: (a) el render normal (una secuencia desde el active render data del Main take, **sin child takes**) es el caso más común y más valioso — el escáner debe cubrirlo, no solo los multi-formato; (b) frames sobrantes de una versión anterior en una carpeta de overwrite rellenan un hueco → el núcleo debe tener conciencia de sesión (mtime); (c) el modo de rango (`ALLFRAMES`/`CURRENTFRAME`) cambia el set canónico → el rango se resuelve por modo, no leyendo FRAMEFROM/TO a ciegas.

**Por qué una acción standalone y NO un check #13 del registry** (validado en el grounding): los checks del `CHECK_REGISTRY` corren en `run_all_checks` sobre un Timer de ~0.5s leyendo **estado de escena vivo** (`plugin/sentinel/ui/panel.py` `_refresh`). Un escaneo de filesystem ahí es un desperdicio, corre a la vez que un render en curso, y —peor— una escena limpia que aún no se ha renderizado saldría `[FAIL]`, semánticamente falso. Post-Render debe dispararse **on-demand**.

---

## Requirements

- **R1** — Un botón "Validate Render Output..." en el Render tab abre un selector de carpeta y audita esa carpeta on-demand.
- **R2** — Detectar **huecos de secuencia**: frames del rango canónico (resuelto por modo, ver R12) ausentes en disco. Un frame presente que cae en un **clúster de mtime más viejo** separado por un hueco temporal (ver KTD8) se clasifica como sospechoso-de-sesión (WARN), NO como presente — para no leer un overwrite parcial como completo, sin marcar en falso un render largo uniforme.
- **R3** — Detectar **truncación dura**: `os.path.getsize == 0`, o tamaño por debajo de un suelo fijo mínimo-viable (header). Es dominio de U3 (señal absoluta), separado de las anomalías relativas de R4.
- **R4** — Detectar **frames anómalos por tamaño** vía control chart (SPC): frame que se desvía >3σ del vecindario. Marca frames negros/fallidos/denoiser-fail **sin decodificar píxeles** — es una heurística de tamaño, **no** validación de contenido. Un frame ya marcado como truncado (R3) no se re-lista en R4 (dedup en el report).
- **R5** — Verificar **presencia de AOVs esperados** por frame: en modo Direct-Output (un fichero por AOV) faltar un AOV configurado es un warning; en modo Multi-Part (un .exr combinado) solo se verifica que el fichero existe y es >0 (verificación por-capa diferida).
- **R6** — Verificar **cobertura por Take/formato**: agrupar el reporte por Take y detectar un Take/formato esperado que no produjo ficheros.
- **R7** — Escribir el resultado como **report JSON atómico** (`<base>_sentinel_render_report.json`, estilo `baseline._write_entries`) con listas de frames capadas.
- **R8** — Anexar un **resumen** de la validación (versión activa, timestamp, passed, conteos de issues) a un **sidecar de render separado** `<base>_render_history.json` (NO al history de versiones — ver KTD7). El sidecar es el registro para futura correlación versión↔render.
- **R9** — La lógica de disco (secuencia, 0-byte, SPC, conciencia de sesión, formato del report) es **pura y pytest-able** sobre carpetas dummy sin C4D; solo la lectura de params de escena (paths/rango/AOVs/resolución de modo) toca C4D.
- **R10** — Fallback graceful: sin Redshift → multipass estándar de C4D; sin carpeta válida / sin render data → mensaje claro, no crash; **doc sin guardar** (sin `GetDocumentPath`) → escribir el report/sidecar dentro de la propia carpeta de render auditada y avisarlo. Estilo defensivo de `checks/render.py`.
- **R11** — El manifest esperado cubre el **render de un solo formato sin child takes** (Main take + active render data), no solo los multi-formato. Es el caso más común.
- **R12** — El set de frames esperado respeta `RDATA_FRAMESEQUENCE`: MANUAL → FRAMEFROM/TO; ALLFRAMES → timeline del doc (`DOCUMENT_MINTIME/MAXTIME`); CURRENTFRAME → un frame (`doc.GetTime()`).

---

## Key Technical Decisions

- **KTD1 — Motor puro + UI fina.** Toda la lógica de escaneo/secuencia/SPC/report/sesión vive en `plugin/sentinel/postrender.py` (funciones puras sobre paths + `{frame: (size, mtime)}`, sin `import c4d` en el núcleo). El panel aporta solo el botón + diálogo + orquestación. **Para no romper la pureza ni crear un import circular** (`postrender` ↔ `ui/panel`), los helpers de light-group que hoy viven en `ui/panel.py` se mueven a `aovs.py` (el motor que ya posee `get_rs_aovs`); tanto `panel.py` como `postrender.py`/U5 los importan desde ahí (ver KTD6, U5).

- **KTD2 — Standalone Render-tab action, no registry check.** (Ver Problem Frame.) Wiring de 3 pasos: `G.BTN_VALIDATE_RENDER` en `plugin/sentinel/ui/ids.py` (~id 1215 libre; modelo `BTN_ADD_FRAME_TAG=1214`, `BTN_COLLECT_SCENE=1171`); `AddButton` en `_build_tab_render` bajo una sección nueva `_add_section_label("Post-Render")`; rama `elif cid == G.BTN_VALIDATE_RENDER:` en `Command()` (modelo `collect_scene`).

- **KTD3 — Expansión de tokens vía el token-system de C4D (CONFIRMADO en U1, C4D 2026.301).** No existía expansión de tokens en el repo. El helper resuelve `RDATA_PATH`/`RDATA_MULTIPASS_FILENAME` a nombres reales con **`c4d.modules.tokensystem.StringConvertTokens(path, rpd)`**, `rpd = {'_doc', '_rData', '_rBc', '_frame'[, '_take']}`. Reglas verificadas: `$frame`→**4 dígitos zero-padded**; `$take` **requiere** `_take` en el rpd o queda literal; si el path resuelto **no** contiene número de frame y es secuencia, el pipeline de C4D añade `str(frame).zfill(4)` → el helper lo replica; la extensión **no** la añade el conversor (la pone el caller vía RDATA_FORMAT→ext). `FilenameConvertTokens` se descarta (prefija `./`, sin extensión). `$pass` **no** se resuelve por el token-system (es interno de RS, ver KTD6). El motor puro recibe paths **ya resueltos**.

- **KTD4 — Corrupción v1 = heurísticas de tamaño/existencia, sin decodificar EXR.** El SPC de tamaño (R4) marca negros/fallidos por tamaño sin abrir un píxel. Es una **heurística**, no validación de contenido — no cazará todos los denoiser-fails y puede dar falsos positivos en varianza de compresión EXR; el report lo comunica así. El decode de EXR (headers/capas, NaN reales) necesita OpenEXR/Imath en Python **externo** (precedente `plugin/exr_converter_external.py`) → **diferido**.

- **KTD5 — Resolución por Take = cobertura de formato en v1; verificación de píxeles diferida.** R6 se cumple verificando que cada Take/formato esperado produjo su set de ficheros en su carpeta esperada. La resolución **real** de píxeles (leer header) → diferida con KTD4.

- **KTD6 — El set de AOVs esperado se lee LIVE, no se hardcodea; y el path lo da RS, no lo replicamos (CONFIRMADO en U1).** `aovs.get_rs_aovs(doc)` da los AOVs habilitados reales; el nº de **ficheros** depende de `REDSHIFT_RENDERER_AOV_MULTIPART` (**1=combinado**, un `.exr` multicapa por frame → solo verificar existencia + no-cero; **0=Direct Output**, un fichero por AOV) y de light groups. Los helpers `_is_lg_active_on_beauty`/`_scan_light_groups` **se mueven a `aovs.py`** (KTD1) y U5 los llama desde ahí — o, alternativa, U5 recibe el set de light-groups ya resuelto como argumento del caller (panel). **Gate resuelto:** RS **sí** escribe por su propio path per-AOV — no se replica su convención. Para cada AOV en Direct Output, U5 lee **`REDSHIFT_AOV_FILE_EFFECTIVE_PATH`** (el path que RS ya resolvió; convención `<beauty base>_AOV_<name>`) + **`REDSHIFT_AOV_FILE_FORMAT`** (0=EXR/1=TIFF/2=PNG → extensión per-AOV). `get_rs_aovs` se extiende para exponer estos dos campos. `$pass` es interno de RS (no expandible por el token-system) — por eso se lee el effective-path en vez de expandirlo. Global fallback: `REDSHIFT_RENDERER_AOV_PATH`.

- **KTD7 — Report atómico + registro en sidecar de render SEPARADO.** El writer usa el patrón atómico de `baseline._write_entries` (`baseline.py:220`: tmp.<pid>+`json.dump`+`os.replace`). El registro va a `<base>_render_history.json` — **NO** a `<base>_history.json`: `versioning.append_history_entry` mete en `history["versions"]`, que la Versions tab, `filter_versions_by_status`, `format_version_row`, `_on_history_row_click` y el pillbox "Last version" (`get_latest_version_info`) leen **sin discriminar tipo** → filas rotas, "File not found" al clicar, pillbox mal leído. Un sidecar separado evita tocar la feature de versiones. El shape per-item ({status,count,label,items[:cap]}) espeja `export_qc_report` con cap 30–50.

- **KTD8 — Conciencia de sesión en el NÚCLEO vía detección de CLÚSTER (no "más viejo que el más nuevo").** El false-verde por overwrite parcial (frames viejos rellenando un hueco) se cierra en el veredicto detectando un **corte bimodal** de mtimes: se ordenan los mtimes de los frames presentes y se busca un hueco grande (> K× el delta inter-frame mediano, K a calibrar ~5–10) que separe dos clústeres; **solo el clúster más viejo** se marca `stale` (WARN). Una secuencia de mtimes uniformemente creciente (un render largo legítimo de 12h, sin hueco) es una sola sesión → **cero flags**, sin importar la duración total — esto evita el crying-wolf que produciría "más viejo que el frame más nuevo" (que marcaría toda la parte temprana de cualquier render largo). **No hay ancla de sesión fiable en v1** (el hook de render-complete está diferido), así que la detección es **auto-contenida sobre el conjunto** — se elimina el argumento `session_mtime` como dead en v1. Caveat: mtime es una señal que el codebase desconfía (Synology conflicted-copy — baseline.py) → es WARN, no FAIL, etiquetado "basado en mtime; poco fiable en carpetas sincronizadas/copiadas".

---

## High-Level Technical Design

Flujo — solo la etapa 1 toca C4D; 2–3 son puras (pytest sobre carpetas dummy):

```
[C4D scene]                              [disk folder]
    │                                         │
    ▼  (U5, toca c4d)                         │
1. Expected manifest (per Take/format, +Main-take fallback for single render)
   { folder, filename_template, ext,          │
     frame_set  ← resolved by RDATA_FRAMESEQUENCE mode (MANUAL/ALL/CURRENT),
     expected_aovs (get_rs_aovs + light-groups from aovs.py, multipart flag) }
   (token expansion via U1 helper)            │
    └────────────────┬──────────────────────── ┘
                     ▼  (U3+U4+U5, PURE — pytest on dummy folders)
        2. Scan & diff  (input: {frame: (size, mtime)})
           - sequence gaps (R2)      ── expected vs files-on-disk
           - stale-session frames (R2/KTD8) ── bimodal mtime split: older cluster → WARN (uniform long render → none)
           - hard truncation (R3)    ── 0-byte / below fixed floor  (U3 owns)
           - size SPC outliers (R4)  ── rolling median/σ            (U4 owns; dedup vs R3)
           - AOV presence (R5)       ── Direct-Output only
           - per-Take coverage (R6)
                     │
                     ▼  (U6, PURE)
        3. Report + record
           - structured report {per check: status,count,items[:cap]}
           - atomic write  <base>_sentinel_render_report.json      (or into render folder if doc unsaved)
           - append summary → <base>_render_history.json  (SEPARATE sidecar)
                     │
                     ▼  (U7, thin UI)
        Render tab button → folder dialog → run → summary dialog
           (surfaces resolved version + range so a farm/edited-scene mismatch is visible)
```

*(Directional — no es especificación de implementación.)*

---

## Output Structure

```
plugin/sentinel/
  postrender.py          # NEW — pure engine (scan, session, SPC, report)
  aovs.py                # +_is_lg_active_on_beauty / _scan_light_groups (moved from ui/panel.py)
  ui/
    ids.py               # +G.BTN_VALIDATE_RENDER
    panel.py             # +Post-Render section, +handler, +dialog; light-group helpers now imported from aovs
tests/
  test_postrender.py     # NEW — pure unit tests; dummy fixtures built in-test en tmp_path (convención del repo, NO commiteadas)
```

---

## Implementation Units

### Phase 0 — Spike + fixtures (prereq de la ideación; sin fixtures ningún criterio es verificable barato)

### U1. C4D spike: expansión de tokens + convención de nombres RS (GATE — API CONFIRMADA)

- **Goal:** Confirmar en C4D 2026 vivo la API de expansión de tokens y la convención de nombres de fichero, y entregar el contrato del helper que U5 consumirá. Es un **gate**: U5 no arranca sin esto. **Estado: la parte arquitectónica está CONFIRMADA (C4D 2026.301, 2026-07-07); quedan 3 confirmaciones on-disk baratas como primer paso de ejecución.**
- **Requirements:** habilita R3, R5, R6, R11, R12 (dependen de nombres/paths reales); KTD3/KTD6.
- **Dependencies:** ninguna.
- **Files:** ninguno de producción — el spike produce hallazgos documentados (ver `scratchpad/u1_findings.md`) + fija la firma de `resolve_output_template(...)` que U5 implementará.
- **Hallazgos CONFIRMADOS (via MCP):**
  - **Tokens:** `c4d.modules.tokensystem.StringConvertTokens(path, rpd)` con `rpd = {'_doc','_rData','_rBc','_frame'[,'_take']}`. `$frame`→4 dígitos zero-padded; `$take` requiere `_take`; sin `$frame` en el path el conversor NO añade número (el pipeline sí → el helper hace `zfill(4)`); extensión la pone el caller. `FilenameConvertTokens` descartado (`./` + sin ext). `$pass` NO expandible (interno de RS).
  - **RDATA_FORMAT→ext:** mapeo por tabla de BitmapSaver (`FilterPluginList(PLUGINTYPE_BITMAPSAVER, True)`): 1100 TIF, 1104 JPG, 1106 PSD, 1016606 OpenEXR(.exr), 1023671 PNG, 1023737 DPX, 1001379 HDR, … (dict estático para los comunes).
  - **AOVs de RS (gate crítico):** RS escribe por su propio path. Por AOV: `REDSHIFT_AOV_FILE_EFFECTIVE_PATH` (path resuelto, convención `<beauty base>_AOV_<name>`) + `REDSHIFT_AOV_FILE_FORMAT` (0=EXR/1=TIFF/2=PNG). Global `REDSHIFT_RENDERER_AOV_MULTIPART` (1=combinado un `.exr`/frame; 0=Direct por-AOV). `get_rs_aovs` funciona.
  - **Rango (R12):** `RDATA_FRAMESEQUENCE`: MANUAL=0, CURRENTFRAME=1, ALLFRAMES=2. MANUAL→`FRAMEFROM/TO.GetFrame(fps)`; ALLFRAMES→timeline del doc; CURRENTFRAME→`doc.GetTime().GetFrame(fps)`.
- **Residuales on-disk (primer paso de ejecución de U1, contra una escena RS real — baratos, NO arquitectónicos):** (1) separador/padding exacto que RS inserta en el EFFECTIVE_PATH Direct-Output para una secuencia (`_AOV_Diffuse.0001.exr` vs `_AOV_Diffuse1001.exr`); (2) confirmar que la beauty auto-añade el frame de 4 dígitos cuando `RDATA_PATH` no tiene `$frame`; (3) confirmar que `$filepath` del EFFECTIVE_PATH toma el directorio de `RDATA_PATH` cuando la beauty tiene path. Render de 1–2 frames Multi-Part OFF/ON + light groups, listar ficheros reales.
- **Patterns to follow:** spike-por-MCP de Sentinel Frame (verificar antes de construir).
- **Test scenarios:** `Test expectation: none` — spike de descubrimiento; su salida son hechos verificados + la firma del helper.
- **Verification:** hallazgos documentados en `scratchpad/u1_findings.md` (arriba) + al cerrar los residuales, un ejemplo real de nombre beauty + un AOV Direct-Output + un `Beauty_[Group]` + Multi-Part en el PR.

### U2. Fixtures deterministas + harness pytest

- **Goal:** Carpetas dummy que ejercen los criterios (incluidos single-render y cross-versión) sin C4D.
- **Requirements:** R9.
- **Dependencies:** ninguna (paralelo a U1).
- **Files:** `tests/test_postrender.py` (scaffolding + helper `_make_seq(folder, start, end, size_fn, mtime_fn, ext, prefix, sep, skip)`). **NB (supera al Output Structure):** fixtures **in-test en `tmp_path`** siguiendo la convención real del repo (`test_baseline.py`/`test_rules.py` construyen árboles en `tmp_path`; los únicos fixtures commiteados son oráculos `.c4d`) — **no** se commitea nada bajo `tests/fixtures/postrender/`.
- **Approach:** fixtures generadas in-test (ficheros dummy con tamaño **y mtime** controlados). U2 construye solo lo que U3/U4 asertan — **(a)** `single_complete/`; **(b)** `gap_truncated/` (gap 1043 + 1050 a 0 bytes + **1075 a 512B sub-FLOOR → truncated**, cubre el bucket `truncated`); **(c)** `black_frame/` (1057 <10% mediana); **(f)** `stale_overwrite/`; **(g)** `long_render_spread/`; **(h)** `stale_plus_black/`. **Regla mtime obligatoria:** cada clúster usa espaciado **intra-clúster monótono NO-cero** (p.ej. `base + i*60`) — timestamps planos dan `median_delta==0` y `detect_stale_cluster` los trata como caso degenerado, anulando la detección stale. Los fixtures **(d)** `missing_aov/` y **(e)** `multi_take/` se **difieren a U5** (ejercen lógica de manifest/AOV/Take que U5 posee; U5 los construye in-test en su propia sesión). Dos estilos de separador (`beauty_1001` y `beauty.1001`) para probar el parser.
- **Patterns to follow:** construcción in-test como `test_baseline.py`/`test_rules.py` (árboles en `tmp_path` con `.mkdir()`/`os.utime`); carga Idiom-A del módulo puro como `test_framing.py`.
- **Test scenarios:** `Test expectation: none` (infraestructura) — su corrección se prueba en U3–U4.
- **Verification:** los tests de U3/U4 consumen las fixtures y pasan.
- **Handoff:** contrato completo de U2–U4 (firmas, criterios a–h, anclas file:line verificadas, correcciones de la revisión adversarial) en `docs/plans/2026-07-07-001-postrender-u2u4-codex-handoff.md`.

### Phase 1 — Motor puro (`postrender.py`)

### U3. Escáner de secuencia + integridad + conciencia de sesión

- **Goal:** Enumerar el set esperado y diffear contra disco; detectar gaps, truncación dura y frames sospechosos de otra sesión.
- **Requirements:** R2, R3, R9, KTD8.
- **Dependencies:** U2.
- **Files:** `plugin/sentinel/postrender.py` (`expected_frames(start,end,step)`, `detect_stale_cluster(mtimes_by_frame, gap_factor=6.0) -> [frames]`, `scan_sequence(folder, prefix, frame_set, ext) -> {found, missing, zero_byte, truncated, stale}` — `prefix` = stem antes del nº de frame; parser toma la última tirada de dígitos, tolera separador `_`/`.`), `tests/test_postrender.py`.
- **Approach:** puro sobre paths ya resueltos. `expected_frames` = `range(start, end+1, step)`. Escaneo cosechando `_find_latest_exr` (panel.py) — `os.listdir` + prefijo/ext + parseo del nº de frame (padding). **Truncación dura (U3 owns):** `getsize == 0` → `zero_byte`; `getsize < FLOOR` (suelo fijo mínimo-viable) → `truncated`. **Conciencia de sesión (KTD8) = clúster bimodal, no ancla:** `detect_stale_cluster` ordena los mtimes de los frames presentes, calcula el delta inter-frame mediano, y si existe un hueco > `gap_factor`× ese delta, marca **solo** el clúster más viejo como `stale`; sin hueco (render uniforme) → `[]`. Un frame `stale` no cuenta como `found`. Existencia+tamaño cosechando `collect_scene` (panel.py:1494).
- **Patterns to follow:** `checks/render.py:443` (conteo), `_find_latest_exr` (scan), `collect_scene` (existencia+tamaño).
- **Test scenarios:**
  - Covers criterio (a): `single_complete/` → `missing==[]`, `zero_byte==[]`, `stale==[]`.
  - Covers criterio (b): `gap_truncated/` → `missing==[1043]`, `zero_byte==[1050]`, `truncated==[1075]` (1075 a 512B < FLOOR — cubre el bucket `truncated`, distinto de `zero_byte`).
  - **Sesión (KTD8) — overwrite:** `stale_overwrite/` (hueco bimodal) → los 1050–1100 de mtime viejo salen en `stale`, NO en `found`.
  - **Sesión (KTD8) — render largo (boundary crítico):** `long_render_spread/` (1001–1100, mtimes monótonos crecientes que abarcan muchas horas, SIN overwrite) → `stale==[]`. Demuestra que un render largo legítimo NO dispara crying-wolf.
  - `expected_frames`: (1001,1100,1)→100; step 2→50; un frame (CURRENTFRAME)→1.
  - Padding: `beauty_1001` y `beauty.1001` parseados; `.txt` ignorado.
  - Carpeta vacía/inexistente → todo en `missing`, sin crash (R10).
- **Verification:** `python3 -m pytest tests/test_postrender.py -q` verde; el escenario `stale_overwrite/` demuestra que un overwrite parcial NO se lee como completo.

### U4. Detector de outliers de tamaño (SPC)

- **Goal:** Marcar anomalías relativas de tamaño sin decodificar píxeles.
- **Requirements:** R4, R9.
- **Dependencies:** U2 (paralelo a U3).
- **Files:** `plugin/sentinel/postrender.py` (`size_outliers(sizes_by_frame, sigma=3.0) -> [frames]`), `tests/test_postrender.py`.
- **Approach:** puro sobre `{frame: size}`, pero la **población se filtra ANTES de calcular estadísticos**: `size_outliers` recibe solo los frames sanos (el caller — U5/U6 — excluye los ya clasificados `stale`/`zero_byte`/`truncated` antes de pasar el dict), porque un frame stale de otra versión puede tener un tamaño legítimamente distinto (otros settings/resolución) y contaminaría la mediana/MAD, enmascarando un negro real o fabricando outliers. Mediana + desviación robusta (MAD o σ) sobre esa población limpia; marcar si `|size-median| > sigma*σ`. **U4 posee solo anomalías relativas**; la truncación dura es de U3. Nota de calibración (riesgo): vecindario = secuencia completa en v1; ventana rodante diferida si hay falsos positivos en cortes de plano. **Carry-forward (review U2–U4, 2026-07-07, ACCEPT):** verificado que con >50% de frames de tamaño byte-idéntico, `MAD==0` → el guard devuelve `[]` y un negro real se escapa (el propio falso-verde de la feature). Es propiedad inherente del MAD elegido (§7.4), no un defecto — los fixtures no lo ejercen. **U5/U6:** añadir un fixture de plano plano/baja-varianza + considerar un check de suelo absoluto secundario, y superficiar anomalías de tamaño como **WARN, no FAIL**.
- **Patterns to follow:** SPC de manufactura (figcaption I1 — "puro Python, testeable sobre ficheros dummy").
- **Test scenarios:**
  - Covers criterio (c): frame a <10% de la mediana → en outliers con su nº.
  - Secuencia uniforme (±ruido pequeño) → `[]` (sin falsos positivos).
  - Frame a 5σ por encima → marcado.
  - Secuencia de 1–2 frames → `[]` (muestra insuficiente, no crash); todos iguales (σ=0) → sin división por cero.
  - Dedup: un frame que es 0-byte NO aparece a la vez en outliers tras `build_report` (verificado en U6).
  - **Población limpia (`stale_plus_black/`):** con frames stale de otra versión (tamaños distintos) excluidos de la población, un frame negro real de la sesión actual SIGUE cazándose; incluir los stale en la población lo enmascararía (assert de ambos casos).
- **Verification:** pytest verde; sin falsos positivos en `single_complete/`.

### U5. Resolver de output esperado (toca C4D) + orquestador

- **Goal:** Producir el "expected manifest" leyendo la escena (paths, rango por modo, resolución/formato, AOVs, takes **incluido el single-render**) y correr U3/U4 + AOV-presence + cobertura por Take.
- **Requirements:** R2, R5, R6, R10, R11, R12; consume KTD3/KTD6/KTD1.
- **Dependencies:** U1 (helper de tokens), U2 (fixtures/mock), U3, U4.
- **Files:** `plugin/sentinel/aovs.py` (mover `_is_lg_active_on_beauty`/`_scan_light_groups` desde `ui/panel.py`; `panel.py` los importa ahora de aquí; extender `get_rs_aovs` para exponer `REDSHIFT_AOV_FILE_EFFECTIVE_PATH` + `REDSHIFT_AOV_FILE_FORMAT` por AOV, KTD6), `plugin/sentinel/postrender.py` (`build_expected_manifest(doc)`, `resolve_output_template(...)`, `audit_render_folder(doc, folder)`), `tests/test_postrender.py`. **U5 construye in-test sus propias fixtures `missing_aov/` (d) y `multi_take/` (e)** — diferidas de U2 porque ejercen la lógica de manifest/AOV/Take que U5 posee.
- **Approach:** construir las entradas del manifest cubriendo el single-render (R11) **sin** doble-contar ni false-RED:
  - Si `main_take.GetDown()` es None → **una** entrada desde `doc.GetActiveRenderData()` ligada al Main take (el caso single-render puro).
  - Si hay child takes → iterarlos, y decidir la inclusión del Main por la **selección real de render** (`take.IsChecked()` / current take), NO incondicionalmente — C4D renderiza una selección de takes; expandir un Main no marcado daría una secuencia entera "faltante" (false-RED).
  - **Dedup del manifest por output resuelto:** un child take sin override de `RDATA_PATH` hereda la render data del Main y resuelve al mismo `(folder, template, ext, frame_set)`; colapsar entradas colisionantes en una antes de escanear (si no, se escanea dos veces y el report duplica gaps/outliers bajo dos Takes).
  Por cada entrada: `RDATA_PATH`/`RDATA_MULTIPASS_*`, `RDATA_XRES/YRES`, `RDATA_FORMAT`→ext (tabla saver, KTD3), y **rango por modo (R12)**: `RDATA_FRAMESEQUENCE` MANUAL(0)→`FRAMEFROM/TO.GetFrame(fps)`; ALLFRAMES(2)→timeline del doc; CURRENTFRAME(1)→`doc.GetTime().GetFrame(fps)`. Beauty: resolver `RDATA_PATH` con `StringConvertTokens` (rpd con `_take` del take de la entrada) + ext + `zfill(4)` si falta el nº de frame (KTD3). **AOVs (Direct Output): leer `REDSHIFT_AOV_FILE_EFFECTIVE_PATH` + `REDSHIFT_AOV_FILE_FORMAT` per-AOV directamente de RS (KTD6) — NO se replica la convención**; `REDSHIFT_RENDERER_AOV_MULTIPART`=1 → "un fichero combinado por frame" (solo existencia). Light groups vía helpers movidos a aovs.py. Guard `REDSHIFT_AVAILABLE`; sin RS → multipass estándar de C4D. Doc sin path (R10) → pasar la carpeta auditada como base de escritura. El orquestador llama U3/U4 por entrada y agrega. **Carry-forward (review U2–U4, 2026-07-07):** `scan_sequence` filtra por `prefix.startswith` + `os.listdir` last-wins, así que una capa/AOV ajena que comparta prefijo (`beautyMask` vs `beauty`) puede sombrear no-deterministamente un frame válido (verificado: `beautyMask_1001.exr` de 100B marca el `beauty_1001.exr` bueno como `truncated`). Al resolver prefijos reales, **U5 debe anclar al stem exacto** (o de-dup determinista por frame), no un `startswith` laxo, para carpetas multi-AOV.
- **Patterns to follow:** `checks/render.py` `check_takes`/`check_output_paths`/`check_fps_range` (traversal + modo de rango); `aovs.get_rs_aovs`; light-group helpers (movidos a aovs.py).
- **Test scenarios:**
  - Puro (manifest mockeado): Covers (d): manifest con `Beauty_Denoised` en Direct-Output + `missing_aov/` → warning por frame afectado; en Multi-Part el mismo AOV faltante NO se reporta (solo existencia del .exr).
  - Puro: Covers (e): manifest 5 formatos + `multi_take/` sin 9:16 → reporte agrupado por Take marca 9:16 no renderizado.
  - **En vivo (MCP): single-render (Main take, sin child takes)** → `build_expected_manifest` produce UNA entrada válida (R11) y audita `single_complete/`-equivalente; NO reporta "nada que validar".
  - **En vivo (MCP): child takes presentes + Main NO marcado-a-render** → el manifest NO incluye el Main (por `IsChecked`/current), así que NO reporta la secuencia del Main como "faltante" (evita false-RED).
  - **Puro/en vivo: dedup del manifest** → un child take sin override de path (hereda la render data del Main) colapsa en una sola entrada; el report NO duplica los mismos gaps bajo dos Takes.
  - **En vivo (MCP): modo de rango** → una escena con preset en ALLFRAMES resuelve el rango al timeline, no a FRAMEFROM/TO (R12); CURRENTFRAME → un frame.
  - En vivo: paths resueltos coinciden con los ficheros reales de un render RS (Multi-Part ON/OFF + light groups) — cierra el gate de U1.
  - Sin Redshift / sin render data / doc sin guardar → fallback/mensaje, sin crash (R10).
- **Verification:** pytest verde (parte pura, manifest mockeado); verificación en vivo por MCP de single-render + modo de rango + paths reales.

### U6. Report atómico + registro en sidecar de render separado

- **Goal:** Ensamblar el reporte (con dedup), escribirlo atómico, y anexar el resumen al sidecar de render separado.
- **Requirements:** R7, R8, R9, R10.
- **Dependencies:** U5 (hallazgos), U3/U4.
- **Files:** `plugin/sentinel/postrender.py` (`build_report(findings)`, `write_report_atomic(path, report)`, `append_render_history(base_or_folder, summary)`), `tests/test_postrender.py`.
- **Approach:** report per-check `{status: OK|WARN|FAIL, count, label, items[:cap]}` capando a ~50 (espejo `export_qc_report`). **Dedup:** un frame en `zero_byte`/`truncated` (U3) se excluye de `size_outliers` (U4); un frame `stale` no cuenta como `found`. Writer atómico estilo `baseline._write_entries` (`baseline.py:220`) → `<base>_sentinel_render_report.json`, o dentro de la carpeta auditada si el doc no tiene path (R10). Registro: **sidecar separado** `<base>_render_history.json` (NO `versioning.append_history_entry` — KTD7). El `<base>` debe derivarse con **la misma lógica de `versioning.get_history_path`** (strip de `_v###[_status]` vía `parse_version_filename`) para que TODAS las versiones (`_v007_TR`, `_v008`, …) compartan UN solo fichero de render-history — si se deriva ingenuamente del nombre del doc actual se fragmenta por versión y se pierde la correlación. Factorizar un `render_history_path(doc_path)` junto a `get_history_path`. Load/append/atomic-write propio (o el helper atómico de baseline), entry `{type:"render_validation", version, timestamp, passed, issues}`.
- **Patterns to follow:** `baseline.py:220` (atómico), `export_qc_report` (shape+cap). **NO** `versioning.append_history_entry`.
- **Test scenarios:**
  - Covers (f): correr sobre `single_complete/` → report OK; `append_render_history` escribe en `<base>_render_history.json`; el `<base>_history.json` de versiones **queda intacto** (assert explícito de no-contaminación).
  - **Base compartida entre versiones:** anexar desde `robot_010_v007_TR.c4d` y luego desde `robot_010_v008.c4d` → ambos escriben en el MISMO `robot_010_render_history.json` (strip de `_v###[_status]`), no en dos ficheros por versión.
  - `write_report_atomic` atómico: un `json.dump` que lanza deja el fichero previo intacto y borra el tmp.
  - Dedup: un frame 0-byte aparece en exactamente UNA categoría del report (no en truncated y outliers a la vez).
  - **Masking no-vacuo (carry-forward review U2–U4):** el test `stale_plus_black` de U4 pasa vacuamente hoy (la contaminación no enmascara el frame 1020, solo fabrica falsos positivos, y la aserción se satisface por el OR `sets difieren`). En U6 —donde el masking real se ejerce sobre población pre-filtrada— endurecer a `1020 not in contaminated_result` para que la aserción sea no-vacua. Superficiar `stale` y anomalías de tamaño como **WARN** (mtime no fiable), nunca FAIL duro.
  - Report con 500 frames faltantes → `items` capado a ~50 + `count==500`.
  - Doc sin path → report escrito en la carpeta auditada, sin crash (R10).
  - Sidecar de render ausente/malformado → no crash, crea uno nuevo.
- **Verification:** pytest verde; assert de que la Versions tab / `<base>_history.json` no se toca; los 7 criterios cubiertos entre U3/U4/U5/U6.

### Phase 2 — UI

### U7. Botón del panel + diálogo

- **Goal:** Superficie on-demand en el Render tab, mostrando la versión+rango resueltos para que un mismatch (farm/escena editada) sea visible.
- **Requirements:** R1, R10; mitiga el blind-spot de farm/Team Render.
- **Dependencies:** U5, U6.
- **Files:** `plugin/sentinel/ui/ids.py` (`G.BTN_VALIDATE_RENDER`), `plugin/sentinel/ui/panel.py` (AddButton en `_build_tab_render` bajo "Post-Render"; rama en `Command()`; handler `_validate_render_output(doc)`).
- **Approach:** el handler: `c4d.storage.LoadDialog(flags=c4d.FILESELECT_DIRECTORY)` (modelo `collect_scene` panel.py:1367) para elegir carpeta (o derivarla del output path resuelto y ofrecerla por defecto); llamar `postrender.audit_render_folder(doc, folder)`; mostrar `MessageDialog` de resumen que incluye **la versión activa + el rango resueltos** ("Validando v007 · rango 1001–1100 · modo Manual") para que el usuario cace una discrepancia con lo que realmente se renderizó (farm/escena editada tras enviar); + escribir el report. Doc sin guardar → el mensaje avisa que el report va a la carpeta de render. Thin — sin lógica de escaneo en el panel.
- **Patterns to follow:** `collect_scene` (dispatch + dialog), receta de wiring de KTD2, botones del Render tab.
- **Test scenarios:** `Test expectation: none` (wiring UI) — verificación por checklist de humo en vivo.
- **Verification:** en vivo: reload sin errores; botón en la sección Post-Render; clic → selector → resumen con versión+rango; report JSON escrito; carpeta inválida / doc sin guardar → mensaje, sin crash.

---

## Scope Boundaries

### Deferred to Follow-Up Work
- **"Trace render" query** (dada una carpeta → devolver versión+status+score + detección de frames stale por timestamp-de-versión) y su UI. La conciencia de sesión (mtime) que cierra el false-verde SÍ va en el núcleo (KTD8/U3); lo que se difiere es la query de correlación y el staleness basado en el timestamp de la versión — heurística de mtime que el codebase ya desconfía (Synology). v1 deja el registro en el sidecar de render para habilitarlo.
- **Verificación por-capa de EXR / corrupción real** (headers, contar capas en Multi-Part, NaN reales) — necesita OpenEXR externo (KTD4).
- **Verificación de resolución real de píxeles por Take** (leer dimensiones del header) — v1 verifica cobertura de formato (KTD5).
- **Ventana rodante para el SPC** si aparecen falsos positivos en cortes de plano.
- **Hook de render-complete** — no existe MessageData de RENDER hoy; v1 es on-demand.

### Outside this feature's scope
- **Matriz de delivery-spec por proyecto** (#2 de la ideación) — extensión v2 sobre este motor.
- **Estimador de coste/tiempo de render** (#9) — necesita el historial que I1 empieza a capturar.
- **Cambios al motor QC/registry/score** — I1 no depende del QC 2.0 y no lo toca.
- **Endurecimiento del texture scanner** — separable, no en este plan.

---

## Risks & Dependencies

- **Falso verde (el riesgo rector).** Tres fuentes cerradas en el diseño: single-render sin child takes (R11/U5), overwrite parcial de otra sesión (KTD8/U3 — conciencia de mtime en el núcleo), y modo de rango (R12/U5). Los tres tienen fixture/test o verificación en vivo dedicados. Sin ellos el plan validaría MAL — no arrancar U5 sin R11+R12 resueltos.
- **Spike de tokens + path efectivo de RS (U1) — GATE CERRADO (2026-07-07).** El mapeo path→ficheros dependía de (a) la API de tokens y (b) de si RS escribe por su propio path de AOV. **Ambos confirmados en C4D 2026.301:** `StringConvertTokens` para la beauty; RS **sí** expone su path resuelto per-AOV (`REDSHIFT_AOV_FILE_EFFECTIVE_PATH` + `_FORMAT`) → se lee, no se replica. Solo quedan 3 confirmaciones on-disk baratas (padding de secuencia) como primer paso de ejecución de U1; no bloquean la arquitectura. Ver `scratchpad/u1_findings.md`.
- **Import circular (KTD1/KTD6).** Los helpers de light-group se mueven a `aovs.py` ANTES de U5 para que `postrender.py` no importe de `ui/panel.py` (que importa `postrender.py` en U7). Sin este movimiento, fallo al cargar el paquete.
- **Contaminación de la Versions tab (KTD7).** Resuelto usando un sidecar separado `<base>_render_history.json`; test explícito de que `<base>_history.json` no se toca.
- **Farm / Team Render blind-spot.** El doc abierto puede no ser el que produjo los frames (editado tras enviar a farm). Mitigado: v1 acota a validación local/inmediata + U7 muestra versión+rango resueltos para cazar el mismatch a ojo. Correlación robusta vía la Trace-render query (diferida).
- **SPC sobre-promete.** El tamaño no caza todos los denoiser-fails y puede dar falsos positivos en varianza de compresión EXR. Mitigado: reformulado como "marca anomalías de tamaño", no "cataches corruption"; ventana rodante diferida. **Verificado (review U2–U4):** además MAD colapsa con >50% de tamaños idénticos → negro escapado (ver U4 carry-forward: suelo absoluto + WARN en U5/U6).
- **Stale por pausa de render (verificado, review U2–U4).** Una sola pausa a mitad de render (un hueco > `gap_factor`×cadencia en una sesión continua) marca toda la mitad pre-pausa como `stale` y la saca de `found`. Es el modelo de corte-único v1 (KTD8/§6.3 step 6), no un defecto. Mitigado: `stale` se superficia como **WARN** ("mtime no fiable"), nunca FAIL; calibrar `gap_factor` en U6/U7 si molesta. El contrapeso `long_render_spread` solo cubre spread uniforme, no pausas.
- **Doc sin guardar (R10).** Sin path de escena → report/sidecar a la carpeta de render + aviso. Fallback enumerado.
- **Cross-platform:** paths `\` vs `/` normalizados (`.replace("\\","/")`, como los helpers existentes).

---

## Sources & Research

- **Origen:** `docs/ideation/2026-07-03-sentinel-10x-ideation.html` idea **I1** (Confianza 90%; 7 criterios de aceptación; prior art Ayon/OpenPype + ShotGrid).
- **Grounding de codebase (verificado file:line):** `plugin/sentinel/checks/render.py` (`check_output_paths:147`, `check_takes:210` — nota: salta Main; `check_fps_range:290` + modo de rango `:419-444`); `plugin/sentinel/aovs.py` (`get_rs_aovs:140`, `force_aov_tier:198`, `REDSHIFT_AVAILABLE:11`); `plugin/sentinel/ui/panel.py` (`collect_scene:1241`, `_find_latest_exr:1602`, `_is_lg_active_on_beauty:3464`/`_scan_light_groups:3434` — a mover a aovs.py, `export_qc_report:586`, `LoadDialog:1367`, Versions tab consumers `_update_history_area`/`_on_history_row_click`/pillbox); `plugin/sentinel/baseline.py:220` (atómico); `plugin/sentinel/versioning.py` (`append_history_entry:163` — NO usar para render; `get_history_path:84`, `load_history:98`); `plugin/sentinel/multiformat.py` (`MULTIFORMAT_DEFS:19`, `compute_format_output_path:154`).
- **Token system (spike U1 — CONFIRMADO C4D 2026.301):** `c4d.modules.tokensystem.StringConvertTokens(path, rpd)`; RS per-AOV `REDSHIFT_AOV_FILE_EFFECTIVE_PATH`/`_FORMAT`, `REDSHIFT_RENDERER_AOV_MULTIPART`. Hallazgos completos en `scratchpad/u1_findings.md`. Ref: `../11 C4D DEV/Cinema-4D-Python-API-Examples/scripts/05_modules/token_system/tokensystem_render_r17.py`.
- **Precedente EXR (frontera KTD4):** `plugin/exr_converter_external.py` (OpenEXR/Imath externo).
- **Revisión adversarial (2026-07-06):** 4 lentes (feasibility/scope/coherence/adversarial), 10 hallazgos verificados plegados — falso-verde por single-render/overwrite/modo, contaminación de Versions tab, import circular, Trace-render sin consumidor, doc-sin-guardar, dedup R3/R4, blind-spot de farm.
- **Convenciones:** CLAUDE.md (engine-module + thin-UI, restart C4D, no over-engineering), escalera v1.6.0 (pytest + fixtures deterministas), loop Codex→revisión (gates PR #2, Sentinel Frame PR #3).
