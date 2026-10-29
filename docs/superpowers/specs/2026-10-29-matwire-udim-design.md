# Matwire UDIM + export de Painter (OpenPBR, Coat) (v1.42)

**Fecha**: 2026-10-29
**Estado**: LIVE-VERIFIED (C4D 2026.304) — pytest 1962, vitest 272.
**Contexto**: proyecto LOK. Painter exporta los materiales en UDIM con nombres OpenPBR y sufijo de colorspace OCIO, y Matwire no reconoce **ningún** set de esa carpeta (0 de 100 ficheros). Mediciones: `docs/research/2026-10-29-redshift-udim.md` (C4D 2026.304, render real por teselas).

## Criterio de éxito

1. La carpeta real de LOK (`…/LOK-003 MAX HYPE (Attack)/cages/produccion/v4/texturizado/EXPORT_PAINTER`) da **dos sets**: `LOK_cuerpo` (9 teselas: 1001–1004, 1006–1010) y `LOK_grip` (1 tesela: 1005). Cada uno tiene basecolor, metalness, roughness, normal (GL), height, coat_color, coat_weight, coat_roughness y coat_normal. El `Normal` genérico queda en ignorados porque GL gana.
2. "Create" construye los dos materiales RS en un Cmd+Z. Los samplers apuntan a `…_<UDIM>.png`, el Coat está cableado, y un render muestra cada tesela en su sitio (repetir la prueba de colores del doc de research con el writer real).
3. Con las rutas pasadas a relativas, QC Assets **no** da `missing` para esos mapas. Una ruta UDIM sin ninguna tesela en disco **sí** da `missing`.
4. El Asset Hub muestra una fila por mapa UDIM (no una por tesela). Shrink, el cambio de resolución, copiar al proyecto y Collect se niegan con un texto visible ante un mapa UDIM.
5. Una carpeta sin UDIM ni nombres de Painter da exactamente el mismo resultado que en v1.41: pytest actual verde y oracle congelado sin cambios.

## Decisiones cerradas (usuario, 2026-10-29)

1. **Alcance: Matwire + resolver.** Matwire construye materiales UDIM/UVTILE, y el resolver de rutas (QC Assets + estado del Hub) entiende los tokens. Las acciones del Hub que trabajan fichero a fichero quedan para la siguiente entrega, pero se niegan de forma visible, nunca en silencio.
2. **Origen de LOK: Substance Painter**, preset OpenPBR. Patrón `<mesh>_<set>_<canal>_<colorspace OCIO>_<tesela>.png`.
3. **Coat: cableado** en los dos BRDF, con los IDs medidos en vivo.

## Hechos medidos que el diseño usa

- Redshift resuelve `<UDIM>` y `<UVTILE>` en `tex0/path`, en mayúscula o minúscula. El sampler no tiene ningún puerto de modo de teselas.
- `<UVTILE>` sustituye también al `_` que lo precede: `rock<UVTILE>.png` carga `rock_u1_v1.png`.
- Una tesela que falta en disco se renderiza **negra, sin aviso**.
- El UV Context Projection de Matwire no estorba: las teselas se resuelven a través de él.
- `GetAllAssetsNew` lista cada tesela existente como un asset propio. Nuestro scan lista el patrón.
- Coat: `coat_weight`, `coat_color` y `coat_roughness` existen en los dos BRDF. La normal es `geometry_coat_normal` en OpenPBR y `coat_bump_input` en Standard. `coat_weight` nace a 0.

## Diseño

### `sentinel/udim.py` (nuevo, puro)

La única fuente del conocimiento sobre teselas, compartida por el motor de Matwire, el resolver, el Hub y el check de colorspace.

- `split_tile(stem) -> (base, tile, scheme, sep) | None`. Detecta una tesela **al final** del stem:
  - UDIM: `[._](1\d{3})$`, con el número entre 1001 y 1999. `sep` es el separador encontrado (`.` en Mari, `_` en Painter).
  - UVTILE: `_u(\d+)_v(\d+)$` (sin distinguir mayúsculas). El número se guarda convertido a UDIM (`u1_v1` → 1001, `u2_v1` → 1002, `u1_v2` → 1011) para mostrarlo igual; `scheme` dice cuál era.
- `pattern_name(base, scheme, sep, ext)`: `base + sep + "<UDIM>" + ext`, o `base + "<UVTILE>" + ext` (el token absorbe el `_`, como se midió).
- `has_token(path)`: la ruta contiene `<UDIM>` o `<UVTILE>`, sin distinguir mayúsculas.
- `strip_token(stem)`: quita el token y su separador, para inferir el canal a partir de un nombre con token.
- `tile_regex(pattern_path)`: regex que reconoce los ficheros de teselas de un patrón.
- `list_tiles(pattern_path, listdir=os.listdir) -> [int]`: las teselas que existen en disco, ordenadas. Si la carpeta no se puede leer, devuelve `[]` sin lanzar error.
- `format_tiles([int]) -> "1001–1004, 1006–1010"`: texto con rangos compactados, para la vista previa y el Hub.

