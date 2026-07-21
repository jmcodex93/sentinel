# Pulido del Asset Hub SPA — metadatos, columnas y facetas (Fase 5.1)

**Fecha**: 2026-07-20
**Estado**: aprobado en brainstorm
**Contexto**: iteración de pulido sobre la Fase 5 (Asset Hub en SPA, rama `feat/hub-spa`), nacida del primer uso real. Referencia estudiada: página Textures de **Overseer** (`/Users/javiermelgar/Downloads/Overseer`, licencia estudiar-sí/copiar-no — mecanismos analizados, cero código copiado).

## Objetivo

La tabla del Hub pasa de listado de rutas a inspector de texturas: nombre primero, metadatos de imagen por fila (resolución, canales, bit depth, colorspace, VRAM estimada), totales globales, columnas redimensionables persistidas, sort clicable y facetas de filtrado. Sin acciones nuevas (Shrink / copy-into-project quedan en backlog como Fase 5.2 opcional).

## Qué tomamos de Overseer y qué corregimos

**Tomamos (mecanismo):** parsers de cabecera sin decodificar píxeles; VRAM = `w×h×canales×bytes_canal×1.33`; chip de resolución por buckets; facetas de resolución/canales/bit depth; totales disk+VRAM; sort default missing→más pesado.

**Corregimos (sus debilidades, verificadas en el análisis):**
- Escaneo bloqueante sin caché → nuestra meta va con **caché por (path, mtime, size)** y **enriquecimiento lazy por lotes** (patrón thumbs); el inventario nunca espera a los parsers.
- Paginación 25/página → seguimos con virtualización.
- Label del chip y su color calculados en dos sitios (se contradicen en bordes) → **una sola fuente servidor** para `{label, tier}`.
- VRAM inconsistente entre vistas → una sola función para fila y totales.
- Pillow-first (ruta pobre) → header-parsers **primero** y únicos; sin Pillow, puro stdlib.

## Diseño

### 1. Motor puro `plugin/sentinel/imagemeta.py` (nuevo, stdlib, sin c4d)

- `read_image_meta(path) -> dict | None`: `{width, height, channels, bit_depth, colorspace}`. Parsers de cabecera: PNG (IHDR + chunk sRGB/gAMA), JPEG (SOF, YCbCr), TIFF (IFD tags 256/257/258/277/262/338), EXR (dataWindow + channels + tipo de píxel → linear), HDR (linear 32b), TGA, BMP. Formato no reconocido o cabecera corrupta → `None` (jamás lanza).
- `vram_bytes(width, height, channels, bit_depth) -> int` — `w×h×ch×(depth/8)` × `MIP_FACTOR 4/3`; defaults defensivos (ch fuera de rango → 4, depth → 8).
- `res_bucket(max_px) -> {"label": "8K"|"4K"|"2K"|"<2K", "tier": "8k"|"4k"|"2k"|"sm"}` — umbrales 7168 / 3584 / 1536. Única fuente para texto Y color del chip.
- Pytest con fixtures binarios sintéticos generados en el propio test (cabeceras mínimas por formato).

### 2. Op `hub/meta` + caché (en `hub_ops.py`)

- `POST hub/meta {keys: [...]} → {metas: {key: {width, height, channels, bit_depth, colorspace, vram_bytes, vram_label, res_label, res_tier}}}`. Resuelve key→path por el memo de thumbs (`_THUMB_PATHS`); caché módulo `{(path, mtime, size): meta}`. Keys sin path o sin meta → ausentes del dict (la SPA pinta "—").
- `hub/inventory` añade `totals.vram_bytes` + `totals.vram_label` sumando la meta cacheada de archivos únicos; los no cacheados aún se completan cuando la SPA barre `hub/meta` — la página re-pide totales con un `hub/meta_totals` ligero (read-only) al terminar el primer barrido.

### 3. Op `hub/ui_state` (get/save)

- Persiste `{col_widths: {col: px}, sort: {col, dir}}` en `sentinel_settings.json` (key `hub_spa_ui`, patrón presets). Paridad con los anchos persistidos del Hub nativo v1.12.

### 4. Tabla (SPA)

