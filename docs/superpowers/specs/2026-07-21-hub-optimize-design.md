# Fase 5.2 — Asset Hub: Shrink + Copy into project

**Fecha**: 2026-07-21
**Estado**: aprobado en brainstorm
**Contexto**: segunda iteración sobre el Hub SPA (v1.17.0, fases 5/5.1 mergeadas). Cierra las dos acciones de Overseer con valor de artista que quedaron en backlog. Mecanismos estudiados de Overseer (estudiar-sí/copiar-no): shrink = copia hermana + relink con original intacto; copy-into-project = copiar a `tex/` + relink.

## Decisiones cerradas (brainstorm)

1. **UX = selección múltiple + toolbar** (no iconos por fila): filtras/facetas → seleccionas → actúas sobre el lote. Más potente que el por-fila de Overseer.
2. **Shrink por objetivo en K** (4K / 2K / 1K, lado mayor), no porcentajes: un lote heterogéneo acaba en un tamaño predecible; los ≤ objetivo se saltan.
3. Shrink corre como **job con progreso** (reutiliza `JobRegistry`/`hub/job_status`); copy-into-project es op síncrona.
4. "Accept missing" sigue descartado (equivalente = baseline QC).

## Diseño

### 1. Selección múltiple (SPA)

- `selectedKeys: Set<string>` en HubPage. Click = selección única (y sigue seleccionando el owner en escena, como hoy); cmd/ctrl+click = toggle; shift+click = rango sobre la lista **visible** (ya ordenada + filtrada + facetada). `aria-selected` por fila; contador "N selected" en la toolbar; Escape limpia.
- Relink Selected: con 1 seleccionada → picker de archivo (como hoy); con >1 → deshabilitado con hint ("Relink works on a single asset").
- Lógica pura de rango/toggle en `web/src/lib/hubTable.ts` (`applySelection(current, visibleKeys, key, {meta, shift}) -> Set`), vitest.

### 2. Shrink (job)

**Diálogo inline** (se abre desde el botón "Shrink..." de la toolbar, activo cuando la selección contiene ≥1 imagen `ok` con meta):
- Objetivo: **4K (4096) / 2K (2048) / 1K (1024)** — lado mayor.
- Resumen del lote calculado con `shrink_plan` (puro): n a reducir, n saltados (ya ≤ objetivo, sin meta, no-imagen, no-ok), dims resultantes por archivo, VRAM estimada antes → después (misma `vram_bytes`).
- Confirmar lanza el job; Cancelar cierra.

**Op `hub/shrink_start {keys, target_px}`** → `{ok, job_id}` | errores `no_document` / `job_running` / `nothing_to_shrink`. El job (mismo slot único que el collect — un job vivo a la vez) ejecuta por archivo:
1. `BaseBitmap.InitWith(original)` → escala con `ScaleIt` (aspect preservado, lado mayor = target) → `Save` como **copia hermana** `<stem>_<K>.<ext>` (p. ej. `Albedo_2K.png`), mismo formato/saver que la extensión original. Formato sin saver fiable (EXR multicapa, etc.) o cualquier fallo de lectura/escritura → **error por fila**, nunca degradación silenciosa. Target ya existente → se sobrescribe (re-run idempotente).
2. Relink de TODOS los shaders que comparten la ruta (`resolve_repath_targets` + `apply_texture_path_change`).
- **Todo el relink del lote en UN `StartUndo`/`EndUndo`**: un Cmd+Z devuelve la escena a los originales. Los archivos `_2K` quedan en disco (originales intactos — semántica Overseer).
- Progreso: `{phase: "shrink", detail: "<file> i/n", pct}` vía el `hub/job_status` existente (respondido en el hilo del servidor). Resultado del job: `{shrunk, skipped, errors: [{key, error}], bytes_saved}`.
- SPA: barra de progreso en la zona de la toolbar (mismo componente de progreso del Deliver), toast al acabar, re-fetch de inventario + meta (los nuevos tamaños/VRAM aparecen solos), stamp re-anclado.

### 3. Copy into project (op síncrona)

- Botón activo cuando la selección contiene filas `absolute` (o resueltas fuera de la carpeta del doc) y el doc está guardado.
- **Op `hub/copy_into_project {keys}`**: por archivo, `shutil.copy2` a `<docdir>/tex/` (creándola si falta) + relink en un **único** undo. Colisión de nombre en `tex/`: mismo tamaño en bytes → **reutiliza** (solo relink, cuenta como `reused`); tamaño distinto → **error por fila** (nunca sobrescribe). Respuesta `{ok, copied, reused, errors, stamp}` → toast + re-fetch.
- Doc sin guardar → `{ok: False, error: "unsaved_document"}` (el botón ya viene deshabilitado, el contrato lo impone igual).

### 4. Motor puro (pytest)

En `assets.py` (o módulo hermano si crece): 
- `shrink_plan(records, metas, target_px) -> {"shrink": [{key, path, width, height, new_width, new_height}], "skipped": [{key, reason}], "vram_before", "vram_after"}` — razones: `already_small`, `no_meta`, `not_image`, `not_ok`.
- `shrink_target_name(path, target_px) -> str` — `<stem>_<K><ext>` (`4096→"_4K"`, `2048→"_2K"`, `1024→"_1K"`); si el stem ya termina en el sufijo objetivo, no lo duplica.
- `copy_plan(records, doc_dir) -> {"copy": [...], "skip": [{key, reason}]}` — fuera-del-proyecto detectado por prefijo de ruta normalizada.
Los ops c4d son adaptadores finos en `hub_ops.py` (tests de contrato con el harness fake-c4d, como el resto).

## Manejo de errores

- Errores por fila se acumulan y se muestran (toast warn con recuento + detalle en consola); nunca abortan el lote entero salvo `no_document`.
- Job fallido a mitad: lo ya relinkeado queda dentro del mismo undo abierto → el runner cierra `EndUndo` SIEMPRE (finally) y reporta `errors`; Cmd+Z revierte lo aplicado.
- El slot único de jobs: `shrink_start` con collect (u otro shrink) en curso → `job_running`.

## Fuera de alcance

- Recompresión con control de calidad (JPEG quality, mipmaps, formatos destino distintos del original).
- Shrink de assets no-imagen y de `asset_uri`.
- Acciones por fila (hover icons) — la selección + toolbar las cubre.
- Tocar el Hub nativo.

## Verificación

- pytest: `shrink_plan` (razones de skip, VRAM antes/después, bordes en target), `shrink_target_name` (sufijos, no duplicar), `copy_plan`, contratos de ops (registro, no_document, job_running, unsaved_document).
- vitest: `applySelection` (single/meta/shift sobre lista filtrada, Escape), habilitación de botones por composición de selección.
- Live C4D (escena real): filtrar 4K → seleccionar → shrink a 2K con progreso visible; un Cmd+Z restaura originales; tamaños/VRAM refrescan solos; copy de los 3 absolute a `tex/` + colisión probada (mismo nombre, distinto tamaño → error por fila); `job_running` al solapar con un collect.