Riesgo aceptado: una secuencia de imágenes numerada desde 1001 dentro de la carpeta de texturas se tomaría por UDIM. La vista previa lo deja a la vista ("UDIM · N teselas").

### Motor `matwire.py`

El orden del pipeline del stem es el contrato (y se comparte con `matgraph._name_channel`):

1. `udim.split_tile` sobre el stem en bruto. Si hay tesela, el fichero entra como miembro de su patrón.
2. Se quita el **sufijo de colorspace OCIO**, antes de `_normalize`, porque estos nombres llevan espacios, puntos y paréntesis. Es una lista cerrada, sin distinguir mayúsculas y precedida de `_`: `Raw`, `Utility - Raw`, `sRGB Encoded Rec.709 (sRGB)`, `sRGB - Texture`, `Utility - sRGB - Texture`, `Linear Rec.709 (sRGB)`, `Utility - Linear - sRGB`, `ACEScg`, `ACES - ACEScg`, `ACES2065-1`. **Solo sirve para reconocer el canal**: el colorspace del sampler lo sigue decidiendo `channel_colorspace` (convención del estudio).
3. `_normalize`, después `_strip_trailing_res` y `_match_channel`, como hasta ahora.

Agrupación de teselas: los ficheros con la misma `(carpeta relativa, base, scheme, sep, extensión en minúsculas)` forman **una** entrada de canal. Su valor en `channels` es la **ruta relativa del patrón** (`…_<UDIM>.png`), con lo que el writer no cambia de forma. La lista de teselas del canal va en `tex_set["tiles"][channel] = [1001, …]`. Un set solo con 1005 también es un patrón. Ante un empate de resolución entre un canal con teselas y otro sin ellas, gana el que tiene teselas, y el otro va a `duplicate_channel`. Los tokens de resolución siguen funcionando sobre la base (`rock_BaseColor_4k.1001.png`).

Tablas de canales, ampliadas siempre de forma aditiva:

- `normal_gl`: añade `normal_opengl`.
- `normal_dx`: añade `normal_directx`.
- `metalness`: añade `base_metalness`.
- `roughness`: añade `specular_roughness`.
- Canales nuevos, colocados **antes** de roughness, normal y basecolor para que `Coat_roughness` no se lo quede `roughness`:
  - `coat_weight`: `coat_weight`, `clearcoat_weight`.
  - `coat_color`: `coat_color`, `clearcoat_color`.
  - `coat_roughness`: `coat_roughness`, `clearcoat_roughness`.
  - `coat_normal`: `coat_normal`, `clearcoat_normal`.

  `coat_color` es sRGB y los otros tres son raw. `CANONICAL_CHANNELS` los incluye, así que también se pueden ampliar vía `matwire_suffixes`.

Hay que fijarlo con un test: la raíz perezosa (`.*?`) junto con las variantes compuestas tiene que dar la raíz `LOK_cuerpo` para `Base_metalness` y `Specular_roughness`, no `LOK_cuerpo_Base` ni `LOK_cuerpo_Specular`.

Reglas puras nuevas, con la misma disciplina de "fuente única" que `ao_destination`:

- `coat_weight_source(channels) -> "map" | "constant" | None`. Hay mapa de weight → `"map"`. Hay mapas de coat sin weight → `"constant"`, y el writer escribe `coat_weight = 1.0` (mismo precedente que la emisión: nunca entregar invisible). Sin coat → `None`.
- `tile_mismatch(tex_set) -> {canal: [teselas que faltan]}`: las teselas que tienen otros canales del set pero este no. La vista previa lo muestra como aviso, porque esas zonas saldrían negras. No bloquea.

`preview_payload` añade a cada fila de canal `tiles` (lista) y `tiles_label` (`format_tiles`). Al set le añade `tile_mismatch`, y a la fila `coat_weight` le añade `source`.

### Writer `matwire_c4d.py`

- `BRDF_PORTS` gana `coat_weight`, `coat_color` y `coat_roughness` en los dos BRDF, más `coat_bump` (`geometry_coat_normal` en OpenPBR, `coat_bump_input` en Standard).
- La normal del coat va por su propio `bumpmap` (`inputtype = 1`, `flipy` = el `normal_flipy` del set) hacia `coat_bump`.
- Con `coat_weight_source == "constant"` se escribe `coat_weight = 1.0`.
- Las rutas de los samplers son el patrón. `_join` no cambia, porque el token es un carácter más de un nombre.
- Títulos: `Coat Weight`, `Coat Color`, `Coat Roughness` y `Coat Normal`. Los dos bumpmap se titulan `Bump` (el título va por tipo de nodo; el sampler `Coat Normal` ya dice cuál es cuál); el layout por columna los apila sin chocar.
- El puerto de normal del coat va en una tabla aparte (`BRDF_COAT_BUMP`), no en `BRDF_PORTS`: igual que `bump`, es la entrada propia del BRDF que ningún sampler alimenta directamente, y así la tabla inversa de `matgraph` sigue exacta.
- La altura en UDIM: las ops prueban la cabecera (`imagemeta`) y las estadísticas (`height_float_stats`) sobre la **primera tesela**, no sobre el patrón.

