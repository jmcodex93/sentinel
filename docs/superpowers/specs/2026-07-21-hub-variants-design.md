# Fase 5.3 — Asset Hub: conmutador de variantes de resolución

**Fecha**: 2026-07-21
**Estado**: aprobado en brainstorm
**Contexto**: tercera iteración sobre el Hub SPA (rama `feat/hub-optimize`, tras 5.2 Shrink/Copy). Nace del uso real: texturas que existen en varias resoluciones en disco (packs comerciales `plaster_4k_1.jpg`/`plaster_8k_1.jpg` y los proxies `_2K` que genera nuestro Shrink) deben poder conmutarse alta ↔ proxy sin repathing manual.

## Decisiones cerradas (brainstorm)

1. **Detección = sufijo propio + tokens comunes**: el convenio del Shrink (`_1K/_2K/_4K/_8K` antes de la extensión) Y tokens genéricos `1k/2k/4k/8k/16k` (case-insensitive) delimitados por `_`, `-` o `.` en cualquier posición del nombre. Hermanos en el MISMO directorio con el resto del nombre idéntico. Nunca tokens dentro de palabra.
2. **UX = selección + "Switch res..."** (patrón 5.2): seleccionar filas → diálogo con objetivos disponibles + contadores → relink del lote en un undo. "Todo a proxy" = seleccionar todo + 2K.
3. Switch es **relink puro** (no escribe archivos) → op síncrona, no job.

## Diseño

### 1. Motor puro (`assets.py`)

- `split_res_token(basename) -> (prefix, px, suffix) | None` — reconoce el token de resolución y lo separa. Mapa px: `1k→1024, 2k→2048, 4k→4096, 8k→8192, 16k→16384`. Delimitadores: inicio/fin de nombre, `_`, `-`, `.` (la extensión cuenta como delimitador final). El sufijo propio `_2K` es un caso particular del token genérico. Si hay varios tokens en el nombre, se usa el ÚLTIMO (el más cercano a la extensión — `4k_scan_2k.png` conmuta el `2k`).
- `find_res_variants(records, list_dir) -> {key: [{"path": str, "px": int}]}` — para cada record con `resolved_path` y token reconocible: lista el directorio (una vez por dir, cacheado en la llamada; `list_dir` inyectable = `os.listdir` en producción), busca hermanos cuyo `split_res_token` dé el mismo `(prefix, suffix)` case-insensitive. Solo devuelve keys con ≥2 variantes (incluida la propia). Orden por px desc.

### 2. Ops (`hub_ops.py`)

- `hub/variants {keys}` (read-only, lotes ≤64 como `hub/meta`): resuelve key→path por `_THUMB_PATHS`, aplica `find_res_variants` → `{"variants": {key: [{"basename", "px"}]}}`. Keys sin variantes ausentes del dict.
- `hub/switch_res {keys, target}` (mutación síncrona): `target` = int px o `"highest"`. Por key seleccionada: elegir la variante con px == target (highest = mayor px disponible); si la actual ya es esa → skip `already_there`; sin variante para ese target → skip `no_variant`; relink con **`replace_basename_preserving_form(stored_path, variante_basename)`** (la forma relativa/absoluta/maxon-url del original se conserva — lección del fix de 5.2). Todo el lote en un `StartUndo`/`EndUndo` (finally) + `EventAdd`; writer failures settle vía `_settle_relink_results`. Respuesta `{ok, switched, skipped: [{key, reason}], errors, stamp}`.

### 3. SPA

- **Fetch**: `fetchHubVariants(keys)` batched tras el barrido de meta (mismo pipeline secuencial); estado `variants: Record<key, {basename, px}[]>`.
- **Indicador**: filas con variantes muestran `⇄` junto al chip Res (title: "N resolutions on disk").
- **Toolbar "Switch res..."**: activo cuando la selección tiene ≥1 fila con variantes. Diálogo (patrón HubShrinkDialog): lista de objetivos = unión de px disponibles en la selección + "Highest", cada uno con contador "X/N disponibles" (cómputo puro `switchTargets(selection, variants)` en `hubTable.ts`, vitest); confirmar → `postHubSwitchRes` → toast `{switched, skipped, errors}` + re-fetch + re-anclaje de stamp + selección limpia.
- Un Cmd+Z revierte el lote (relink puro).

## Manejo de errores

- Sin doc → `no_document`; keys desconocidas → skip por fila; errores de writer → `writer failed` por fila (patrón settle). Nunca aborta el lote.
- El barrido de variantes nunca bloquea: `find_res_variants` es I/O de listdir cacheado por directorio; keys sin resolved_path se omiten.

## Fuera de alcance

- Generar variantes que no existen (eso es Shrink).
- Detección cross-directorio o por metadata de contenido.
- Persistir un "modo proxy" del proyecto (estado global) — el conmutador es por acción, sin estado.
- Tocar el Hub nativo.

## Desviaciones de implementación

- **Barrido de variantes en paralelo, no encadenado tras el de meta**: la spec (§3, "Fetch") describía `fetchHubVariants` como parte del "mismo pipeline secuencial" del barrido de meta. La implementación lo corre como su propio efecto React, en paralelo al barrido de meta existente, en vez de esperar a que este termine. Sin impacto observable — ambos barridos leen el mismo inventario ya cargado y son independientes entre sí; correrlos en paralelo solo acelera el primer render de los indicadores `⇄`.
- **Cap de lote 64 también en `hub/switch_res`**: la spec solo mencionaba explícitamente el cap ≤64 para `hub/variants` (§2, "lotes ≤64 como `hub/meta`"). La implementación aplica el mismo `_META_BATCH_CAP` a `hub/switch_res`, coherente con el resto de ops de mutación en lote del Hub (mismo patrón que `hub/apply_repath`).
- **Keys desconocidas en `hub/switch_res` → skip `no_variant`**: no estaba explícito en la spec qué pasa si `switch_res` recibe una key que no resuelve a ningún record de la escena (por ejemplo, un doble-click enviado tras un rescan que hizo desaparecer el asset). La implementación la trata igual que "sin grupo de variantes" y la reporta como skip `no_variant`, nunca como error — consistente con el resto de la ruta, que nunca aborta el lote por una fila individual.

## Verificación

- pytest: `split_res_token` (fronteras `_`/`-`/`.`, inicio/fin, case, token dentro de palabra → None, múltiples tokens → último), `find_res_variants` (mismo prefix+suffix, no cruzar familias, dir cacheado, list_dir inyectable), contratos de ops (registro, no_document, already_there/no_variant, highest).
- vitest: `switchTargets` (unión de objetivos + contadores, highest).
- Live C4D (escena real): las `_4k_1.jpg` con hermanas `_8k_1.jpg` y los proxies `_2K` del Shrink; bajar selección a 2K, volver a Highest, Cmd+Z, formas de ruta conservadas.
