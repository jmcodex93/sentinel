# UDIM, segunda entrega: acciones del Hub por tesela + QC de teselas sin textura (v1.43)

**Fecha**: 2026-10-29
**Estado**: IMPLEMENTADO (v1.43.0). Aprobado por el usuario el 2026-10-29 (sustituir los tests de la negativa, #14 en WARN, Shrink copia las teselas pequeñas). Comprobado en vivo en c4dpy (C4D 2026.304, `tests/c4d_runner/run_udim_checks.py`); falta pasarlo por el panel en la GUI. Las diferencias con la propuesta están en «Cambios al implementar».
**Parte de**: v1.42.0 (`feat/matwire-udim`, spec `2026-10-29-matwire-udim-design.md`, "Fuera de alcance"). Hechos de Redshift: `docs/research/2026-10-29-redshift-udim.md`.

## Criterio de éxito

1. **Shrink** sobre una fila UDIM crea una familia de teselas nueva y reducida al lado de la original y repunta el sampler a su patrón en **un** Cmd+Z. Cada tesela de la familia original tiene su tesela en la nueva (ninguna zona sale negra).
2. **Switch resolution** cambia una fila UDIM a otra familia hermana (`_4k` ↔ `_2k`, o la base sin token que dejó Shrink) en un Cmd+Z, y **se niega por fila** si la familia destino no cubre todas las teselas actuales.
3. **Copy into project** copia todas las teselas a `<doc>/tex/` y repunta a `tex/<patrón>` en un Cmd+Z. Si alguna tesela choca con un fichero distinto, ese mapa no se repunta y el error lo nombra.
4. **Collect** entrega una escena con mapas UDIM. El manifiesto sellado registra cada patrón con sus teselas, y `verify_package` comprueba tesela a tesela. Una tesela que había en origen y falta en el paquete deja la entrada en `missing` con `missing_tiles`.
5. **QC "UDIM tiles"** (check #14, WARN): un objeto con material UDIM y polígonos cuyas UVs caen en una tesela sin textura en disco lo reporta (objeto, material, teselas). La escena LOK (cuerpo 1001–1004 y 1006–1010, grip 1005) **no** da falso positivo cuando grip está restringido a su selección.
6. Escenas sin UDIM: mismos resultados que v1.42. pytest y web verdes, oracle congelado ampliado con el check nuevo y recongelado, y los dos fixtures dan "ok" en él.
7. Las negativas `udim_unsupported` desaparecen de las cuatro acciones, porque todas tienen soporte por tesela.

## Hechos medidos (C4D 2026.304, macOS, 2026-10-29, documentos desechables)

- **`SaveProject` (Collect) ya copia las teselas.** Con un sampler RS en `…/ext_textures/rock_Emit.<UDIM>.png` (1001, 1002 y 1011 en disco), `SaveProject(ASSETS|SCENEFILE|DONTFAILONMISSINGASSETS)` lista las 3 teselas en `assets`, deja `missing` vacío, copia `tex/rock_Emit.1001.png`, `.1002` y `.1011`, y reescribe el sampler a `relative:///rock_Emit.<UDIM>.png`. El documento entregado, reabierto, resuelve el patrón como `ok`. Da igual que el documento esté insertado o no. Caso base: una ruta normal se comporta igual (1 asset, `tex/…`, `relative:///`).
- **UVs, ruta rápida:** `UVWTag.GetLowlevelDataAddressR()` devuelve un `memoryview` de bytes: 32 bytes por polígono = 4 esquinas × (u, v) en float32 (sin w). `array('f').frombytes(mv.tobytes())` lee 500 000 polígonos en 3 ms. Plegarlos a teselas por centroide en Python puro cuesta ~0,4 s (bucle indexado). `GetSlow` de 500 000 polígonos cuesta 0,17 s sin contar el bucle.
- **Fila de tesela en UV de C4D** (del doc de research: 1011 = v ∈ [−1, 0], y v ∈ [1, 2] sale negro): `col = floor(u)`, `row = floor(1 − v)`, `tesela = 1001 + col + 10·row`, válida solo con `0 ≤ col ≤ 9` y `row ≥ 0`. Fuera de ese rango Redshift no puede direccionar tesela: también es negro.

## Diseño

### `sentinel/udim.py` (puro, se amplía)

- `tile_of_uv(u, v) -> int | None`: la fórmula de arriba. `None` si cae fuera del rango direccionable.
- `tiles_of_polygons(uv_floats, poly_indices=None) -> set[int]`: recibe la secuencia plana de 8 floats por polígono (el formato medido). Usa el centroide de las 4 esquinas; un triángulo repite c en d, y el centroide sigue dentro del triángulo. Con `poly_indices` mira solo esos polígonos. Fuera de rango lo cuenta como `None`, que se reporta como "UVs fuera del rango UDIM".
- `shrunk_pattern(pattern, target_px)`: `<base>_2K<sep><UDIM><ext>`. El sufijo va **delante del token**, no detrás (`…1001_2K.png` ya no sería una tesela). Usa `assets.shrink_target_name` sobre la base, así que es idempotente y `find_res_variants` encuentra la familia y su base sin token.

### Hub: acciones por tesela (`assets.py` puro + `hub_ops.py` adaptador)

Regla común: **el servidor vuelve a derivar las teselas del disco** (`udim.list_tiles(resolved_path)`) en cada mutación, nunca las de la fila del cliente. **Todo o nada por mapa:** un patrón solo se repunta si todas sus teselas de destino quedaron escritas o verificadas. Si no, error por fila con las teselas que fallaron, y el sampler sigue en el patrón original (que sigue completo). Un `StartUndo`/`EndUndo` por gesto, como hoy.

**Shrink** (`shrink_plan` + `_run_shrink_for_job`)
- Plan: una fila UDIM es elegible si al menos una tesela supera `target_px`. Las metas se leen por tesela (`_meta_for(tile_path)`); sin la meta de alguna tesela → `no_meta`. La VRAM antes/después suma las teselas.
- Job: por cada tesela, si supera `target_px` se escala con `_save_shrunk_copy`; si no, se copia tal cual (`shutil.copy2`) al nombre nuevo, porque sin ese fichero esa zona saldría negra. El progreso es por tesela (`rock_Emit.1002.png 2/9`).
- El relink usa `replace_basename_preserving_form(path, basename(shrunk_pattern))`, así que conserva `relative:///`.
- Extensión no soportada (p. ej. `.exr`): la fila entera da `unsupported format`, igual que hoy para un fichero suelto.

**Switch resolution** (`find_res_variants` + `_op_hub_switch_res`, también `hub/variants`)
- Para una fila UDIM, el listado de la carpeta se pliega a nombres de patrón (`split_tile` + `pattern_name`) y la detección de hermanos de siempre corre sobre esos nombres. `px` sale del token; si es la base sin token, de la meta de su primera tesela.
- Cada variante lleva sus `tiles`. Si un destino no cubre las teselas actuales, se salta con `{"reason": "incomplete_tiles", "missing": [...]}` y el toast lo dice. `already_there` y `no_variant` siguen igual.

**Copy into project** (`copy_plan` + `_op_hub_copy_into_project`)
- El plan expande una fila UDIM a sus teselas: cada una con destino `<doc>/tex/<tesela>`. Las colisiones son por tesela: mismo tamaño → `reused`; tamaño distinto → error del mapa (`collision` + tesela) y no se repunta.
- El relink va a `tex/<basename del patrón>`. El recuento `copied`/`reused` es por mapa, y la respuesta añade `tiles_copied`.

**Collect** (`_op_hub_collect_start`, `flows.run_collect_pipeline`, `manifest.py`)
- Se quita la negativa. `SaveProject` ya copia y reescribe (medido).
- Antes de `SaveProject`, el pipeline anota `source_tiles = {basename del patrón en minúsculas: [teselas]}` desde el scan de la escena original.
- `manifest.classify_asset` / `build_asset_entries`: una ruta con token existe si `list_tiles` no está vacío. La entrada gana `udim: {"tiles": [...]}` (las teselas que hay en el paquete). Si `source_tiles` tiene alguna que no está en el paquete, la entrada pasa a `state: "missing"` con `missing_tiles` (una entrega con zonas negras no se da por buena).
- `verify_package` comprueba cada tesela registrada. Las teselas perdidas van a `lost` como rutas concretas (`tex/rock_Emit.1002.png`). Una entrada sin `udim` se comprueba como hoy, así que los manifiestos v1.42 siguen verificándose.
- `total_size_mb` ya suma bien (la lista `assets` de `SaveProject` trae cada tesela).

**SPA**
- Se borran `udimRefusalMessage` y la rama `udim_unsupported` de `collectStartRefusal`.
- Toasts: Shrink y Copy dicen "N maps (M tiles)" cuando hay UDIM. Switch nombra `incomplete_tiles`. El tipo `HubSwitchResponse.skipped` gana `missing?: number[]`.
- Se reconstruye y se commitea `plugin/web/`.

### QC #14 "UDIM tiles" (`checks/udim.py` + `udim_c4d.py` adaptador + `udim.py` puro)

**Registro:** `check_id="udim_tiles"`, `row_label="UDIM Tiles"`, `severity="WARN"`, sin fix, `actions=("select", "info")`, `report_key="udim_tiles"`. Se añade al tuple `STRUCTURED_CHECKS` de `run_fixtures.py` y se recongela el oracle.

**Qué es un material UDIM:** un material con al menos un registro de `scan_all_texture_paths` cuyo `current_path` tiene token. Sus teselas en disco por sampler salen de `udim.list_tiles(resolved)`. Un patrón `missing` (ninguna tesela) ya lo reporta QC Assets: aquí no se repite.

**Qué polígonos usan qué material** (`udim_c4d.polygon_materials`): por cada objeto poligonal del árbol se resuelve el material efectivo de cada polígono con las reglas de C4D:
- Las Texture Tags se aplican en orden y la última gana.
- Una tag con `TEXTURETAG_RESTRICTION` cubre solo los polígonos de la Polygon Selection con ese nombre. Una restricción a una selección que no existe no cubre nada.
- Las tags heredadas de los padres van debajo de las propias del objeto.
- Solo cuentan las tags con proyección UVW: con otra proyección las UVs del objeto no deciden la tesela.

Objetos que se leen: los `PolygonObject` del árbol (sus propias UVs; los deformadores no cambian UVs). Un generador sin hijos poligonales (primitivas) se lee de su caché (`GetCache()`, recorrida en profundidad), con las tags del generador. Un objeto sin UVW tag se salta y va a la info como `no_uvs`.

**Veredicto:** por cada (objeto, material UDIM, sampler) se calcula `teselas usadas − teselas en disco`. Si queda algo, es una violación. Se agrupa por (objeto, material): "Body · LOK_cuerpo: tiles 1005 have no texture (3 maps) — renders black". UVs fuera del rango direccionable dan una violación propia ("UVs outside the UDIM range"). Identidad: `object_identity(obj)` + `field=<nombre del material>`, que se puede aceptar en el baseline. `extras` lleva `tiles_missing` y los ficheros.

**Coste:** cada objeto se cachea por `(obj, uvw.GetDirty(DIRTYFLAGS_DATA), obj.GetDirty(DIRTYFLAGS_DATA|DIRTYFLAGS_SELECT), firma de sus tags de textura y selección)` → `{material: set(teselas)}`. Así una escena que no cambia no vuelve a recorrer UVs, aunque el check corra en cada ciclo de QC. La clave usa `==`/`hash` del wrapper, nunca `id()`; las entradas que no aparecen en una pasada se purgan. La caché de resultado (`cached_result`) es la de siempre.

**Lo que no hace (y la fila de Info lo dice):** offset/tiling de la Texture Tag y nodos de UV que transforman coordenadas dentro del grafo (se leen las UVs crudas); materiales no Redshift; mezclas por alpha entre tags apiladas.

## Errores y no-regresión

- Escenas sin token: los planes de Shrink, Copy y Switch dan lo mismo que hoy (tests actuales verdes). El check #14 da `ok` sin leer ninguna UV, porque sin material UDIM sale antes.
- Una carpeta de teselas que no se puede leer → `list_tiles == []` → la fila da `not_ok`/`unresolved`, nunca una excepción.
- Las ops siguen sin modales (`_forbid_dialog` en los tests nuevos).

## Verificación

- **pytest:** `tile_of_uv` (incluida la fila 1011 = v ∈ [−1, 0] y el rango fuera), `tiles_of_polygons` con buffers reales de 8 floats, `shrunk_pattern`, `shrink_plan`/`copy_plan`/`find_res_variants` con UDIM (y paridad sin UDIM), manifiesto (`udim.tiles`, `missing_tiles`, `verify_package` por tesela, manifiesto v1.42 sin `udim`), resolución de material por polígono con un fake que modela orden de tags, restricción, herencia y proyección. Ops de hub con `tmp_path` real: todo o nada, undo único (contando pasos en el fake) y teselas re-derivadas del disco ignorando las del cliente. Cada test nuevo, probado por mutación.
- **vitest:** toasts nuevos.
- **Oracle:** `udim_tiles` en `STRUCTURED_CHECKS`, recongelado; violating/clean → ok.
- **Live (C4D 2026.304, documentos desechables, `KillDocument` en `finally`):**
  - Shrink, Switch y Copy sobre un mapa de 3 teselas: render por teselas antes y después (colores en su sitio), y un Cmd+Z real (`CallCommand(12105)`) que devuelve la ruta.
  - Collect de la misma escena: manifiesto con teselas y `verify_package` limpio. Borrando una tesela del paquete → `lost`.
  - QC #14: plano con quads en 1001/1002/1003 sin 1003 en disco → reporta 1003. La escena LOK con grip restringido a su selección → sin violación; quitando la restricción → reporta 1005.

## Decisiones (cerradas por el usuario el 2026-10-29)

1. **Tests existentes que fijan la negativa.** `tests/test_hub_ops.py::TestHubUdimRefusals::test_shrink_copy_and_switch_refuse_udim_rows`, `::test_collect_refuses_before_qc` y en `web/src/lib/hubTable.test.ts` los dos `it` de `udimRefusalMessage` / "collect refusal for UDIM stays on the form" afirman el comportamiento de v1.42 que esta entrega retira. La regla es no tocar tests existentes. Propuesta: sustituirlos por los tests del comportamiento nuevo (mismo nombre de clase, casos invertidos), y que conste en el commit.
2. **Shrink copia tal cual las teselas que ya son pequeñas** (en vez de saltarse el mapa entero). Recomendado: sí, porque la familia reducida tiene que estar completa.
3. **Severidad del #14: WARN** (como pide la tarea). Alternativa: FAIL, porque el resultado es un render roto.

## Cambios al implementar

- **Collect:** la comparación con las teselas de origen es un paso puro aparte, `manifest.mark_lost_tiles(entries, source_tiles)`, que se aplica después del re-scan. `build_asset_entries` solo anota `udim.tiles`. Así `_rescan_collected_package` no cambia de firma, y los tests de durabilidad de Collect siguen sin tocarse.
- **QC #14:**
  - Hay **una violación por objeto**, que nombra todos sus materiales con huecos. El baseline empareja las violaciones de objeto solo por ubicación, así que dos por objeto se aceptarían juntas de todas formas.
  - No hay fila de Info propia: las limitaciones van en «Known limitations» de `CLAUDE.md`.
  - El informe JSON legado gana la sección `udim_tiles`, porque el contrato es que sus claves coincidan con las del registro.
- **Reglas de Texture Tag:** se midieron con render antes de darlas por buenas (research, sección v1.43).
- **Shrink solo planifica filas `ok`,** como con un fichero suelto: una ruta UDIM absoluta da `not_ok`.
- **Tests que fijan el tamaño del registro** (`12/13`, `13/13`, `12/12`, la lista de ids y `total = 13` del fixture, en `test_check_rs_colorspace.py`, `test_qc_registry_score.py` y `test_webbridge.py`): con 14 checks cambian sus literales, igual que cuando la v1.38 añadió el #13. Se actualizaron con la aprobación del usuario (2026-10-29), cada uno con un comentario v1.43.
