# Fase 6.1 — Panel SPA: sección QC

**Fecha**: 2026-07-22
**Estado**: aprobado en brainstorm (companion visual — mockups en `.superpowers/brainstorm/40035-1784707797/content/qc-list.html`)
**Contexto**: primera sección de contenido del panel SPA (tras 6.0 host+Overview, v1.19.0). Rediseño, no port 1:1: el nativo tenía 3 botones por fila (ruidoso); la sección SPA es signal-first (watchdog dockeado). Spec madre `2026-07-21-panel-spa-design.md`.

## Decisiones cerradas (brainstorm)

1. **Layout = "C refinada"**: tarjetas FAIL (rojo) arriba → WARN (ámbar, más ligeras) → línea plegada `▸ N OK · M disabled`. Acción directa en la tarjeta, sin expandir para actuar. Coherente con la tarjeta QC del dashboard Overview.
2. **Cada tarjeta muestra solo las acciones que ese check soporta**: `Select` si `can_select`, `Fix` si `can_fix`, `Info` y `Accept` siempre.
3. **Recheck = solo lee la caché**: la sección lee `check_cache` (mismo scoring que Overview/Reports); el polling la refresca por stamp. Abrir la sección NO re-dispara checks. El re-check real lo sigue provocando el motor por dirty-flag como hoy.
4. **Accept = todo el check de golpe**: aceptar "Lights · 8 new" con autor+razón sella las 8 violaciones actuales en el baseline (mismo camino que `BaselineActionDialog`/gate). Reutiliza `baseline.py`. No violaciones individuales.
5. **Cero popups**: Accept = formulario inline (autor pre-rellenado del artista guardado + razón), Info = detalle expandible, Fix = confirmación inline para los destructivos (contrato palette existente).

## Diseño

### 1. Ops (`panel_ops.py`)

- **`panel/qc`** (read-only): QC completo por check desde el scoring compartido (`active_rules_for_doc → run_all_checks → compute_score → qc_report_payload`, ya en el módulo — misma llamada que `_panel_qc_block`, ampliada a la lista completa). Payload:
  ```
  { "score": {"passed","total","disabled"},
    "fail": [check], "warn": [check], "ok_count": int, "disabled_count": int }
  check = { "id","label","severity","count","new","accepted",
            "detail": str,               # texto expandible (del qc_report_payload)
            "can_select": bool,          # el check tiene selección en escena
            "can_fix": bool, "fix_action_id": str|null,   # palette id (fix_lights…) o null
            "accepted_all": bool }       # todas las violaciones actuales ya aceptadas
  ```
  Los flags `can_select`/`can_fix`/`fix_action_id` salen del `CHECK_REGISTRY` (severidad, fix capability ya declarados ahí) — no se inventan.
- **`panel/qc/select {check_id}`** (mutación): selecciona en escena los objetos del check vía el selector del motor QC (el mismo que usa el botón Select nativo — reutilizar, no duplicar). `{ok, stamp}`.
- **`panel/qc/accept {check_id, author, reason}`** (mutación): valida author/reason no vacíos → sella las violaciones actuales del check en el baseline vía `baseline.py` (mismo camino que el nativo/gate) → invalida `check_cache` → `{ok, stamp, qc}` (QC refrescado embebido para evitar un segundo fetch).
- **Fix**: reutiliza `palette/run {id: fix_action_id, confirm?}` (confirm contract existente para materials/fps) — cero op nueva.
- **Info**: sin op — es el campo `detail` del payload, expandido en cliente.
- **Fix all fixables**: reutiliza el flujo batch existente (`apply_fixes` vía la op que ya lo expone — verificar cuál; si no hay una directa, `palette/run` por cada fixable NO — usar el `apply_fixes` batch en un solo undo como hace el gate/collect). Op `panel/qc/fix_all` fina sobre `apply_fixes` scope objetos, un undo, `{ok, stamp, qc}`.
- **Stills detection (check Y fix, misma decisión)**: `is_stills_preset` (compartida por `check_fps_range` y `_fix_one_render_data`) es **substring-based** — un preset cuenta como stills si su nombre normalizado CONTIENE cualquier token de `stills_presets` (default `["stills", "lookdev", "look_dev", "beauty"]`, configurable por ruleset). Un preset de proyecto que contenga uno de estos tokens en cualquier parte del nombre (p.ej. "RS-LookDev 2026") se trata como stills; nombrar presets de estudio con esto en mente (evitar tokens genéricos que aparezcan dentro de nombres de animación).

### 2. SPA — `PanelQcSection`

