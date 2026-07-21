# Fase 5 — Asset Hub en SPA

**Fecha**: 2026-07-20
**Estado**: aprobado en brainstorm
**Contexto**: quinta fase del rediseño UI (spec madre `2026-07-18-ui-redesign-design.md`). Fases 1-4 entregadas (v1.13.0–v1.16.0): Reports, consolidación IA nativa, formularios SPA + toasts + Command Palette + cancelación de peticiones en la cola.

## Objetivo

Migrar el Asset Hub completo (`AssetHubDialog`, v1.11) a la SPA embebida: inventario con thumbnails, repathing, pre-flight QC y entrega con progreso en vivo. El diálogo nativo queda como fallback. Es la última superficie grande antes de la Fase 6 (panel completo como SPA).

## Decisiones cerradas (brainstorm)

1. **Migración completa** — no parcial. Todo el Hub en una página SPA; `AssetHubDialog` nativo se conserva como fallback ante excepción al abrir (patrón fases 2-4).
2. **Collect con progreso en vivo** — job con polling de estado (fase actual + summary inline al terminar), no síncrono ni delegado al nativo.
3. **Thumbnails lazy en la SPA** — endpoint binario nuevo en el bridge con caché; no se posponen.
4. **Compatibilidad Fase 6 explícita** — la página no sabe en qué host vive (todo entra por URL + ops HTTP); la infra nueva (jobs, thumbs, ops) vive en el motor, agnóstica del host. Lo único desechable en el rebase de Fase 6 es el host `HubDialog` (~50 líneas).

## Arquitectura y host

- **Ruta `?page=hub`** en la SPA existente (`web/src/pages/HubPage.tsx` + componentes en `web/src/components/hub/`). Mismo build, mismo design system, mismos toasts. No aparece en el sidebar de Reports (es herramienta, no informe); se abre por deep-link como los formularios.
- **`HubDialog`**: host hermano de `FormDialog`/`ReportsDialog` — mismo servidor, misma cola, mismo registro de retención anti-GC (fase 4). Tamaño grande (~1100×700), **async no modal** (Cmd+Z debe atravesar al documento).
- **Parámetro de foco por URL**: `?page=hub&focus=deliver` (equivalente al `focus="deliver"` actual).
- **Puntos de entrada migrados** (3): Tools → "Asset Hub...", botón Collect del panel (`focus=deliver`), QC #6 Assets Info. Cada uno con try/except → fallback al `AssetHubDialog` nativo.
- **Refresco**: polling ligero mientras la página está visible — op read-only `hub/state_stamp` (hash de documento activo + dirty count) cada ~2s; si cambia, la SPA re-pide el inventario. Sin PostWebMessage (eso es spike de Fase 6).
- **Job runner a nivel de módulo** (junto a `MainThreadQueue`), drenado por *cualquier* Timer de host vivo — hoy el de `HubDialog`, en Fase 6 el del panel-SPA. Nunca acoplado a un diálogo concreto.

## Inventario y tabla virtualizada

- **Op `hub/inventory`** (read-only): reutiliza el scan actual (`scan_all_texture_paths` + `GetAllAssetsNew` + merge por `canonical_asset_key`, archivo propio de la escena excluido). JSON: filas con id estable (la clave canónica), path, tipo, estado (`ok`/`missing`/`absolute`/`asset_uri`/`empty`), tamaño, used-by (procedencia). Totales agregados para la cabecera (n assets, tamaño total, n missing).
- **Tabla virtualizada** con `@tanstack/react-virtual`: solo filas visibles en el DOM (resuelve la deuda anotada del `AssetListArea` nativo, que dibuja toda la lista). Columnas: thumb, nombre, tipo, estado (badge del design system), tamaño, used-by.
- **Filtros**: All / Missing / Absolute / OK / Asset URI (paridad con los QuickTabs nativos) + **búsqueda por texto** (nueva, gratis en SPA).
- **Used-by clicable** → op de mutación `hub/select_owner` (selecciona el material/objeto dueño en la escena; patrón de mutación fase 4 con cancelación).
- **Thumbnails**: `GET /thumb/<asset_id>` — primer endpoint binario del bridge. PNG ~64px generado en main thread vía la cola (op read-only), caché en disco (dir de prefs) + LRU en memoria. La SPA lazy-carga solo filas visibles (virtualizador + `loading="lazy"`). Placeholder por tipo si falla, sin reintentos (como el nativo).

## Repathing (mutaciones)

- **Modelo de pending changes en cliente**: Find/Replace, Search Folder y relinks acumulan cambios pendientes (fila en verde, columna "→ nueva ruta"); nada toca la escena hasta **Apply All**.
- **Op `hub/apply_repath`**: recibe `[{asset_id, new_path}]` y reutiliza el writer nativo exacto (`apply_texture_path_change`, dispatch por source_type), en **un solo** `StartUndo`/`EndUndo` con el anclaje `AddUndo(UNDOTYPE_CHANGE, mat)` para node graphs. Cero lógica duplicada; un Cmd+Z revierte el lote. Devuelve resumen (n cambiadas, errores por ruta) → toast + re-fetch del inventario.
- **Find/Replace**: computado en la SPA — case-insensitive por defecto + toggle Match case; misma semántica que el `re.sub` con lambda del nativo (los backslash de Windows sobreviven), replicada en TS con **test espejo** de paridad.
- **Presets last-5**: ops `hub/presets` get/save contra `sentinel_settings.json` (mismo key actual).
- **Search Folder for Missing / Relink selected**: picker nativo vía op `hub/pick_path` (`c4d.storage.LoadDialog` en main thread; bloquea la cola mientras el modal está abierto — aceptable con un solo usuario, y la cancelación de fase 4 cubre al cliente si abandona). El matching reutiliza `build_file_index`/`match_missing_in_folder` de `assets.py` (ambiguity-safe: nunca auto-elige).
- **Make All Relative / Clear pending**: paridad con el nativo; Clear es puro cliente.

