# Sentinel Frame v2 — auto-sync, AM control strip, crop camera-type-aware

**Fecha**: 2026-07-28
**Estado**: aprobado en brainstorm (fricción del usuario + benchmark GSG Social Frame / C4DFrame + investigación técnica de cámara)
**Contexto**: overhaul de UX y motor del `SentinelFrameTag` (v1.8.0, `plugin/sentinel/ui/frame_tag.py` + `multiformat.py` + `framing.py`). Fricción reportada en producción: flujo Takes/outputs manual y torpe, guías/HUD con ruido y sin info, config frecuente enterrada, y desajuste WYSIWYG viendo un Take de formato. Investigación: `docs/research/2026-07-28-*` (comunidad, cross-DCC) + brief técnico de cámara C4D/RS (resumen §4).

## Decisiones cerradas (brainstorm)

1. **Tag-first, no panel-first**: la config vive en el tag/AM (localidad del dato: es estado de ESA cámara; multi-cámara lo resuelve la selección gratis; el nudge es actividad acoplada al viewport; el tag funciona sin el panel). El panel Frame (6.6) sigue siendo espejo de estado + orquestación.
2. **Auto-sync**: el tag es la fuente de verdad; los Takes/outputs siempre la reflejan. Desaparecen los botones Create/Update Takes, Set Output y Remove Stale (Mark Subject ya vive en el panel).
3. **AM = control strip por frecuencia de uso** (patrón Social Frame refinado con C4DFrame): Main (diario, sin scroll) / Display (una vez por gusto) / Advanced (casi nunca). Nudge X/Y **inline por fila** (feedback vía el rect del formato en vista master — C4DFrame acierta aquí). Selector **Viewing** (activa el Take real = verificación WYSIWYG auténtica).
4. **Crop camera-type-aware** (hallazgo de la investigación): ORSCAMERA es un nodo con namespace de parámetros PROPIO — los IDs de Ocamera (`CAMERAOBJECT_APERTURE`=1006, `FILM_OFFSET_X/Y`) no existen en él. El "RS ignora aperture" de v1.8.0 fue un diagnóstico erróneo (ID equivocado sobre el nodo equivocado). Mecanismo por tipo: Ocamera→aperture, ORSCAMERA→`RSCAMERAOBJECT_SENSOR_SIZE`/`SENSOR_SHIFT`, focal como fallback.
5. **Invariante preservado**: la cámara master NUNCA se muta — todos los cambios de crop/nudge viven como overrides en los Takes (por eso no necesitamos el "Restore Camera" de C4DFrame).
6. **Descartes YAGNI**: grupos por categoría (Social/Cinema/Print), Custom ratio W/H, mask/solo/set/take por fila, modos focales Preserve V/H (siguen fuera del cycle), HUD interactivo clicable (sin ruta limpia de input en TagData 2026).

## 1. AM del tag — estructura de tabs

```
[Main]                                        ← diario, sin scroll
  Enabled ▣          Viewing: [Master ▾]      ✓ synced  (read-only)
  ─ Formats ────────────────────────────────
  ■ 16:9   Master     ▣     X  0%   Y  0%
  ■ 9:16   Reels      ▣     X  0%   Y +5%
  ■ 1:1    Square     ▢     X  —    Y  —
  ■ 4:5    Portrait   ▣     X  0%   Y  0%
  ■ 21:9   Cinema     ▢     X  —    Y  —
  ─ Display ────────────────────────────────
  Guides ▣    Mask ▣    Zones ▢    HUD ▣

[Display]                                     ← una vez, gusto de artista
  Mask color · Mask opacity · Line width · Line opacity
  Dim non-viewed formats (%)                  ← atenuación del foco (§3)

[Advanced]                                    ← casi nunca
  Composition: [Crop to Guides (default) / None (camera unchanged)]
  Per-format insets (los actuales)
  Per-format guide colors
```

Detalles:
- **Fila por formato** = 5 elementos con `DESC_COLUMNS`: swatch de color (identifica la guía) · nombre (aspecto) · on/off · X% · Y%. El nudge de una fila deshabilitada se muestra dim/inerte. Los valores X/Y son el nudge actual (mismo storage por-formato que hoy).
- **Viewing** = cycle `Master / <cada formato habilitado>`. Elegir un formato **activa su Take** (cámara croppeada + resolución reales); Master vuelve al Take principal. Es estado de documento, no del tag — el cycle refleja el Take activo si el usuario lo cambia por el Take Manager (two-way).
- **`✓ synced` read-only**: con auto-sync el estado normal es synced; muestra `⟳ syncing…` durante el debounce. Nunca "stale" persistente (ese estado muere).
- **Tabs**: `DTYPE_GROUP` de primer nivel — C4D los rinde como tabs en la description dinámica (patrón Social Frame Main/Advanced).
- **Migración**: los params existentes conservan sus IDs (enable/insets/nudge per-format, toggles, opacity); solo se reorganiza la description. Params nuevos: Viewing (cycle), Line width/opacity, Dim %, per-format colors si no existían como params. Escenas viejas cargan sin pérdida; los botones retirados desaparecen de la description (sus IDs no se reutilizan).

