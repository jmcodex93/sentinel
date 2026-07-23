# Fase 6.3 — Panel SPA: sección Deliver

**Fecha**: 2026-07-23
**Estado**: aprobado en brainstorm
**Contexto**: cuarta sección de contenido del panel SPA (tras Overview 6.0, QC 6.1, Render 6.2 — v1.19/v1.20/v1.21). Rediseño, no port 1:1. Spec madre `2026-07-21-panel-spa-design.md`.

## Decisiones cerradas (brainstorm)

1. **Layout = bloques apilados con status en cabecera** (coherente con QC/Render). Tres bloques: **Version**, **Notes**, **Deliver**.
2. **Formularios absorbidos = sub-vista dentro del panel** (no ventana). Al pulsar Save Version / Edit Notes, el contenido del panel cambia al formulario COMPLETO reutilizando los componentes `SaveVersionPage`/`NotesPage` que ya existen (montados inline con `onBack`/`onDone`), con botón "← Deliver". Cero ventanas nuevas. Submit reutiliza las ops `form/save_version/*` y `form/notes/*` (probadas desde Fase 4) — cero lógica de submit duplicada.
3. **Recent Versions = lista en la SPA** (nueva; el `HistoryArea` nativo era un UserArea): últimas N con badge de status (WIP/TR/CR/FINAL color-coded) + filtro (All/WIP/TR/CR/FINAL); click en una fila → confirma inline y abre ese `.c4d`.
4. **Hub / Supervisor / Delivery Summary = accesos** (abren sus ventanas Hub/Reports, deep-link) — NO se absorben. Reutilizan `runPaletteAction`/`open_form`/`open_reports` existentes.
5. **Delivery Summary condicional**: el acceso solo aparece cuando hay un manifest colectado con sección de assets junto a la escena abierta (mismo criterio que `_delivery_manifest_available` nativo).

## Diseño

### 1. Ops (`panel_deliver_ops.py`, nuevo — adaptadores finos, cero lógica duplicada)

- **`panel/deliver`** (read-only, bloques AISLADOS como `panel/overview`/`panel/render`):
  ```
  { "version": {
        "last": {"version": int, "status": str, "age": str|null,
                 "qc_label": str|null} | null,   # null = sin versiones / sin guardar
        "unsaved": bool,                          # doc sin path → Recent vacío + nota
        "recent": [ {"version": int, "status": str, "age": str|null,
                     "qc_label": str|null, "path": str} ]  # <= N filas, ya filtrado NO
      } | null,
    "notes": {"summary": str, "todos_pending": int, "notes_present": bool,
              "unsaved": bool} | null,
    "deliver": {"has_manifest": bool} | null }
  ```
  Fuentes reales (nada inventado): version = `versioning.get_latest_version_info` + `load_versions_for_doc` + `format_version_row`/`format_history_qc_label`/`_humanize_time_diff`; notes = `notes.get_notes_path`/`load_notes`/`summarize_notes`/`has_pending_todos` (mismos reads que `_panel_deliver_block` y `web_ops._op_form_notes_state`); deliver = detector de manifest colectado (extraer el criterio de `panel._delivery_manifest_available` a un helper puro reutilizable, o replicar su comprobación de `assets_schema` en el manifest junto a la escena).
  - `recent` incluye TODAS las versiones (sin filtrar) hasta un tope razonable (p.ej. 15); el filtro por status vive en la SPA (pura, sin round-trip) igual que hoy el combo nativo filtra en cliente. Cada fila lleva su `path` absoluto para el open.
- **`panel/deliver/open_version {path}`** (acción → `{ok, error?, opened?, stamp?}`): abre ese `.c4d`. Reutiliza el mismo camino del click nativo (`_on_history_row_click`): extraer un núcleo sin diálogo `open_version_core(path)` que devuelve un dict de estado (`{ok, error}`) con las mismas guardas que el nativo — archivo no existe (`file_not_found`), ya es el documento activo (`already_active`), path vacío (`bad_path`) — y ejecuta `LoadFile`/`LoadDocument`. El wrapper nativo conserva sus `MessageDialog`; el op mapea el dict a la SPA (patrón dialog-free-core de 6.2 — un `MessageDialog` en el drain de la cola congela C4D). NO gestiona "cambios sin guardar" con un diálogo bloqueante: si el doc activo tiene cambios, el op devuelve `{ok:False, error:"unsaved_changes"}` y la SPA lo resuelve inline (confirmar y abrir de todas formas → `open_version {path, force:true}`, o cancelar). Alternativa aceptable si `LoadFile` ya muestra su propio prompt nativo de guardado fuera del drain: documentarlo y no duplicar la guarda.
- **Registrar `PANEL_DELIVER_OPS`** y mergear en `reports_dialog._OPS` (junto a PANEL_OPS/PANEL_RENDER_OPS).

Nada nuevo de submit: Save Version y Notes usan las ops `form/*` ya registradas.

### 2. SPA — `DeliverSection` con sub-router