- **Filas de 2 líneas, alto fijo ~44px** (virtualizador intacto): línea 1 = **basename** (primario) + chip de bucket + badge de status; línea 2 (muted) = path completo · `4096×4096 · RGB 8b · linear` · owner principal.
- Columnas: thumb | nombre/path | tipo | status | resolución | tamaño | VRAM | used-by. **Divisores arrastrables** (pointer events sobre la cabecera grid), anchos persistidos vía `hub/ui_state`, mínimos por columna, doble-click resetea.
- **Sort clicable** en cabeceras (nombre, status, resolución, tamaño, VRAM); default = missing primero, luego bytes desc (semántica Overseer). Indicador de dirección.
- **Facetas** junto a los filtros de status: Resolución (8K/4K/2K/<2K), Canales (RGB/RGBA/Grey), Bit depth (8/16/32) — client-side con contadores; se componen con búsqueda y status.
- Chips de resolución colorean por `res_tier` con tokens semánticos existentes (fail/warn/neutral/pass no — usar tints neutros/inks del design system; el acento nunca; si hace falta croma nueva, derivar tints de los tokens existentes en DESIGN.md, no inventar hex).
- La meta llega async: filas sin meta pintan "—" y se rellenan al llegar el lote (sin saltos de layout — celdas de ancho fijo).

### 5. Fuera de alcance

- Shrink / copy-into-project / bulk relink-clear-accept de Overseer (Fase 5.2 candidata, decidir tras uso).
- "Accept missing" estilo Overseer — nuestro equivalente es el baseline QC (autor+razón); no se duplica el concepto.
- Cambios en el Hub nativo (`AssetHubDialog` queda como está).
- Pillow o cualquier dependencia nueva de imagen.

## Verificación

- pytest: `imagemeta.py` (por formato, cabeceras corruptas, buckets en bordes 7168/3584/1536, vram defaults), `hub/meta` (caché por mtime, keys desconocidas), `hub/ui_state` round-trip.
- vitest: sort + composición de facetas (lógica TS no trivial).
- Build committeado + live en C4D con la escena real (39 assets): metadatos correctos contrastados contra Overseer como referencia cruzada (mismo archivo → misma resolución/canales/depth), totales coherentes, drag de columnas persistente entre aperturas, sort y facetas con contadores correctos.

## Desviaciones de implementación

- **Chip 4K usa `--color-status-warn-tint-10`, no `-15`**: el token `--color-status-warn-tint-15` no existe en DESIGN.md (solo hay `-10` para warn; `-15` sí existe para `fail`, usado en el chip 8K). En vez de inventar hex se reutilizó el tint más fuerte disponible para warn — documentado inline en el componente (`RES_CHIP_META`).
- **Sort por resolución vive como control secundario junto a la columna Name, no como columna propia** *(superado, ver ronda 2 abajo)*: el plan no le daba una columna dedicada a "Res" (la resolución vive en el chip de la línea 1 del nombre, no en una celda propia), así que el botón de orden por `res` se ancló como un pequeño control `text-caption` ("Res") pegado a la cabecera de Name en vez de encabezar su propia columna — mismo ciclo asc→desc→default que el resto, `aria-sort` propio.

## Ronda 2 (2026-07-20, feedback en vivo sobre escena real)

- **"Res" pasa a ser columna propia** (70px, entre Type y Status): el chip de resolución sale de la línea 1 del nombre; la línea 2 conserva `WxH · canales depth · colorspace`. El control secundario de la ronda 1 se retira — la cabecera "Res" ahora es un botón de sort normal como el resto (`HEADER_COLUMNS`/`RESIZABLE_COLUMNS`/`DEFAULT_COL_WIDTHS`/`gridColumnsFor` actualizados con el id `"res"`).
- **Divisores de columna**: pasan de una franja de 4px invisible-hasta-hover a una línea permanente de 1px (`--color-hairline`, `--color-hairline-strong` en hover/drag) centrada en el borde real, con un área de agarre de 8px. Tras trazar `handlePointerMove` a mano, la matemática del delta (`startWidth + (clientX - startX)`) ya era correcta (arrastrar a la derecha ensancha la columna a la izquierda del divisor); lo que faltaba era una guía visible — un agarre de 4px sin ninguna marca estática es fácil de fallar o de percibir como "invertido".
- **Tamaño "?" en missing**: `size_bytes = -1` (stat-fail) se pinta como "—" en la tabla (igual que VRAM sin meta) en vez del "?" que expone el motor.
- **Scrollbar horizontal de página**: la tabla no tenía overflow propio "roto" — el contenedor flex (`flex-1` en `HubPage`) carecía de `min-w-0`, así que el tamaño mínimo de contenido de la tabla (ancho de columnas fijas + mínimo de 160px de Name) empujaba al padre entero en vez de quedar contenido en el `overflow-auto` de la propia tabla. Fix: `min-w-0` en el contenedor de contenido — sin tocar `overflow-x` de la tabla.
