# Sentinel Asset Hub — Design Spec

**Fecha:** 2026-07-16
**Estado:** Aprobado en brainstorming (pendiente de plan de implementación)
**Referencia visual:** Crate «Collect & Archive Scene» (screenshots del usuario, 2026-07-16)

## Objetivo

Unificar **Texture Repathing** (v1.5.7) y **Scene Collector** (v1.10.0) en un único
diálogo visual — el **Asset Hub** — que muestre el inventario completo de assets de
la escena con estado, tamaño y procedencia, permita repathing y relink en sitio, y
ejecute el collect (carpeta o ZIP) con el pre-flight QC embebido y el manifest
sellado v1.10 intacto.

**Criterio de éxito verificable:** abrir el Hub en una escena RS real muestra todos
los assets (texturas + ABC + HDRI + LUTs…) con estado y tamaño; un find/replace se
revierte con un solo Cmd+Z; pulsar Collect produce el mismo paquete + manifest que
el flujo v1.10 actual (corroborado 1:1 en una entrega real) más, opcionalmente, un
`.zip`; y los dos puntos de entrada antiguos abren el Hub.

## Decisiones cerradas (brainstorming)

| Tema | Decisión |
|---|---|
| Alcance | El Hub **reemplaza ambas** entradas (Texture Repathing y Collect Scene) |
| Tipos de asset | **Inventario completo**: scan estructurado de texturas + `GetAllAssetsNew` |
| Salida collect | **Carpeta (SaveProject) + ZIP opcional** (dropdown Output, stdlib `zipfile`) |
| Extras | Tamaño por asset + total, procedencia clicable, Search Folder for Missing, thumbnails lazy |
| Pre-flight | **Embebido en el Hub** (franja con Fix/Accept inline; sin MessageDialogs encadenados) |
| Organización lista | **Tabla plana** con columna Type + filtros (no grupos colapsables) |
| Missing al collectar | **Avisar y permitir continuar** (estilo Crate; el manifest los sella como missing) |
| Arquitectura | Opción A: motor puro nuevo `assets.py` + refactor de `collect_scene` en pipeline |

## Arquitectura

### Motor puro: `plugin/sentinel/assets.py` (nuevo)

Mismo patrón que `manifest.py` / `postrender.py`: **stdlib puro, sin `import c4d`**,
testeable con pytest. Las lecturas de C4D viven en un adaptador fino en
`ui/flows.py` (patrón del adaptador de `postrender.py`).

**Modelo `AssetRecord`** (deduplicado por ruta normalizada):

- `path` — como está escrito en la escena
- `resolved_path` — ruta absoluta en disco, o `None`
- `status` — `ok | missing | absolute | asset_uri | empty` (clasificación actual de Texture Repathing, ampliada a todos los tipos)
- `asset_type` — `texture | hdri | alembic | vdb | ies | lut_ocio | sound | xref | proxy | other` (inferido por extensión + contexto del owner)
- `size_bytes` — `os.stat` sobre `resolved_path`; `None` si missing
- `owners` — lista de `(owner_name, owner_kind, channel)`, p. ej. `("RS_Body", "material", "Base Color")`. Un asset usado N veces = 1 fila con N owners
- `repathable` — `True` solo si procede del scanner estructurado de texturas (existe writer). Lo que solo aporta `GetAllAssetsNew` se lista **read-only**: se ve y se collecta, pero no se edita
- `owner_ref` — referencia opaca al objeto C4D para «click → seleccionar en escena»; solo la maneja el adaptador, nunca el motor puro

**Fusión de scanners** (en el adaptador C4D):

1. `scan_all_texture_paths(doc)` → registros repatheables con owner/canal detallado
2. `c4d.documents.GetAllAssetsNew(doc, …)` → inventario exhaustivo del resto
3. `assets.merge_inventories(textures, generic)` (puro) — dedupe por ruta
   normalizada; si un asset aparece en ambos, gana el registro de texturas (más
   rico) y se le suman los owners del genérico

**Funciones puras** (todas con pytest): `merge_inventories`, `classify_status`,
`infer_type`, `compute_totals` (por tipo + total), `match_missing_in_folder(missing,
file_index)` (match por basename case-insensitive con detección de ambigüedad) y
`plan_zip(delivery_dir)`.

**Reutilización estricta:** los writers de repathing
(`apply_texture_path_change`), `manifest.py` (305 tests) y `gate.py` **no se
tocan**. El Hub es un consumidor nuevo.

### UI: diálogo `AssetHubDialog` (async) + `AssetListArea`

Diálogo **async** (no modal — Cmd+Z debe llegar a C4D, misma razón que Texture
Repathing), ~980×720 redimensionable, con `CoreMessage`/`Timer` para re-scan al
cambiar la escena. Seis zonas:

1. **Cabecera** — escena, resumen (`64 assets · 2 missing · 5 absolute · 1.94 GB`), botón Rescan
2. **Filtros** — por estado (All/Missing/Absolute/OK) + búsqueda por nombre/ruta
3. **Tabla de assets** — `AssetListArea` (evolución de `TextureListArea` en `ui/user_areas.py`), tabla plana en `ScrollGroup`: estado (dot color), thumbnail, nombre, tipo, tamaño, used-by, ruta, `[…]` por fila (solo repatheables). Orden clicable por columna; por defecto missing arriba. Click en «used by» → selecciona material/objeto en C4D
4. **Repathing** — Find/Replace (+ Recent presets + Match case, como hoy), Preview, Search Folder for Missing…, Make All Relative, Clear Pending, contador de pendientes, **Apply All** (un `StartUndo`/`EndUndo`)
5. **Pre-flight QC embebido** — franja con score (`10/12`), issues resumidos y botones Fix auto-fixables / Accept… / Details, reutilizando `run_all_checks` + `compute_score` cacheados (los mismos del panel) y el triage de `gate.py` inline
6. **Entrega** — Deliver to (path + Choose…), Output (`Folder | Zip`), botón **Collect ▸**

**Thumbnails lazy:** caché `{resolved_path: BaseBitmap 22×22}` rellenada solo para
filas visibles del viewport, en el `Timer` (~8 por tick), nunca en `DrawMsg`.
Placeholder gris mientras carga; sin thumb para missing/read-only. Cap ~200
entradas con evicción simple. Formato que no carga → placeholder permanente, nunca
traceback.

### Pipeline de Collect

`flows.collect_scene` se trocea en pasos que el Hub invoca con estado visible en
su barra de estado (la lógica v1.10 sobrevive; la cadena de MessageDialogs
desaparece):

0. **Estado previo** — assets escaneados, pre-flight resuelto, destino y output elegidos (fuera del botón)
1. **Gate de missing** *(nuevo)* — si quedan missing: aviso con la lista («N assets quedarán fuera del paquete») → Continue / Cancel
2. **Quality gate** *(reusa `gate.py`)* — si `gates_enabled`; el triage ya se resolvió inline, aquí solo re-evalúa y registra overrides
3. **SaveProject with Assets** *(reusa)* — copia + rename a nombre limpio + sidecars (notes, baseline, ruleset, report)
4. **Re-scan de verificación + manifest sellado** *(reusa, intacto)* — doc temporal, `assets_schema` en `sentinel_manifest.json`
5. **ZIP opcional** *(nuevo)* — `zipfile` stdlib sobre la carpeta de entrega, con progreso; la carpeta original se conserva
6. **Resumen de entrega en el Hub** *(nuevo)* — destino, tamaño total, collected/missing/external, QC sellado, TODOs pendientes + Reveal in Finder / Open Manifest

### Migración de puntos de entrada

- Tools → «Texture Repathing…» pasa a ser «Asset Hub…» (mismo sitio)
- Botón «Collect Scene» del panel → abre el Hub (foco en la zona de entrega)
- QC #6 Assets Info → ofrece abrir el Hub
- `TextureRepathingDialog` se retira del panel pero la clase se conserva una
  versión (patrón `MultiFormatDialog`); el flujo collect antiguo desaparece como
  UI, su lógica sobrevive como pasos del pipeline

## Manejo de errores

- **Scan parcial:** excepción en un material/asset concreto se captura por-item (`safe_print` + «N items skipped» en cabecera). Nunca un inventario vacío silencioso (principio `scan_status` del manifest)
- **Tamaños en red lenta (Synology):** `os.stat` por lotes en el `Timer`, no en el open; columna Size muestra «…» y el total «calculando»; timeout por item → «?»
- **Search Folder for Missing:** indexa una vez con `os.walk` (cap ~50k ficheros + aviso al superarlo); 2+ candidatos con el mismo basename → fila «ambiguous», elección manual, nunca auto-elige
- **Collect:** cada paso reporta a la barra de estado; fallo del ZIP no invalida la carpeta ya collectada («carpeta OK, ZIP falló»); el manifest sellado es la fuente de verdad
- **Undo:** repathing = un undo por Apply All (como hoy); Collect no toca la escena original, no necesita undo

## Testing (escalera del proyecto)

1. **pytest** sobre `assets.py` puro: merge/dedupe, clasificación de estado y tipo, totales, matching de missing (ambigüedad, case-insensitive), plan de ZIP. ~40–50 tests nuevos; los 305 existentes intactos
2. **Fixtures C4D** (`violating.c4d` / `clean.c4d` vía `run_fixtures.py`): el inventario del Hub sobre `violating.c4d` debe ser superset de lo que hoy reporta Texture Repathing (mismos paths, mismos estados)
3. **Live C4D 2026.3:** Hub sobre escena RS real — thumbnails/tamaños/used-by-click, repathing con Cmd+Z verificado por menú Edit, collect completo en modo Folder y en modo Zip, Delivery Summary + Verify sobre el paquete
4. **Producción real antes de mergear** (regla validate-on-real-render-data): collect de una entrega real, manifest corroborado 1:1

## Fuera de alcance

- Grupos colapsables por tipo en la lista (descartado: tabla plana)
- Editar/repathear assets read-only (LUTs, sonido…) — se listan y collectan, sin writer
- Bloqueo duro por missing o severidad configurable del gate de missing (elegido: avisar y continuar)
- Cambios en `manifest.py`, `gate.py` o los writers de repathing