- **Sub-estado**: `deliverView: "main" | "save_version" | "notes"` (estado local de la sección, no del panel global). En `main` se muestran los tres bloques; en `save_version`/`notes` se monta el formulario absorbido a pantalla de sección + un header "← Deliver".
- **Absorción de formularios**: `SaveVersionPage`/`NotesPage` ganan props OPCIONALES `onBack?: () => void` y `onDone?: () => void` (default no-op, preservan el host `FormDialog` intacto — el switch `form/save_version`/`form/notes` de `App.tsx` los sigue montando sin props). Cuando el panel los monta: `onBack` vuelve a `main`; `onDone` (tras submit OK) vuelve a `main` y re-fetchea `panel/deliver`. Si hoy la página no expone un punto de "submit correcto" para enganchar `onDone`, añadir la llamada en su handler de éxito (junto al toast que ya emite). Mejora mínima justificada; no reescritura.
- **Bloque Version** (`main`): status `v007 TR · hace 2h · QC 9/12` (de `version.last`; si `null` → "sin versiones" / "escena sin guardar" según `unsaved`). Botón **Save Version** → `deliverView="save_version"`. **Recent Versions**: filtro (All/WIP/TR/CR/FINAL, cliente) + lista de filas con badge de color por status; click en fila → confirmación inline (patrón confirm de QC/Render) → `panel/deliver/open_version {path}`; `unsaved_changes` → segunda confirmación → `{force:true}`. Estados vacíos equivalentes a los nativos ("Save the scene first" / "No versions match filter").
- **Bloque Notes** (`main`): status `⚠ Notes: texto + 3 TODOs (2 pendientes)` (de `notes.summary`, prefijo ⚠ si `todos_pending>0`). Botón **Edit Notes** → `deliverView="notes"`.
- **Bloque Deliver** (`main`): **Collect Scene** → abre el Hub en foco deliver (reutilizar la acción palette/`open_form` que ya lo hace); **Supervisor** → `runPaletteAction`/`open_reports` a la página Supervisor; **Delivery Summary** → deep-link a Reports Delivery Summary, VISIBLE solo si `deliver.has_manifest`.
- **Refresco**: fetch `panel/deliver` al entrar en la sección + en cambio de stamp (polling existente); `open_version` y los submit de formulario re-anclan/refrescan. Bloque `null` → nota "no disponible" (resiliencia como overview).
- **Rail**: badge de la sección Deliver opcional, NO en 6.3 (sin contador de estado obvio; el ⚠ de TODOs pendientes vive en el bloque). Dejar sin badge.
- **Lógica pura** (formato de status por bloque, filtro de recent por status, color de badge por status, gating de confirmación) en `panelDeliver.ts` + vitest.

### 3. Componentes SPA

- `DeliverSection.tsx` (sub-router main↔save_version↔notes, fetch, confirm bar, toast).
- Sub-bloques testeables: `VersionBlock` (+ `RecentVersionsList` con filtro y filas), `NotesBlock`, `DeliverAccessBlock`. Reutilizar el badge de status si ya existe uno en Reports/QC; si no, uno mínimo en `panelDeliver.ts` + componente.
- `SaveVersionPage`/`NotesPage`: sólo se les añaden props opcionales `onBack`/`onDone`; su cuerpo no se reescribe.

## Manejo de errores

- Ops nunca lanzan; bloques aislados (un fallo no blanquea el resto). `open_version` devuelve dict de estado (file_not_found / already_active / bad_path / unsaved_changes), NUNCA un `MessageDialog` en la ruta del op. Doc sin guardar → `unsaved:true` en version/notes → la SPA muestra "guarda la escena primero" en Recent y en el summary, sin crashear. Sin manifest → Delivery Summary ausente (no deshabilitado).

## Fuera de alcance

- Reescribir Save Version / Notes (se absorben tal cual, sólo props de navegación).
- Reimplementar Hub / Supervisor / Delivery Summary (deep-link/accesos).
- El gate de calidad de Save/Collect sigue siendo modal nativo dentro de esos flujos síncronos (no se rediseña aquí; `form/gate` es triage independiente del palette, ya existente).
- Retirar la pestaña Deliver nativa (6.4).
- Tocar los motores de versionado/notas/collect (solo consumir; si `_on_history_row_click` está acoplado a UI con `MessageDialog`, extraer un núcleo sin diálogo reutilizable — mejora mínima, no reescritura).

## Verificación

- **pytest**: `panel/deliver` (bloques aislados, un fallo no blanquea; fuentes reales; `unsaved` cuando el doc no tiene path; recent ordenado y con path por fila; has_manifest true/false); `open_version` (contrato: ok, file_not_found, already_active, bad_path, unsaved_changes, force); `_forbid_dialog` en la ruta del op (cero modales). Harness fake-c4d.
- **vitest**: status por bloque (pura), filtro de recent por status, color de badge por status, gating de confirmación (open + unsaved→force), sub-router main↔save↔notes.
- **Live C4D (SHOT_18)**: bloque Version muestra última versión + QC; **Save Version desde el panel** (sub-vista) crea `_v###`, vuelve a main, Recent y la caption se actualizan; filtro de Recent funciona; click en una fila abre ese `.c4d` (con confirmación; y con segunda confirmación si el activo tiene cambios); **Edit Notes** (sub-vista) edita texto + TODOs y el summary refleja pendientes; Collect abre el Hub; Supervisor abre Reports; Delivery Summary aparece solo con manifest presente y abre su página; sin popups en las rutas del panel; un Cmd+Z tras un Save Version se comporta como el nativo.
