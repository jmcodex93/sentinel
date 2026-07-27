# Fase 6.5 — Jubilar el panel nativo (teardown + extracción)

**Fecha**: 2026-07-27
**Estado**: aprobado en brainstorm
**Contexto**: con el panel SPA en paridad funcional (Overview/QC/Render/Deliver/Tools + Frame, tras v1.24.0), se retira el panel nativo (`YSPanel`/`YSPanelCmd`). NO es un borrado en bloque: `panel.py` y `user_areas.py` son monolitos con piezas vivas que la SPA y los tests aún usan y que deben extraerse primero. Spec madre `2026-07-21-panel-spa-design.md`.

## Decisiones cerradas (brainstorm)

1. **Postura**: extraer-y-borrar ahora (no deprecar). El panel SPA es el único panel; se pierde el panel nativo como fallback (los fallbacks de *formularios* en `dialogs.py` siguen).
2. **export_qc_report**: conservar la utilidad de export a JSON — reubicar a un módulo propio, no borrar.
3. **check_* legacy + StatusArea**: borrar y **migrar los tests** a los módulos reales (`sentinel.checks.*`, `CHECK_REGISTRY`, el nuevo módulo de export), no un shim de compatibilidad.

## Hallazgos de dependencia (por qué no es un borrado limpio)

- `panel_ops` importa `panel._select_objects` (el QC select de la SPA).
- `SentinelPaletteCmd` (comando moderno que abre el palette SPA vía `open_form(doc,"palette")`) vive en `panel.py` pero NO es nativo.
- `panel.export_qc_report` + `panel._scene_snapshot_b64` los usan los tests (`build_qc_report` ya vive en `reports.py`, no se mueve).
- `user_areas.py` NO se puede borrar: `dialogs.py` (fallbacks, en scope de "seguir") importa `TodoArea`, `TextureListArea`, `AssetListArea`, `AssetHubHeaderArea`, `PreflightStripArea`, `_violation_label`; `flows.py`/`reports.py` importan los helpers puros (`_accepted_entry_payload`, `_violation_label`). Solo el dibujo del panel nativo se puede recortar.
- El `.pyp` copia todos los símbolos de `panel/dialogs/ids/user_areas` a una "superficie de compatibilidad" que ~5 tests consumen.
- Ningún ref del registry QC usa fuente `"panel."` → los 12 `check_*` de `panel.py` son legacy muerto (el motor resuelve contra `sentinel.checks.*`).

## Diseño

### 1. Extracciones (helper vivo → su sitio propio)

- **`_select_objects`** → mover a `panel_ops.py` (su único consumidor). Importa `_iter_objs` de `common.helpers` (ya es el patrón). Actualizar `panel_ops._op_panel_qc_select` para llamarlo local en vez de `from sentinel.ui.panel import _select_objects`.
- **`SentinelPaletteCmd`** → mover a `panel_spa.py` (junto a `SentinelPanelSPACmd`; `panel_spa` no importa `panel`, movida limpia). Preserva el atajo de teclado al palette SPA.
- **`export_qc_report` + `_scene_snapshot_b64`** → nuevo módulo `plugin/sentinel/ui/report_export.py` (junto a `reports.py`, de donde importa `build_qc_report`; también usa `versioning`, `client_report`, `flows.load_versions_for_doc`, `c4d.storage.SaveDialog`). Byte-equivalente al comportamiento actual.

### 2. Borrados

- **`plugin/sentinel/ui/panel.py` → BORRAR el fichero entero** (tras las 3 extracciones): los 12 `check_*` adapters, `check_cross_aspect_safe_area*` (copias), `_rules_header_text`, `_current_module` (el de panel), `_active_rules_for_doc` (alias local), el diálogo `YSPanel` (~2400 líneas) y `YSPanelCmd`.
- **`plugin/sentinel/ui/user_areas.py` → RECORTAR**: eliminar solo el dibujo exclusivo del panel nativo — `ScoreHeader`, `StatusArea`, `HistoryArea`, `_badge_color_for_status` (~lines 266-767). Todo lo demás (helpers puros `_violation_label`/`_entry_label`/`_accepted_entry_payload`/`_stale_suffix`/`format_baseline_row_message` + las UserAreas usadas por `dialogs.py`) se queda.

