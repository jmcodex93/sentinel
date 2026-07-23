# Fase 6.4 — Panel SPA: sección Tools + paridad (Settings/Doctor/Help) + limpieza de código muerto

**Fecha**: 2026-07-23
**Estado**: aprobado en brainstorm
**Contexto**: quinta y última sección de contenido del panel SPA (tras Overview 6.0, QC 6.1, Render 6.2, Deliver 6.3 — v1.19–v1.22). Con esto el panel SPA alcanza **paridad funcional** con el nativo. Rediseño, no port 1:1. Spec madre `2026-07-21-panel-spa-design.md`.

## Alcance (cerrado en brainstorm)

6.4 = **Tools** en el SPA + **paridad** (exponer Settings/Doctor/Help en el SPA) + borrar el código **ya muerto** (`collect_scene`, `TextureRepathingDialog`). El panel **nativo se queda como fallback**. El retiro del nativo (desregistrar `YSPanelCmd`, borrar `panel.py`/`user_areas.py`) es **Fase 6.5**, deliberadamente separada por perfil de riesgo.

## Decisiones cerradas (brainstorm)

1. **Tools = rejilla de acciones agrupada** espejando el nativo (Layout & Hierarchy / Animation / QC Marking / Asset), acción directa por botón.
2. **Sin read op ni enablement por selección**: los botones siempre activos; si falta una precondición, el resultado es un **toast** ("Select an object first"), no un `MessageDialog`. Sondear la selección en cada tick es derroche y la selección cambia constantemente.
3. **Sin confirm**: ninguna herramienta es destructiva (todas revertibles con Cmd+Z), a diferencia de borrar-materiales/FPS del palette.
4. **Núcleos sin-diálogo** (patrón 6.2): casi todas las herramientas hacen `MessageDialog` para feedback → se extrae un núcleo por herramienta que devuelve dict de estado; el wrapper nativo conserva su diálogo; el op llama solo al núcleo. Un `MessageDialog` dentro del drain de la cola congela C4D.
5. **Settings/Doctor/Help en el pie del rail** (persistentes, junto a "⌘ acciones") — replica el pie del panel nativo.

## Diseño

### 1. Ops (`panel_tools_ops.py`, nuevo — adaptadores finos)

- **Acciones de herramienta** (cada una → `{ok, error?, message?}`; sin `stamp` embebido — las mutaciones de escena SÍ ensucian el documento, así que el polling de `panel/state_stamp` existente las capta; no hace falta re-anclar como en repaths):
  - `panel/tools/hierarchy` — `scene_tools._create_hierarchy(doc)` (ya usa `safe_print`, sin diálogo → núcleo trivial o llamada directa envuelta).
  - `panel/tools/h_to_layers` — núcleo de `_hierarchy_to_layers` (hoy `MessageDialog` en orphans / no-null-groups → `{ok:False, error:"orphans"|"no_groups", count?}`).
  - `panel/tools/solo` — núcleo de `_solo_layers`/`_unsolo_layers` (smart-toggle; `MessageDialog` "No layers found" → `{ok:False, error:"no_layers"}`).
  - `panel/tools/drop_to_floor` — núcleo de `_drop_to_floor` (`safe_print`; `{ok:False, error:"no_selection"}` si nada seleccionado, `{ok:True, dropped:N}`).
  - `panel/tools/vibrate_null` — núcleo de `_create_vibrate_null` (`MessageDialog` no-doc / warning → dict).
  - `panel/tools/abc_retime` — núcleo de `_apply_abc_retime_tag` (`MessageDialog` no-doc / no-selection / failure → `{ok:False, error:"no_selection"|"apply_failed"}`).
  - `panel/tools/cam_simple` / `panel/tools/cam_shakel` — núcleo de `_merge_camera_file(doc, filename)` (`MessageDialog` file-not-found → `{ok:False, error:"file_not_found"}`). Cada op fija su `filename` (los dos templates de cámara del nativo).
  - `panel/tools/mark_safe_area` — núcleo de `_toggle_safe_area_mark(doc)` (smart-toggle; `MessageDialog` no-doc / hint → dict con `{marked:N, unmarked:N}` para el toast).
  - `panel/tools/open_hub` — abre el Asset Hub (ventana; reutiliza `reports_dialog.open_form(doc, "hub")` — sin foco deliver, es el Hub general).
