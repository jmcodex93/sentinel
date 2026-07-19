# UI Fase 2 — Reports completo + triage de popups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** Todos los informes de Sentinel en la superficie Reports (QC, Doctor, Supervisor, Render Validation) con el design system, y el primer gran triage de popups informativos → captions/strips.

**Architecture:** Spec: docs/superpowers/specs/2026-07-18-ui-redesign-design.md. Base fase 1: webbridge (ops read-only vía cola main-thread), SPA en web/ (React+TS+Tailwind, tokens DESIGN.md), ReportsDialog host. Regla: ops de dispatch READ-ONLY/idempotentes (escrituras de settings idempotentes permitidas con justificación); nunca diálogos en dispatch.

## Global Constraints

- DESIGN.md manda en todo pixel nuevo. pytest verde tras cada tarea (baseline 433). Build SPA committeado y reproducible. Comentarios/UI inglés. No copiar código Overseer. Motores puros intocables salvo mappers nuevos puros. Los diálogos nativos viejos (Doctor/Supervisor) quedan como fallback igual que _show_delivery_summary.

---

### Task 1: Ops + mappers puros para QC / Doctor / Supervisor / Render Validation

**Files:** Modify: plugin/sentinel/webbridge.py (mappers puros + tests), plugin/sentinel/ui/reports_dialog.py (ops)
**Interfaces:** Produces ops: `report/qc` (run_all_checks+compute_score del doc activo → {scene, score{...}, ruleset{name,path,shadowed}, checks:[{id,label,severity,status,count,new,accepted,details[]}], disabled[]}); `report/doctor` (motor doctor.py → {sections:[{title,items:[{label,status,detail}]}]} — leer doctor.py para el shape real y mapear); `report/supervisor` (payload.folder o último de settings supervisor_last_folder; sentinel.supervisor.scan → {folder, shots:[{...}], meta} — mapear del motor real; guardar last folder = escritura idempotente permitida); `report/render_validation` (localizar y cargar el último informe JSON que escribe postrender tras Validate Render Output — leer postrender.py/flows para la ruta real; not found → {"error":"no_report"}). Mappers puros con tests (fixtures anonimizadas); ops delgadas en reports_dialog.
- [ ] TDD mappers; implementar ops; pytest verde; commit `feat(webui): report ops — qc, doctor, supervisor, render validation`

### Task 2: Páginas SPA + navegación

**Files:** Modify: web/src (router simple por estado o wouter ligero, Sidebar con 5 items), Create: páginas QcReportPage, DoctorPage, SupervisorPage (input de carpeta + Scan), RenderValidationPage; build → plugin/web committeado.
**Interfaces:** Consumes los payloads T1 (tipos TS espejo). Componentes nuevos reutilizables: CheckRow (status dot+label+count), Section, KeyValue list — según DESIGN.md. Estados loading/error/empty en todas. Mock por página (?mock=1) anonimizado.
- [ ] Implementar; npm build reproducible; oxlint/tsc clean; verificación Playwright local como T3 de fase 1; commit `feat(webui): Reports pages — QC, Doctor, Supervisor, Render Validation`

### Task 3: Entradas nativas + triage de popups (lote flows.py)

**Files:** Modify: plugin/sentinel/ui/panel.py (Doctor/Supervisor/Export QC → abren Reports con fallback legacy; Validate Render Output ofrece abrir Reports), flows.py.
**Interfaces:** Inventario primero: clasificar los MessageDialog/QuestionDialog de flows.py (15) en DECISIÓN (se queda) / INFORMATIVO (→ caption/strip/safe_print + registro). Convertir los informativos con superficie inline obvia (save version success, fix results, collect statuses ya migrados al Hub). Documentar el inventario en docs/superpowers/specs/2026-07-19-popup-triage.md con la clasificación de TODOS los sitios (flows 15, panel 45, dialogs 52) y cuáles convierte este lote.
- [ ] Inventario + conversiones flows + entradas panel; pytest; commit `feat(ui): Reports entries + popup triage batch 1 (flows)`

### Task 4: Triage lote 2 (panel.py) 

**Files:** Modify: plugin/sentinel/ui/panel.py
- [ ] Convertir informativos de panel.py con caption/strip cercano (AOV apply results, preset resets, tool results → captions de sección; los que no tengan superficie → dejar y anotar en el doc de triage para fase 4 toasts). pytest; commit `feat(ui): popup triage batch 2 (panel)`

### Task 5: Live + docs

- [ ] Controller: sync + restart; verificar las 4 páginas con datos reales (QC de la escena activa, Doctor, Supervisor sobre carpeta real de proyecto, Render Validation del último validate); popups convertidos muestran captions. Docs: CLAUDE.md (extender bullet Reports + entrada v1.13.x o v1.14.0), ROADMAP marcar fase 2. Merge.

## Self-Review
Cubre spec fase 2 (4 informes + triage). Shapes de motores se anclan a código real en T1 (doctor.py/supervisor.py/postrender.py leídos por el implementador). Popup triage documentado para no perder los no convertidos.