## Pre-flight QC + Entrega (jobs)

- **Franja pre-flight**: op read-only `hub/preflight` reutilizando los helpers compartidos del QC Report (fase 2): score, filas con severidad, `N new (M accepted)`. Fix/Accept reutilizan las ops existentes del palette/gate (fase 4) donde las haya; Details deep-linkea a `?page=qc`.
- **Gate**: si `gates_enabled` y hay FAILs, el botón Deliver muestra el triage **inline en la página** (componentes de `GateTriagePage` reutilizados) antes de lanzar el job. No el modal nativo — este flujo es async, no aplica la excepción de fase 4 (que cubría el Save/Collect síncrono nativo).
- **Job de collect**: `hub/collect_start {output_dir, zip, ...}` → `{job_id}`. El runner ejecuta `run_collect_pipeline` troceado por fases usando su callback de estado existente (save → re-scan → manifest → zip), un paso por tick del Timer donde sea divisible, publicando `{phase, detail, pct}`. `hub/job_status {job_id}` es read-only (polling desde la SPA).
- **Al terminar**: la página pinta el **delivery summary inline** (componentes de `DeliverySummaryPage` con el manifest recién sellado).
- **Missing-gate**: aviso y permitir continuar (decisión v1.11 intacta — el manifest los sella igual).
- **Concurrencia**: un solo job vivo; `collect_start` con job en curso → error claro.

## Manejo de errores

- Cualquier excepción al abrir la página → fallback al `AssetHubDialog` nativo (patrón fases 2-4).
- Errores de op → JSON `{error}` + toast; el Timer nunca lanza (invariante del bridge intacta).
- Job fallido → estado `error` con detalle consultable por `job_status`; la página lo muestra y permite reintentar.
- Thumbnail fallido → placeholder por tipo, sin reintentos.

## Fuera de alcance

- PostWebMessage / push en vivo (spike de Fase 6).
- Migrar el panel principal (Fase 6).
- Tocar los motores (`assets.py`, `manifest.py`, `run_collect_pipeline` salvo el troceo por callback ya previsto, writers de repathing).
- Retirar `AssetHubDialog` (se conserva como fallback al menos una versión).

## Testing

- **pytest**: ops nuevas (inventory / apply_repath / presets / preflight / pick_path stub / job lifecycle) con la cola stubbed; job runner puro (transiciones de fase, error a mitad, cancelación, un-solo-job); payload mappers campo a campo contra `assets.py`; endpoint `/thumb` (rutas, caché, 404).
- **Vitest**: test espejo del Find/Replace TS (paridad con Python en backslashes y case).
- **Build**: reproducible (`npm ci && npm run build` → estáticos committeados) + Playwright de la página con payload fixture.
- **Live C4D** (escena real de producción, 39 assets): inventario paridad 1:1 con el Hub nativo; repath + un solo Cmd+Z; collect real con progreso visible y summary inline; fallback nativo forzado; eyeball del usuario.

## Desviaciones de implementación

Registradas al cierre de Fase 5 (Task 13), frente al spec original arriba:

- **`FormDialog` reutilizado en vez de una clase `HubDialog` nueva**: el spec asumía un host propio; en la práctica `FormDialog` ya cubre exactamente lo que el Hub necesita (mismo servidor/cola, tamaño por página, `query` string) — añadirle un `focus` param al `query` existente costó menos y evita un tercer host GeDialog que mantener en paralelo a Reports/Forms. Ningún comportamiento del spec cambia; solo el vehículo.
- **Vitest en vez de Playwright**: el spec pedía "Playwright de la página con payload fixture" para probar `HubPage`. Se implementó el test de paridad Find/Replace (TS vs Python) en Vitest, que es lo que realmente necesitaba cobertura automatizada (la lógica pura de reemplazo, no el render). Un E2E de Playwright contra la página completa quedó fuera de esta tarea — la verificación de render/interacción real se hace en el live-MCP de Task 14, no en CI.
- **Ops `hub/make_relative` y `hub/match_folder` añadidas**: el spec las implicaba ("Make All Relative: paridad con el nativo"; "Search Folder... reutiliza `build_file_index`/`match_missing_in_folder`") pero no las nombraba como ops explícitas del contrato servidor. Se crearon como ops de primera clase (mismo patrón que `hub/apply_repath`) porque ambas mutan/resuelven server-side contra el motor nativo — no tenía sentido replicarlas en el cliente.
- **Re-anclaje de `hub/state_stamp` desde stamps de mutación**: cada op de mutación (`apply_repath`, `make_relative`, `match_folder`, `collect_start`, gate ack) devuelve el stamp resultante junto con su respuesta; el cliente adopta ese stamp como el "conocido" antes de seguir el polling normal de `state_stamp`. Sin esto, una mutación local podía verse "revertida" un tick por un snapshot del servidor tomado justo antes de que la mutación aplicara — el mismo problema que `_suppress_ticks` resuelve en el panel nativo (donde una escritura local se protege de que el próximo tick del `Timer` la pise con el estado viejo leído de disco). El re-anclaje es el equivalente stateless: en vez de suprimir ticks, el cliente avanza su noción de "última versión vista" al confirmar la mutación.