- **Paridad — accesos del pie**:
  - `panel/tools/open_settings` — abre el form Settings (ventana; `open_form(doc, "form/settings")`, mismo host `FormDialog` que Save Version/Notes en modo ventana).
  - `panel/open_external {target}` — `target ∈ {"github","bug"}`; abre la URL fija con el opener OS cross-platform (`open_in_explorer`/opener existente). Doctor NO necesita op nuevo: reutiliza el palette `open_reports_doctor` ya existente.
- **Núcleos sin-diálogo**: extraer `_<tool>_core(doc[, filename])` de `scene_tools.py` para cada herramienta que hoy hace `MessageDialog`; el wrapper nativo (`_<tool>`) queda intacto llamando al núcleo + mostrando su diálogo, exactamente como los 7 núcleos de 6.2. Tests `_forbid_dialog` garantizan cero modales en la ruta del op.
- Registrar `PANEL_TOOLS_OPS` y mergear en `reports_dialog._OPS` (junto a PANEL_OPS/PANEL_RENDER_OPS/PANEL_DELIVER_OPS).

### 2. SPA — `ToolsSection`

- Reemplaza el placeholder de la sección Tools. Bloques agrupados (mismo `DeliverBlock`/`RenderBlock`-style shell): Layout & Hierarchy, Animation, QC Marking, Asset. Cada botón dispara su op vía un handler de `PanelPage` (`onTool(id)`), con un `busy` lock compartido (mismo idioma que las otras secciones) y toast del resultado. Asset Hub y los accesos del pie abren ventanas.
- Sin fetch/read op (acción-only). Sin sub-router. Lógica pura mínima en `panelTools.ts` si hace falta (p.ej. mapa id→label/grupo) + vitest; si es trivial, inline.
- **Rail footer**: `PanelRail` gana entradas persistentes bajo las secciones, junto a "acciones": **Settings**, **Doctor**, **Help** (Help puede ser un pequeño popover/submenú con GitHub + Report Bug, o dos entradas). Cada una dispara su op/deep-link. Adaptativo igual que el rail (iconos <560px / etiquetas ≥560px).
- Toasts para el resultado de cada herramienta (success/warn), reutilizando `useToast`.

### 3. Limpieza de código muerto

- Borrar `flows.collect_scene` (sin llamadores reales — solo menciones en comentarios/docstrings, que se conservan como prosa histórica).
- Borrar la clase `TextureRepathingDialog` y su función lanzadora en `dialogs.py` (superseada por `AssetHubDialog`; las referencias restantes en `dialogs.py` son comentarios dentro del Hub, se conservan).
- **No tocar** `panel.py`/`user_areas.py` ni desregistrar `YSPanelCmd` — eso es 6.5.
- Verificar en la implementación que no quedan llamadores vivos antes de borrar cada símbolo.

## Manejo de errores

- Ops nunca lanzan; núcleos devuelven dict de estado, NUNCA `MessageDialog` en la ruta del op (test `_forbid_dialog`). Precondición fallida (no-selection, no-layers, file-not-found, apply-failed) → `{ok:False, error}` → toast warn con copy claro. Éxito → toast success (con conteo cuando aporta: "Dropped N objects", "Marked N subjects"). Herramientas que abren ventanas: fallo del servidor → toast warn.

## Fuera de alcance

- Retirar el panel nativo (`YSPanelCmd`), borrar `panel.py`/`user_areas.py` — **Fase 6.5**.
- Reescribir los motores de scene_tools (solo extraer núcleos donde haya diálogo; no reescritura).
- Read op / enablement por selección para Tools (decisión: acción-only + toast).
- Rediseñar Settings/Doctor/Help como páginas nuevas (se reutilizan las superficies existentes: form Settings, Reports Doctor, opener OS para los enlaces).

## Verificación

- **pytest**: cada op de herramienta (contrato ok/error, precondición fallida → dict correcto, `_forbid_dialog` cero modales); núcleos byte-equivalentes al comportamiento nativo (mismos efectos de escena); `open_external` con target válido/inválido; ops registradas y mergeadas en `_OPS`. Harness fake-c4d.
- **vitest**: `ToolsSection` renderiza los 4 grupos + botones; rail footer con Settings/Doctor/Help; lógica pura si existe.
- **Live C4D** (escena real): cada herramienta ejecuta y muestra toast (éxito y precondición-fallida); Solo y Mark Safe Area smart-togglean; Asset Hub abre; Settings/Doctor/Help abren desde el pie del rail; Cmd+Z revierte una mutación (p.ej. Drop to Floor); sin popups desde las rutas del panel. El panel nativo sigue operativo en paralelo.