- Dentro de `PanelPage`, sección "QC" (hoy placeholder). Fetch `panel/qc` al entrar + en cada cambio de stamp (re-anclaje ya existente).
- **Cabecera**: `QC N/12` + botón **Fix all fixables** (deshabilitado si no hay fixables) + confirm inline si el lote incluye destructivos.
- **Tarjetas FAIL** (`--color-status-fail` borde/tinte) → **WARN** (`--color-status-warn`, tinte más ligero) → línea plegada `▸ N OK · M disabled` (abre lista read-only de los que pasan).
- **Tarjeta**: label + chip severidad + `N new (M accepted)` + detalle 1-2 líneas. **Info** → expande `detail` completo. Acciones condicionadas: `Select` (can_select), `Fix` (can_fix; confirm inline destructivos, respeta enabled/reason del palette como en Overview), `Accept…` → mini-form inline (autor pre-rellenado de `GlobalSettings.load_artist_name()` vía un campo del payload o el settings ya disponible; razón obligatoria) → `panel/qc/accept`.
- Tras cualquier mutación: toast + el `qc` embebido en la respuesta re-renderiza (o re-fetch si no viene) + re-ancla stamp. Selección de escena limpia no aplica (esto no es tabla).
- Badge del rail QC (ya existe en 6.0) sigue reflejando fails — se alimenta del overview, coherente.
- Lógica pura de agrupado/acciones-por-check en `web/src/lib/panel.ts` (o `panelQc.ts`) + vitest.

## Manejo de errores

- Ops nunca lanzan (patrón); accept con autor/razón vacíos → `{ok: False, error}` inline (no popup). Fix respeta el confirm contract. Bloques resilientes como el overview.

## Fuera de alcance

- Violaciones individuales (accept es por check).
- Re-check forzado / botón Re-scan (la caché se invalida sola por dirty-flag).
- Retirar el QC del panel nativo (va en 6.4 con la jubilación).
- Tocar el motor QC / baseline / fixes (solo se consumen).

## Verificación

- pytest: `panel/qc` (agrupado fail/warn/ok, flags desde CHECK_REGISTRY), `panel/qc/select`/`accept` (contrato, no_document, accept invalida caché + valida author/reason), `panel/qc/fix_all` (un undo). Reutiliza el harness fake-c4d.
- vitest: agrupado por severidad + qué acciones muestra cada check (pura), confirm gating.
- Live C4D (escena real SHOT_18): aceptar Lights con autor+razón → el numerador sube, el check pasa a contar como accepted y el denominador (`total`) no cambia (`X/11 · 1 accepted`); Fix inline de un fixable; Select selecciona en escena; Fix all; Cmd+Z revierte un fix; sin popups en todo el flujo.

## Desviaciones de implementación

Documentadas tras la implementación (Tareas 1-3), no cambian el diseño de arriba, lo precisan:

1. **REVERTIDA (2026-07-22): `panel/qc/select` vuelve a ciclar uno-a-uno, como el nativo.** La versión original de esta desviación (documentada abajo, en cursiva por historial) hacía que Select marcara TODO lo marcado del check de una vez, alegando que un op HTTP stateless no tenía dónde guardar la "posición del ciclo" entre requests. Feedback del usuario: quiere el comportamiento nativo de vuelta — un objeto por click. Fix: el cursor vive en `panel_ops._QC_SELECT_CURSOR`, un dict a nivel de módulo keyed por `check_id` (la misma clase de excepción-con-estado que `hub_ops._META_CACHE`/`panel_ops._ASSETS_BLOCK_CACHE` — un documento activo a la vez, un cursor por check es suficiente). `_advance_cursor` (pura, testeada directamente) reproduce el guard nativo `if self._idx >= len(self._bad): self._idx = 0` y además resetea a 0 si el TAMAÑO del conjunto marcado cambió desde el click anterior (objeto arreglado/añadido/borrado entre clicks). `unused_mats` cicla materiales (no objetos) igual que `_qc_select_unused_mats` nativo. La respuesta incluye `cursor_pos`/`total` para que la SPA muestre progreso ("Select 3/8"). *Nota histórica (razón de la desviación original, ya no vigente): "selecciona toda la lista de objetos marcados por el check de una vez — igual que el resto de acciones batch de esta sección (Fix, Accept). Es más simple, es coherente con 'acción directa sin estado oculto' del resto de la sección". Documentado también en el commit `ade9a29`.*
2. **La línea plegada `▸ N OK · M disabled` muestra CONTADORES, no expande a la lista de checks.** El payload de `panel/qc` no devuelve los ids/labels de los checks OK/disabled — por diseño, para no forzar una segunda pasada de agrupado ni inflar el payload con datos que el usuario rara vez necesita (un check en verde no requiere acción). La lista completa de qué checks pasan ya vive en Reports → QC Report. Si se pide en el futuro, el fix es barato: añadir `{id, label}` a las filas ok/disabled dentro de `webbridge.group_qc_by_severity` — la misma pasada de scoring ya las tiene disponibles, no hace falta re-computar nada.
3. **Tipo `PanelQcSection` en vez de `PanelQc`.** El tipo `PanelQc` ya existe en `web/src/types.ts` (línea ~804) para la tarjeta QC con top-3 fails del dashboard Overview (6.0). El payload completo de esta sección usa `PanelQcSection` (con `PanelQcCheck`, distinto de `PanelQcTopCheck`) para no colisionar de nombre ni de forma con el tipo de Overview — ambos coexisten porque sirven vistas distintas del mismo scoring subyacente.
