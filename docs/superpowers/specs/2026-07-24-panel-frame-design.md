# Fase 6.6 — Panel SPA: sub-vista Frame (flujo multi-formato consolidado)

**Fecha**: 2026-07-24
**Estado**: aprobado en brainstorm
**Contexto**: consolidación del flujo multi-formato (cross-aspect delivery), hoy fragmentado en 3 secciones del panel SPA: **Sentinel Frame** (bloque de Render), **Mark Safe Area** (Tools) y **QC #12 Cross-Aspect** (QC). Surge de la auditoría de diseño de producto post-6.4. Spec madre `2026-07-21-panel-spa-design.md`.

## Decisiones cerradas (brainstorm)

1. **Objetivo**: co-localizar las 3 acciones dispersas + **pistas ligeras** (estado / siguiente-paso sugerido, sin forzar orden — NO un wizard).
2. **Ubicación**: **sub-vista dentro del panel**, abierta desde el bloque *Sentinel Frame* de la sección Render (patrón sub-router local, como Deliver→Save Version/Notes). El rail se queda en 5 secciones; framing sigue bajo Render (donde vive el setup de render).
3. **Alcance**: solo lo que hoy está disperso entre secciones (Frame status + Add/Select, Mark/Unmark subjects, QC #12 inline, pistas). Las acciones "pesadas" del tag (Create/Update Takes, Set Output, Remove Stale) y la config fina **siguen en el Attribute Manager del tag** (ya son un sitio único; se llega con "Select tag"). Cero extracción de núcleos nuevos desde los handlers del tag.

## Diseño

### 1. Entrada (sección Render)

El bloque *Sentinel Frame* de la sección Render (hoy: `sin tag` / `en <cámara> · N formatos` + Add/Select) gana:
- Una **pista de estado** en su status line (tinte warn cuando QC #12 tiene sujetos violando), derivada del mismo `panel/frame` read.
- Un botón **"Manage frame →"** que entra en la sub-vista Frame.
(Add to camera / Select tag pueden quedar en el bloque de Render como acceso rápido y también dentro de la sub-vista — sin duplicar lógica, misma op.)

### 2. Sub-vista Frame (bloques apilados)

`RenderSection` gana un sub-router local (`renderView: "main" | "frame"`), igual que `DeliverSection`. En `frame` renderiza:

1. **Hint / next-step line** (arriba) — derivada del estado, pura en TS (`panelFrame.ts`):
   - sin tag → *"Add a Sentinel Frame to your camera to start."*
   - tag sin sujetos → *"Mark your key subjects (logo, title, character) so QC #12 can verify them."*
   - tag + sujetos + QC #12 pass → *"✓ All marked subjects stay inside every format's safe area."*
   - violaciones → *"⚠ N subject(s) leave the safe area in M format(s)."*
   - stale → *"Takes out of date — update from the tag."* (si `stale`, prioriza esta pista)
2. **Sentinel Frame block** — status (`on <camera> · N formats` / `No Sentinel Frame tag.`) + **Add to camera** (reusa `panel/render/add_frame_tag`) + **Select tag** (reusa `panel/render/select_frame_tag`; deshabilitado si no hay tag). Nota estática: *"Formats, output & Take generation live on the tag — Select to edit."*
3. **Subjects block** — `N subjects marked` + **Mark / Unmark selected** (reusa `panel/tools/mark_safe_area`).
4. **QC #12 (Cross-Aspect Safe Area) block** — status pass/violaciones (de la fila `cross_aspect` del scoring QC compartido) + **Select** (sujetos que violan, reusa `panel/qc/select {check_id:"cross_aspect"}`) + **"Details in QC →"** (deep-link a la sección QC). Estado neutral cuando no hay sujetos marcados o no hay formatos (QC #12 devuelve OK trivial).

### 3. Ops (`panel_frame_ops.py`, nuevo — adaptador fino de LECTURA)

- **`panel/frame`** (read-only, bloques AISLADOS como overview/render):
  ```
  { "frame": {"has_tag": bool, "camera_name": str|null, "format_count": int|null, "stale": bool} | null,
    "subjects": {"marked_count": int} | null,
    "qc12": {"pass": bool, "violations": int} | null }
  ```
  Fuentes reales (nada inventado): frame = `panel_render_ops._find_sentinel_frame_tag` + camera/format_count (ya expuestos por el frame block) + detector de staleness del tag; subjects = recorrido del doc contando `safe_areas.is_object_marked_safe_area`; qc12 = fila `cross_aspect` de `panel_ops._run_qc_scoring(doc)` (mismo scoring compartido que Overview/QC/Reports — cero re-derivación). `stale` reutiliza el `_is_stale_from_signature`/hash del tag (`frame_tag.py`) si es accesible sin diálogo; si no, se omite `stale` (pista degradada) — a decidir en implementación, nunca inventado.
- **Acciones**: CERO ops nuevas. La sub-vista reutiliza las existentes: `panel/render/add_frame_tag`, `panel/render/select_frame_tag`, `panel/tools/mark_safe_area`, `panel/qc/select`. Los toasts y el refresco siguen el patrón de las otras secciones (aplicar resultado + `load(true)` del `panel/frame`).
- Registrar `PANEL_FRAME_OPS` y mergear en `reports_dialog._OPS`.

### 4. SPA

- `panelFrame.ts` (puro + vitest): tipos `PanelFrameState`; `frameHint(state)` → la línea de pista (prioridad stale > violaciones > sin-sujetos > pass > sin-tag); `frameStatusLine`, `qc12StatusLine`.
- `FrameSubview.tsx` (o dentro de `RenderSection`): los 4 bloques; recibe `frame` data + callbacks (add/select/mark/select-qc12/back/details). Reusa el confirm/toast/busy idiom de las otras secciones.
- `RenderSection` gana el sub-router `main`/`frame` + el "Manage frame →" y la pista en el bloque Frame de `main`.
- `PanelPage` posee `frameState`/`loadFrame`/stamp igual que render/qc; fetch al entrar en `frame`, refetch por stamp.

### 5. Cambio en Tools

**Mark Safe Area sale de Tools**: se elimina el grupo "QC Marking" de `TOOL_GROUPS` (Tools queda = Layout & Hierarchy + Animation). El op `panel/tools/mark_safe_area` se mantiene (ahora llamado desde la sub-vista Frame). Actualizar el test de `TOOL_GROUPS`.

## Manejo de errores

- Ops nunca lanzan; bloques aislados (un fallo no blanquea el resto). Sin tag → bloques con `has_tag:false` / `qc12` OK trivial → la sub-vista muestra el estado inicial y la pista "add a frame". QC #12 sin sujetos/sin formatos → pass trivial (mismo comportamiento que el check nativo). Acciones que fallan precondición → toast (reutilizando el contrato existente de cada op).

## Fuera de alcance

- Traer Create/Update Takes / Set Output / Remove Stale / config fina a la SPA (viven en el tag/AM; se llega con Select).
- Quitar QC #12 de la sección QC (es 1 de los 12 checks; la sub-vista lo refleja, no lo reemplaza).
- Nuevas ops de acción (todas se reutilizan).
- Retirar el panel nativo (6.5) — independiente.

## Verificación

- **pytest**: `panel/frame` (bloques aislados; no-tag → has_tag:false; tag → camera/format_count; marked_count contra fake docs; qc12 = fila cross_aspect del scoring compartido; sin sujetos → qc12 pass trivial). Harness fake-c4d.
- **vitest**: `frameHint` (prioridad stale>violaciones>sin-sujetos>pass>sin-tag), status lines, sub-router main↔frame, `TOOL_GROUPS` sin "QC Marking".
- **Live C4D** (escena real con Sentinel Frame + sujetos marcados): el bloque Frame de Render muestra la pista; "Manage frame →" entra en la sub-vista; Add/Select tag funcionan; Mark/Unmark subjects actualiza el contador y QC #12; con un sujeto fuera de safe area la pista pasa a "⚠ N violan M formatos" y Select los selecciona; "Details in QC →" navega a QC; Mark Safe Area ya NO está en Tools; Cmd+Z revierte una marca.