### 3. `.pyp` (bootstrap)

- Quitar el registro de `YSPanelCmd` (`RegisterCommandPlugin` del panel nativo) y su bloque.
- Cambiar el import: `from sentinel.ui.panel import YSPanelCmd, SentinelPaletteCmd` → `from sentinel.ui.panel_spa import SentinelPanelSPACmd, SentinelPaletteCmd`.
- Quitar `_panel` del import y del bucle de superficie de compatibilidad (`for _module in (_dialogs, _ids, _user_areas)`).
- Registros que SIGUEN: `SentinelPanelSPACmd`, `SentinelPaletteCmd`, el frame tag.

### 4. Migración de tests (~5 ficheros)

- `test_baseline_artifacts.py`, `test_qc_action_registry.py`: `sentinel_module.export_qc_report` → `from sentinel.ui.report_export import export_qc_report`.
- `test_scene_check_results.py`: `sentinel_module.check_*` → los reales de `sentinel.checks.scene`/`render`.
- `test_qc_registry_score.py`: `StatusArea.ROW_KEYS` → derivar del `CHECK_REGISTRY` directamente (lo que el test realmente valida: que el registry dirige las filas).
- `tests/c4d_runner/run_fixtures.py`: si usa `export_qc_report`/`check_*` del panel → apuntar a los nuevos homes.
- Verificar caso a caso qué símbolo exacto usa cada test y reapuntarlo; nunca reintroducir un shim.

### 5. Sin tocar

- `dialogs.py` (fallbacks de Save Version/Notes/Settings/Gate/AssetHub — la red de seguridad de los formularios SPA).
- Panel SPA (`panel_spa.py` salvo el add de `SentinelPaletteCmd`), todas las `*_ops.py`, `frame_tag.py`, el comando/página del palette SPA.

## Manejo de errores / riesgo

- Riesgo asumido: sin panel nativo de fallback (si el servidor/webview SPA fallara al arrancar, no hay panel). Mitigación: la SPA es daily-driver probado; los fallbacks de formularios siguen; el borrado es reversible por git si hiciera falta.
- Invariante de seguridad: tras el teardown, `grep` no debe encontrar NINGÚN import vivo de `sentinel.ui.panel` (ni `from ... import`, ni `ui.panel.`) fuera de comentarios/docstrings.

## Fuera de alcance

- Borrar `dialogs.py` o los fallbacks de formularios.
- Reescribir `user_areas.py` más allá de recortar el dibujo del panel.
- Tocar la lógica de los checks reales (`sentinel.checks.*`) o del registry.

## Verificación

- **pytest**: suite completa verde tras la migración; los tests reapuntados ejercitan los módulos reales (checks, report_export, registry). Ningún test importa `sentinel.ui.panel`.
- **grep de invariante**: `grep -rn "sentinel.ui.panel\b\|from sentinel.ui import panel\b\|ui\.panel\." plugin/ tests/` → cero imports vivos (solo prosa).
- **Import del `.pyp`**: `python3 -c "ast.parse(...)"` + carga vía el fixture `sentinel_module` sin errores (la superficie de compat ya sin `_panel`).
- **Live C4D**: el panel SPA abre y dockea igual; el comando "Sentinel Panel" nativo YA NO aparece (solo "Sentinel Panel (SPA)"); el comando/atajo del Command Palette sigue abriendo el palette; el QC select de la SPA (que usaba `_select_objects`) sigue seleccionando en escena; Export QC report (si se ejercita desde donde quede cableado) escribe el JSON+HTML igual.
