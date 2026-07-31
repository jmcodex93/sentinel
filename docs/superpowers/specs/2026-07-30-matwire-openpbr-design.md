# Matwire — OpenPBR como material por defecto (v1.34)

**Fecha**: 2026-07-30
**Estado**: implementado en rama feat/matwire-openpbr (pytest 1143, vitest 206), Live-verificado por el usuario (C4D 2026.303) y mergeado.
**Contexto**: quinta fase del arco matwire (v1.32 base → v1.32.1 pulido → v1.33 UV Context + fallback UniversalXform → **v1.34 este spec**). OpenPBR quedó explícitamente fuera de v1.32.1 y v1.33 con la nota "fase propia: otra tabla de puertos, requiere su spike". Esta fase la ejecuta.

## Hechos medidos antes de diseñar

Todo lo de abajo se leyó del nodo vivo en C4D 2026.303 (2026-07-30), no de documentación:

| Hecho | Valor |
|---|---|
| `com.redshift3d.redshift4c4d.nodes.core.openpbrmaterial` | disponible; **72 entradas** |
| Salida | `outcolor` — **la misma que Standard** |
| `emission_luminance` (default) | **0** — misma trampa que el `emission_weight` de Standard |
| `specular_isglossiness` | **AUSENTE** — el atajo de Standard no existe |
| `base_weight` / `specular_weight` | 1 (no hay que escribirlos) |
| `specular_roughness` | 0.3 |

El mapeo se cotejó además contra la implementación de TexToMatO (`Salad/Redshift/redshift_helper.py:406-445`), que resuelve exactamente los mismos puertos. Procedencia idéntica al resto del arco: **estudiar sí, copiar no** — se toman HECHOS (ids), no código.

## Decisiones cerradas

1. **OpenPBR es el default**; Standard sigue disponible por selector. Sin clave de ruleset en v1 (YAGNI explícito: `matwire_suffixes` existe porque los nombres de archivo varían por proveedor, algo que el artista no controla; el tipo de material es una decisión de estudio que se toma una vez. Si el uso pide fijarlo por proyecto, la clave se añade después con esa evidencia).
2. **Glossiness bajo OpenPBR se resuelve con `rsmathinv`** interpuesto entre el sampler y `specular_roughness`. No se degrada ese set a Standard (rompería la coherencia del lote por un detalle de formato de textura) ni se deja el mapa sin conectar.
3. **Emission**: cada tipo escribe su propio parámetro de intensidad, con valores distintos porque las unidades son distintas (`emission_weight` es un peso; `emission_luminance` es luminancia). El valor de OpenPBR se **mide**, no se hereda.
4. Fuera de alcance: coat, fuzz, subsurface, thin-film y demás canales exclusivos de OpenPBR — ningún pack PBR estándar los entrega como archivos sueltos.

## Diseño

### Tabla de puertos por BRDF (`matwire_c4d.py`)

Hoy los ids de puerto están incrustados en el dict que emite `build_description`. Se extraen a **una tabla canal→puerto por tipo**, resuelta una vez; el resto del writer es común.

| Canal | Standard | OpenPBR |
|---|---|---|
| basecolor | `base_color` | `base_color` |
| roughness | `refl_roughness` | `specular_roughness` |
| metalness | `metalness` | `base_metalness` |
| specular | `refl_color` | `specular_color` |
| opacity | `opacity_color` | `geometry_opacity` |
| bump/normal | `bump_input` | `geometry_normal` |
| emission (color) | `emission_color` | `emission_color` |
| emission (intensidad) | `emission_weight` | `emission_luminance` |

La columna Standard no es de memoria: se leyó del writer actual (`build_description`), donde esos ids están hoy incrustados. La de OpenPBR se leyó del nodo vivo y se cotejó con TexToMatO.

**No cambia nada más**: samplers, colorspaces, flip Y, splitter ORM, Color Correct, AO multiply, UV Context / UniversalXform, leftovers, layout, títulos, displacement (cuelga del nodo de salida) y el contrato de un solo Cmd+Z. Solo cambia el nodo del centro y a qué puertos entra.

Divergen exactamente dos ramas:

- **Glossiness**: Standard → puerto bool nativo; OpenPBR → `rsmathinv` interpuesto.
- **Emission**: parámetro de intensidad distinto, valor distinto.

### Disponibilidad y degradación

`openpbr_available()` con el idiom de siempre (`FindLatestAsset(...).IsNullValue()`). Si el nodo no está: el selector se deshabilita con la razón inline y el material se construye como Standard.

Se aplica la lección de v1.33: el valor **efectivo** se deriva (helper puro, espejo de `effectiveProjection`) en vez de mutar la elección del artista — un "openpbr" elegido antes de saber que el nodo falta no puede seguir viajando en el payload ni iluminando un control deshabilitado, pero la elección sobrevive si un preview posterior reporta el nodo disponible.

### Ops

`matwire_create` acepta `{"material": "openpbr"|"standard"}` (default `"openpbr"`), con la re-derivación server-side intacta: un valor desconocido normaliza al default. `matwire_preview` informa `openpbr_available: bool`.

### Preview honesto

Regla ya establecida por las filas de ORM (v1.32.1) y AO (v1.33): una fila no puede describir un cableado que el writer no va a hacer. Dos cosas nuevas que decir:

- Qué **tipo de material** se creará.
- Qué le pasa al gloss: `→ specular roughness (inverted)` bajo OpenPBR, `→ roughness (glossiness mode)` bajo Standard.

### SPA

Sub-vista: SegmentedControl **Material** (OpenPBR / Standard), junto a Projection y los checkboxes existentes.

## Spike live (bloqueante, antes del writer)

Patrón de v1.32/v1.33: se mide primero, se escribe después.

1. **`geometry_normal` — riesgo alto.** En Standard el nodo `bumpmap` entra en `bump_input`; el puerto de OpenPBR se llama *normal*, no *bump*. Si espera otra cosa, los normales saldrían mal **en silencio** (el material se ve; solo el relieve está mal). Se verifica **renderizando**, no leyendo parámetros.
2. **`emission_luminance`**: qué valor produce una emisión equivalente a la de Standard con `emission_weight = 1.0`.
3. **`rsmathinv`**: ids de puerto y que invierta de verdad.
4. **Displacement**: confirmar que sigue colgando del nodo de salida sin cambios.

## Verificación

- **pytest**: la tabla por tipo, `build_description` para ambos BRDF, la rama de glossiness (bool vs nodo invert), el parámetro de emisión por tipo, la normalización del payload y el derivado del valor efectivo.
- **Live, oráculo fuerte del invert**: un set con Glossiness bajo OpenPBR (invertido) debe renderizar **pixel-idéntico** al mismo material con un mapa de roughness que sea `1 − gloss`. Prueba el invert sin depender de criterio visual.
- **Live, por canal**: no se busca identidad con Standard (son BRDF distintos y deben verse distintos), sino que cada canal **responda** — metalness, roughness, normal con relieve visible, emission, opacity.
- **No-regresión**: `material = "standard"` produce el grafo de v1.33 sin cambios.

## Errores

- Nodo OpenPBR ausente → Standard, dicho en el preview; nunca una promesa que el writer no cumple.
- Un set legacy spec/gloss bajo OpenPBR nunca sale sin conectar ni omitido en silencio: lleva su `rsmathinv`.