### Ops `panel_tools_ops.py`

`_matwire_request` resuelve la primera tesela de la altura para las sondas de float. El resto no cambia: el scan se vuelve a derivar del disco en cada llamada, y `create` vuelve a escanear antes de crear.

### Check de colorspace (`matgraph.py`, QC #13)

`_name_channel` aplica `udim.strip_token` y la eliminación del sufijo OCIO antes del pipeline de siempre, así que los nombres de LOK vuelven a dar la señal por nombre. `PORT_TO_CHANNEL` gana `coat_color`, `coat_weight` y `coat_roughness`. La normal del coat ya entra por `bumpmap.input` → `normal`.

### Resolver `textures.py`

`_resolve_relative_texture` y `_classify_texture_path`: si `udim.has_token(path)`, una candidata cuenta como encontrada cuando `udim.list_tiles(candidata)` no está vacía, en lugar de `os.path.isfile`. Se buscan las mismas carpetas y en el mismo orden. Las rutas absolutas siguen como están (`absolute`, sin comprobar existencia, igual que hoy).

### Asset Hub (`assets.py`, `hub_ops.py`, SPA)

- `merge_inventories`: un registro genérico (de `GetAllAssetsNew`) que encaja con el `tile_regex` de un registro de textura con token **se pliega** en esa fila: añade su owner y cuenta como tesela, en lugar de crear una fila propia. La fila lleva `udim: {"tiles": [...]}`.
- La fila del Hub muestra `UDIM · N` junto al nombre.
- Shrink, cambio de resolución y copiar al proyecto **se niegan** si la selección incluye filas UDIM (`udim_unsupported` + `udim_files`), y el toast las nombra para que el artista las deseleccione. (Esas acciones no devuelven hoy la lista de filas saltadas, así que "saltar en silencio" no se vería.) Match folder no necesita nada: un patrón con token nunca coincide con un nombre de fichero del índice. El repath manual (editar la cadena) y Make relative sí funcionan, porque solo tratan con texto.
- **Collect** se niega antes de copiar nada si hay algún mapa UDIM, nombrándolos ("Collect doesn't support UDIM textures yet: …"). Nunca entrega una escena sellada con texturas rotas.

### SPA (`MatwireSubview.tsx`, `panelMatwire.ts`, Hub)

- Fila de canal: "UDIM · 9 tiles (1001–1004, 1006–1010)".
- Aviso de set con `tile_mismatch`.
- Fila `coat_weight`: "weight 1.0 (no map)" cuando es una constante.
- Hay que reconstruir el bundle y commitear `plugin/web/` (CI comprueba que coincide con el código fuente).

## Errores y no-regresión

- Una carpeta sin teselas ni sufijos OCIO produce el mismo scan que v1.41: los tests actuales de matwire siguen verdes sin tocarlos.
- Una carpeta de teselas que no se puede leer da `list_tiles` → `[]` → `missing`, nunca una excepción.
- Una tesela que falta en disco no es un error de Matwire (puede ser legítimo, como el 1005 de `cuerpo`). Solo la diferencia **entre canales del mismo set** genera aviso.
- Un Cmd+Z por lote, como hasta ahora.

## Verificación

- **pytest:**
  - `udim.py`: split, patrón, tokens en mayúscula y minúscula, `list_tiles` con un `listdir` falso, `format_tiles`.
  - Motor: los 100 nombres reales de LOK como fixture (criterio 1), Mari `.1001.exr`, UVTILE, un set de una sola tesela, la raíz de `Base_metalness`/`Specular_roughness`, `coat_weight_source`, `tile_mismatch`, el desempate con y sin teselas, el token de resolución con tesela, y paridad con carpetas sin UDIM.
  - Writer: la descripción con coat para los dos BRDF y el patrón en la ruta.
  - Resolver: relativo con teselas → ok; sin teselas → missing.
  - Hub: el plegado en `merge_inventories`, las razones `udim_unsupported` y la negativa de Collect.
  - `matgraph`: canal por nombre con token.
- **vitest:** las etiquetas de teselas y del aviso.
- **Oracle congelado:** `run_fixtures.py` sin cambios.
- **Live (C4D 2026.304, documento desechable):**
  - La carpeta real de LOK → 2 materiales, revisión del grafo y Cmd+Z.
  - La prueba de colores por teselas con el writer real.
  - Rutas relativas → QC Assets sin missing.
  - El Hub con una fila por mapa, y Collect negándose con el texto.

## Fuera de alcance

- Collect, Shrink, cambio de resolución y match folder por tesela (la siguiente entrega: el manifiesto debería registrar el patrón y sus teselas).
- Un check de QC que avise cuando el mesh usa teselas que no tienen textura: hay que leer las UVs de los objetos que llevan el material. Es exactamente el negro silencioso que se midió.
- Respetar el colorspace que declara el sufijo OCIO cuando contradice la convención.
- La anisotropía del coat, su IOR y otros lóbulos de OpenPBR (sheen, transmission, subsurface).
- Asignar materiales automáticamente a una selección.
