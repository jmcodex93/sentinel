# Sentinel Frame v2.1 — Custom ratio + Slices (v1.29)

**Fecha**: 2026-07-28
**Estado**: implementado en la rama `feat/frame-slices` (8 tareas subagent-driven, todas Approved en review adversarial; pytest 912, vitest 136) — **pendiente de verificación live en C4D real y de merge a main** (decisiones del usuario en brainstorm: slices para TODOS los formatos como C4DFrame; slices en X e Y según config; cortes exactos sin solape — todas implementadas tal cual)
**Contexto**: sobre el Frame v2 (v1.28.0 — auto-sync, control strip, crop camera-type-aware). Caso motor: entregas ultra-anchas de pantallas de eventos (p.ej. 9000×500) que conviene renderizar como N slices (3×3000×500) en vez de un chunk — mejor para farm/memoria/re-renders parciales; ensamblado en comp trivial (Reads contiguos). El film offset de C4D existe para exactamente este tiled-render.

## Decisiones cerradas

1. **Custom ratio**: UNA entrada custom por tag (sexta fila del grid de formatos): `Custom ▣ · W · H · swatch · X · Y [· Sx · Sy]`. Se comporta como cualquier formato: guía, Take auto-sincronizado (`<cam>_custom`), output, firma del auto-sync (W/H incluidos → cambiar el ratio regenera solo). El set de defs pasa de tupla estática a **fuente por-tag** (5 estándar + custom si está activa).
2. **Slices en TODOS los formatos** (paridad C4DFrame): cada fila del grid gana dos enteros `Sx`/`Sy` (columnas × filas de corte; 1×1 = sin trocear, default). El grid pasa de 4 a 6 columnas compartidas.
3. **Cortes exactos, sin solape** (paneles físicos). Sin campo de padding en v1.
4. **Tiling pixel-perfect sin exigir divisibilidad**: límites de slice por `floor((i+1)·W/Sx) − floor(i·W/Sx)` — las anchuras difieren ±1 px cuando W no es divisible, la suma es exacta.

## Diseño

### Motor (`framing.py` + `multiformat.py`)

- **Defs por-tag**: `_format_defs()` (frame_tag) devuelve las 5 estándar + `{"id": "custom", "label": "Custom", "width": W, "height": H}` cuando la fila custom está activa. `multiformat` recibe los defs por opciones (ya recibe `formats`; añadir `custom_def` o defs resueltos) — los consumidores (guías, QC #12, firma, take naming) ya iteran defs, así que es generalizar la fuente.
- **Slices como ventanas de crop**: cada slice (i,j) de un formato es un rect inscrito DENTRO de la ventana del formato en el master. Nueva función pura `slice_windows(fmt_rect_ndc, sx, sy, px_w, px_h) -> [(rect_ndc, w_px, h_px, name_suffix)]` con límites floor-exactos. El writer de cámara reutiliza `crop_writes`: cada slice = crop factor + offset propios (generalizar la entrada de `format_crop_values`/`nudge_to_film` para aceptar una ventana arbitraria además del centered+nudge — misma matemática, ancla distinta).
- **Takes**: sin slices → como hoy. Con Sx·Sy > 1 → takes `<cam>_<fmt>_s01..sNN` (orden row-major, numeración con cero-pad a 2), cada uno con su RenderData clonado a la resolución del slice y su override de cámara. El auto-sync los regenera/pruna igual que a los formatos (firma incluye Sx/Sy). El take "entero" del formato NO se genera cuando hay slices (el conjunto de slices ES la entrega; evita renders duplicados).
- **Output paths**: `compute_format_output_path` gana el sufijo de slice (`.../<fmt>/s01/...` en modo subfolder; `_s01` en modo suffix).

### AM (tag)

- Grid de formatos a **6 columnas**: `[enable/label] [swatch] [X] [Y] [Sx] [Sy]` (anchos compartidos — la alineación de v1.28 se mantiene). Sx/Sy enteros 1-16, default 1, deshabilitados si el formato está off (mismo `GetDEnabling`).
- Fila **Custom** al final del grid con `W`/`H` (enteros, defaults 1920×1080) en las posiciones que en las filas estándar ocupan… W/H necesitan 2 celdas extra → la fila custom vive en su propio sub-grid de 8 columnas bajo el principal, alineado a ojo (deviation aceptada: los anchos exactos del grid principal no aplican a W/H).

### Viewport

- Guías: la ventana del formato como hoy; con slices, **líneas de corte internas** (mismo color, línea fina/discontinua) + numeración `s1..sN` con el patrón de etiquetas en-rect (stagger) SOLO cuando el formato está enfocado o es el único activo (evitar ruido).
- Viewing: el cycle lista los slices de un formato troceado (`custom · s1`, `custom · s2`, …) — activar uno muestra su crop real (WYSIWYG por slice).

### QC #12

- Sin cambio de semántica: evalúa la ventana COMPLETA del formato (la composición), no cada slice — el troceo es empaquetado de render, no encuadre. Documentado en el spec del check.

### Panel

- `panel/frame`: `viewing_options` incluye los slices; el bloque frame muestra `N formats (M slices)`.

## Errores / no-regresión

- Formatos sin slices: byte-idéntico a v1.28 (Sx=Sy=1 no cambia nada — ni naming ni firma… la firma SÍ incluye los campos nuevos: migración = defaults 1 → misma semántica; la firma cambia una vez en la adopción → un re-sync inocuo).
- Escenas v1.28: cargan; el primer cambio real re-sincroniza (adopción como siempre).
- Todos los writes de cámara siguen las lecciones de `docs/solutions/logic-errors/2026-07-28-take-override-descid-and-viewport.md` (DescID almacenado, UpdateSceneNode solo-activo, force-redraw).

## Verificación

- pytest: `slice_windows` (límites exactos, no-divisible, 1×1 passthrough), defs por-tag (custom on/off), naming/outputs por slice, firma con Sx/Sy/W/H.
- Live (matriz): custom 9000×500 con 3×1 slices → 3 takes de 3000×500, render de cada slice == su ventana de la guía (oráculo render real, como el spike); ensamblado horizontal de los 3 == el render entero (comparación numérica); slices 2×2 en un formato estándar; Viewing por slice; auto-sync al cambiar Sx; guías de corte legibles.

## Fuera de alcance

- Padding/solape entre slices (v1: cortes exactos; campo futuro si comp lo pide).
- Varios customs simultáneos (el diseño extensible lo permite crecer después).
- Ensamblador automático de slices en comp (candidato al generador de handoff Nuke/AE del research cross-DCC).