## 2. Auto-sync (motor)

**Regla**: cualquier cambio en los parámetros del tag que afectan a los Takes (formatos on/off, nudge, insets, composition) dispara una regeneración debounced. La firma de staleness existente (`_params_signature_for_takes`) pasa de "avisar" a "disparar".

**Mecánica** (respeta las restricciones de threading de C4D):
- `Message(MSG_DESCRIPTION_POSTSETPARAMETER)` en el tag (main thread) compara firma → si cambió, marca dirty con timestamp y programa el sync.
- El sync real corre **deferred + debounced** (≈500 ms sin nuevos cambios) — nunca dentro del propio POSTSETPARAMETER (un drag de slider dispara ráfagas), nunca desde Draw/Execute (read-only). Vehículo: `SpecialEventAdd` → un `MessageData` plugin (`sentinel_frame_sync`, nuevo, registrado en el `.pyp`) que recibe el CoreMessage y ejecuta el sync con retraso corto; el panel NO es el vehículo (el tag debe funcionar con el panel cerrado).
- El sync ejecuta el motor existente (`generate_multiformat_takes` + set output + retirar Takes de formatos deshabilitados = Remove Stale implícito) en **un solo undo** que se une al del cambio del usuario cuando es posible; si no, como paso propio inmediatamente después (un Cmd+Z revierte el cambio+sync en ≤2 pasos, verificado en vivo).
- **Guard de re-entrada**: el sync no debe re-disparar POSTSETPARAMETER-loops (flag en curso). Los cambios hechos POR el sync (take links, firma privada) no cuentan como cambios de usuario.
- **Undo del usuario**: deshacer un cambio de parámetro re-dispara el sync con la firma vieja → converge solo.
- Edge: renombrar/borrar la cámara o el tag usa las guardas rename-safe existentes (BaseLink resolver de v1.8.0).

## 3. Viewport (guías/HUD)

- **Foco por formato**: viendo un formato (Viewing≠Master), su guía a plena intensidad; las demás atenuadas al `Dim %` (default 70% — 0% = ocultas). En Master, todas a plena intensidad como hoy. Mata el ruido multi-formato.
- **HUD enriquecido** (líneas, esquina actual): `Viewing: 9:16 Reels · 1080×1920 · ✓ synced` (o `⟳`), y en composition None: `⚠ None: guides are reference only — render extends vertically`. Desaparece el HUD "Takes out of date" (no existe el estado).
- **Fix WYSIWYG**: con el motor camera-type-aware (§4) el render del Take debe igualar el viewport exactamente. La máscara/guías no cambian de matemática (crop-interpretation intacta); cambia QUÉ escribe el motor en la cámara.
- Draw sigue read-only estricto (estado desde BaseContainer, nunca setattr — lección v1.8.0).

## 4. Crop camera-type-aware (motor `framing.py`/`multiformat.py`)

