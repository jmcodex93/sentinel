# UI Fase 4 — Formularios a SPA + toasts + ⌘K Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Save Version, Notes, Settings y Gate Triage como páginas SPA (look Linear) en una ventana de formulario embebida; sistema de toasts (mueren los 12 popups diferidos ligados a estos flujos); command palette ⌘K sobre las acciones del plugin.

**Architecture:** Base fases 1-3. NOVEDAD: ops de MUTACIÓN — exige cerrar el gap de idempotencia de la cola (un submit con timeout hoy se despacha igualmente después). Ventana `FormDialog` (HTMLVIEWER, tamaño por formulario, async) con la misma SPA (`?page=form/...`); Reports queda para lectura. Los flujos nativos siguen siendo el fallback ante excepción (patrón _open_reports).

## Global Constraints

- DESIGN.md manda. pytest verde tras cada tarea (baseline 456). Build committeado reproducible. Sin copiar Overseer. Los motores (versioning, notes, gate, settings) NO se duplican: las ops llaman a los mismos helpers que usan los diálogos nativos hoy (ground cada uno). Decisiones dentro de una página de formulario = botones de la página (permitido); popups modales nuevos = prohibidos salvo bloqueo real. Los diálogos nativos actuales se conservan como fallback (patrón legacy).
- Mutaciones SOLO vía cola con cancelación (T1); jamás desde el thread del servidor.

---

### Task 1: webbridge — cancelación de requests + soporte de mutación

**Files:** Modify: plugin/sentinel/webbridge.py, tests/test_webbridge.py
**Interfaces:** `MainThreadQueue.submit` marca `cancelled=True` al expirar el timeout; `drain` SALTA los cancelados (y lo cubre un test con dispatch-espía). Documentar: con esto las ops de mutación son seguras (una petición que el cliente dio por muerta no se ejecuta tarde). Añadir `submit` param `timeout` ya existe — sin API nueva más allá del flag interno. Actualizar el comentario de invariante (de "read-only obligatorio" a "mutaciones permitidas; la cancelación garantiza no-ejecución-tardía; handlers siguen debiendo ser seguros ante reintento del cliente").
- [ ] TDD (test: submit corto timeout → drain posterior NO despacha; test: happy path intacto). pytest verde. Commit: `feat(webui): request cancellation — safe mutation ops through the queue`

### Task 2: ops de formularios (get + submit por formulario)

**Files:** Modify: plugin/sentinel/ui/reports_dialog.py (o módulo hermano forms_ops), webbridge.py (mappers/validadores puros + tests)
**Interfaces:** Por formulario, un op GET de estado inicial y un op POST de envío, reusando los helpers nativos EXACTOS (ground: SaveVersionDialog + smart_save_version / _handle_save_version en panel; NotesDialog + notes.py load/save; SentinelSettingsDialog InitValues/Command-save + GlobalSettings; GateTriageDialog + gate.py evaluate/apply/accept). Shapes documentados en docstrings (T3 los espeja):
- `form/save_version/state` {scene, last_version, qc:{score}, status_options, warn_final} · `form/save_version/submit` {comment, status, custom_status} → {ok, new_version, path} | {error}
- `form/notes/state` {notes_text, todos:[{text,done}], scene_base} · `form/notes/submit` {notes_text, todos} → {ok}
- `form/settings/state` {fps, fps_locked(+reason), compositor, multipart_default, slate(+locked), mv_max, snapshot_dir(+detected,+locked), recent_versions} · `form/settings/submit` → {ok}
- `form/gate/state` (evalúa el gate para el doc activo: failing checks con severidad y fixables) · `form/gate/submit` {action: fix_all|accept:{ids,author,reason}|proceed|cancel} → resultado
- `palette/actions` (T4): lista de acciones {id, label, group, enabled} · `palette/run` {id} → resultado con mensaje toast
- [ ] Validadores/mappers puros con tests (p.ej. save_version: comentario vacío → error; status custom alfanumérico — copiar reglas reales del diálogo nativo). pytest verde. Commit: `feat(webui): form ops — save version, notes, settings, gate + palette registry`

### Task 3: SPA — sistema de formularios + toasts + las 4 páginas

**Files:** web/src (FormField/TextInput/TextArea/Select/Checkbox/TodoList components según DESIGN.md; Toast provider + hook; páginas SaveVersionPage, NotesPage, SettingsPage, GateTriagePage bajo rutas form/*), build a plugin/web
**Interfaces:** Consume shapes T2. Toast: success/info/warn variantes, 4s auto-dismiss, clicable. Submit deshabilitado mientras pending; errores inline bajo el campo (no popups). Página gate: lista de checks con severidad + 3 acciones del spec (Fix auto-fixables / Accept con author+reason obligatorios / Proceed) + Cancel. Mocks por página. Estados load/error. Validación espejo de la nativa.
- [ ] tsc/oxlint/build; Playwright de las 4 páginas + toast visible; pytest intacto. Commit: `feat(webui): form pages — save version, notes, settings, gate triage + toasts`

### Task 4: FormDialog host + ⌘K + recableado del panel

**Files:** Create/Modify: plugin/sentinel/ui/reports_dialog.py (FormDialog reutilizando server/cola; tamaños por página), panel.py (Save Version / Edit Notes / Settings / gate hook → FormDialog con fallback nativo), palette (SPA page + CommandData plugin "Sentinel Command Palette" en sentinel_panel.pyp registrado con id nuevo — ground cómo se registran los CommandData existentes; atajo lo asigna el usuario, documentar en el menú Help una entrada "Command Palette")
**Interfaces:** `open_form(doc, page, w, h)`; gate hook: donde hoy se abre GateTriageDialog (save + collect paths — ground en flows/dialogs) va el FormDialog si gates_enabled, fallback nativo. Palette actions v1: abrir páginas (hub, reports, forms), fixes auto (via apply_fixes), save version, collect (abre Hub deliver), rescan. Toast tras acción.
- [ ] pytest verde; py_compile. Commit: `feat(webui): form dialog host, panel rewiring, command palette`

### Task 5: Live + docs + cierre

- [ ] Controller: sync + restart; por formulario: abrir desde panel, estado inicial correcto, submit real (guardar una versión de prueba en una escena temporal, notes round-trip, settings round-trip respetando locks, gate con la fixture violating), toast visible, fallback probado (matar server → botón usa diálogo nativo). Palette: abrir, buscar, ejecutar 2 acciones. Cmd+Z tras mutación HTML (el undo de C4D debe reflejar el save/fix). Docs: CLAUDE.md v1.16.0 + bump; ROADMAP fase 4 [x]; triage doc: marcar los diferidos que mueren. Merge + push según patrón.

## Self-Review
Idempotencia resuelta ANTES de la primera mutación (T1 bloquea T2). Formularios = paridad con los diálogos nativos actuales, sin features nuevas (YAGNI). Fallbacks nativos en todos los puntos de entrada. Palette v1 acotada a acciones existentes.