**Base técnica** (brief de investigación, fuentes: help.maxon.net OCAMERA + Redshift Camera Object, SDK ORSCAMERA, foro Maxon #4535, aturtur AR_ResizeCanvas):
- Ocamera: `APERTURE` (1006) = ancho de sensor HORIZONTAL en mm (no hay vertical; el vertical se deriva del film aspect del render). `FILM_OFFSET_X/Y` = pan del gate, gate-relativo, sin cambiar perspectiva. Crop inscrito: `new_aperture = aperture × factor` — misma perspectiva, DOF intacto (focal/f-stop/foco no cambian), y **sobrevive a keyframes de focal** (escribes un parámetro distinto del animado).
- ORSCAMERA (cámara RS nativa, C4D 2023.1+): **namespace propio** — `RSCAMERAOBJECT_SENSOR_SIZE` (Vector), `RSCAMERAOBJECT_FOCAL_LENGTH`, `RSCAMERAOBJECT_SENSOR_SHIFT`. Los IDs de Ocamera son inertes en este nodo. "The Optical settings are not compatible with the Cinema 4D default camera" (Maxon).
- El hallazgo re-explica v1.8.0: "RS ignora aperture" era ID-de-Ocamera-sobre-ORSCAMERA (no-op), no una limitación del renderer. Y la hipótesis del bug actual: el **nudge** (film offset con IDs Ocamera) es inerte en cámaras RS nativas → guías con nudge en viewport, render sin nudge.

**Diseño del writer**:
```
detect_camera_kind(cam) -> "ocamera" | "orscamera"      # por GetType()
crop_writes(kind, aperture_o_sensor, factor, nudge) ->
  ocamera:   [(CAMERAOBJECT_APERTURE, ap×factor), (FILM_OFFSET_X, nx), (FILM_OFFSET_Y, ny)]
  orscamera: [(RSCAMERAOBJECT_SENSOR_SIZE, Vector(sx×factor, sy×factor[, z])),
              (RSCAMERAOBJECT_SENSOR_SHIFT, Vector/params según unidades)]
```
- Matemática compartida en `framing.py` (pura); el mapeo a DescIDs por tipo en `multiformat.py`. `format_crop_values` (focal) se conserva como **fallback** explícito si el override de Vector por Take resulta inviable.
- Formatos MÁS ANCHOS que master: siguen resolución-sola (comportamiento actual, correcto).
- Composition **None**: sin escritura de cámara (como hoy) + el aviso honesto del HUD (§3).

**Incógnitas que SOLO el test en vivo resuelve** (spike previo a construir, en C4D 2026.303 con RS):
1. ¿`FindOrAddOverrideParam` acepta override de `RSCAMERAOBJECT_SENSOR_SIZE` como Vector completo, o hace falta por-componente?
2. ¿El `SENSOR_SIZE_FIT_MODE` de la cámara RS cambia qué eje debe escalar el crop? (¿hay que fijarlo/leerlo?)
3. ¿Unidades/escala de `SENSOR_SHIFT` vs el film offset porcentual de Ocamera? (round-trip numérico)
4. ¿Una Ocamera con el tag RS legacy respeta el override de `APERTURE` igual que sin tag?
5. Cámara convertida estándar→RS-nativa con Takes viejos: ¿overrides huérfanos apuntando a IDs Ocamera? (staleness de conversión — el sync debe detectar el cambio de tipo y regenerar).

Si el spike invalida la escritura de sensor en ORSCAMERA → ese tipo cae al fallback focal (lo verificado en v1.8.0) y se documenta; el diseño no se bloquea.

## 5. Panel Frame (sub-vista 6.6) — cambios mínimos

- Gana el selector **Viewing** (espejo two-way del cycle del tag; activar Takes es estado de documento — legítimo desde ambos lados). Op nueva de mutación `panel/frame/set_viewing {format_id|master}`.
- El bloque de staleness/hint se simplifica: sin estado stale, la pista "Takes out of date" desaparece; `⟳ syncing` transitorio es suficiente. `panel/frame` deja de exponer `is_stale` como accionable.
- Todo lo demás intacto (Add/Select tag, Subjects, QC #12).

## 6. Compatibilidad y QC

- **QC #12 (cross-aspect)**: sin cambio de semántica; sigue leyendo nudge por formato. Verificar que lee el storage que el AM nuevo escribe (mismos IDs → sin cambio).
- **`has_takes`/staleness en `panel_frame_ops`**: `_is_stale_from_signature` se conserva internamente como trigger del auto-sync, deja de ser UI.
- Escenas v1.8.0: cargan, el primer POSTSETPARAMETER o un pase de adopción al cargar el tag (Message `MSG_MENUPREPARE`/init) sincroniza. Takes existentes se actualizan idempotentemente (motor actual ya lo es).

## Manejo de errores

- Sync falla (p.ej. TakeData inaccesible) → HUD/status `⚠ sync failed` + `safe_print`; nunca un MessageDialog desde el MessageData (freeze). Reintento en el siguiente cambio.
- Cámara borrada bajo el tag → guardas existentes (tag sin host válido = inerte).
- Debounce nunca pierde el último estado: la firma se recomputa al ejecutar, no al programar.

## Verificación

- **pytest** (motores puros): `crop_writes` por tipo de cámara (tabla de escrituras esperada), firma→decisión de sync (debounce puro parametrizado por timestamps inyectados), mapeo Viewing↔take, migración de description (IDs estables).
- **Spike en vivo primero** (las 5 incógnitas de §4) — sus resultados se escriben en `docs/solutions/` y ajustan el writer antes del grueso.
- **Matriz live final (oráculo = render real)**: por cada tipo de cámara (Ocamera / ORSCAMERA) × formato (9:16, 1:1) × {sin nudge, con nudge} × {focal estática, focal animada}: render del Take == captura del viewport de guías (comparación visual con escena real). Auto-sync: cambiar formato/nudge → Takes correctos sin tocar botón, un Cmd+Z revierte; Viewing cambia Takes en ambos sentidos; None muestra el aviso; escena v1.8.0 abre y adopta.
- vitest: cambios del panel (Viewing, hint simplificado).

## Fuera de alcance

- Expansión de Tools y oportunidades cross-DCC (fases siguientes; evidencia en `docs/research/2026-07-28-*`).
- Custom ratios, categorías de formatos, HUD interactivo, modos focales Preserve V/H en el cycle.
- Burn-ins/review viewer (cross-DCC #1/#2 — fase propia).
