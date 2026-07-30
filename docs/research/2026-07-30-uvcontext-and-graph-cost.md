# Spike live: UV Context vs. control de transform compartido · y coste de render del grafo "artist-ready"

**Fecha**: 2026-07-30 · **C4D**: 2026.303 (live, MCP `exec_python`) · **Redshift node space**: `com.redshift3d.redshift4c4d.class.nodespace`
**Método**: documento throwaway `SENTINEL_UVCTX_SPIKE` (`InsertBaseDocument` + `SetActiveDocument`), todo construido ahí, `KillDocument` al final y reactivación del doc del usuario. Verificación de limpieza pegada al final. Ninguna medida se hizo "a ojo": las dos preguntas se resuelven con **píxeles renderizados** y con **tiempos de `time.monotonic()`**.

**Veredictos en una línea**:
- **A**: sampler `scale/offset/rotate` y `uvcontextprojection` **NO colisionan — se COMPONEN (multiplican)**. Un UniTransform compartido es seguro y sobrevive a UV Context.
- **B**: el grafo artist-ready cuesta **~5%** de tiempo de render en un test donde el shading domina (invisible a 640², medible a 1280²). No es justificación para un preset "Minimal".

---

## Escena de prueba (común a A y B)

- Cámara `CAM` en `(0,0,-800)` mirando +Z (FOV 54.43°); geometría a `z=0`.
- **A**: plano `PLANE` (`PRIM_AXIS=5`) dimensionado EXACTAMENTE al frame — `w = 2·800·tan(fov/2) = 822.857` — para que el rango U visible sea 0..1 y contar teselas sea un oráculo exacto. Material **emisivo** (`emission_color` ← sampler, `emission_weight=1`, `base_color=0`, `refl_weight=0`) → imagen = textura pura, sin iluminación de por medio.
- **B**: esfera `SPHERE` (r=380, 64 seg) + luz omni `LT` (brightness 0.8) + material PBR real (basecolor/roughness/normal) con reflexión glossy activa.
- Renderer: Redshift (`RDATA_RENDERENGINE = 1036219`, videopost RS presente), render vía `c4d.documents.RenderDocument(..., RENDERFLAGS_EXTERNAL)`.
- Textura-oráculo para A: PNG 64×64 generado con `c4d.bitmaps`, **mitad izquierda negra / mitad derecha blanca** (`/tmp/sentinel_uvctx/half.png`, verificado leyéndolo de disco: fila = 8×`0` + 8×`255`). Así, **nº de teselas en U = (transiciones a lo largo de una scanline + 1) / 2**.

---

# QUESTION A — ¿colisionan UniTransform y UV Context?

## A.1 Qué existe en este build (probe §7 del spike anterior)

```
uvcontextprojection : True
triplanar           : True
texturesampler      : True
rscolorlayer        : True
rsramp              : True
rscolorcorrection   : True
com.bogus.nope      : False      ← control negativo del probe
```

**Puertos reales** (dump del nodo vivo, no documentación):

```
texturesampler.in  : tex0_gamma, tspace_id, mirroru, mirrorv, wrapu, wrapv,
                     scale, offset, rotate, uv_context, color_offset,
                     alpha_multiplier, alpha_offset, alpha_is_luminance,
                     invalid_color, filter_enable_type, filter_bicubic,
                     prefer_sharp, mip_bias, tone_map_enable, tex0, color_multiplier
texturesampler.out : outcolor

uvcontextprojection.in  : tp_blend_amount, tp_blend_curve, tp_blend_noise, tp_noise_scale,
                          uv_tiling, uv_pivot, hex_tile_blend, hex_blend_curve, hex_blend_noise,
                          hex_noise_scale, hex_random_seed, hex_random_offset, hex_random_rotate,
                          hex_random_rotate_mode, hex_uniform_scale, hex_random_scale, hex_random_flip,
                          islefthanded, yisup, proj_space, tspace_id, coord_source, coord_object_id,
                          coord_physical_size, coord_uniform_size, coord_offset, coord_rotate,
                          camera_film_aspect, camera_pixel_aspect, tp_axis_rotate, flip_v, flip_u,
                          wrap_v, wrap_u, uv_rotate, uv_offset, uv_tiles_v, uv_tiles_u,
                          uv_uniform_tiles, coord_size_z, coord_size_y, coord_size_x, proj_type
uvcontextprojection.out : outcontext

triplanar.in  : imagex, sameimageoneachaxis, imagey, imagez, blendamount, blendcurve,
                scale, offset, rotation, projspacetype, worldspaceunit, islefthanded, yisup
triplanar.out : outcolor
```

Lecturas inmediatas:
- El sampler tiene **a la vez** `scale`/`offset`/`rotate` (el objetivo del UniTransform de TexToMatO) **y** `uv_context`. Coexisten como puertos; la pregunta es qué hace el motor con los dos.
- `triplanar` tiene entradas de **imagen** (`imagex/imagey/imagez`) → es un **nodo que SUSTITUYE al sampler**, no un modo del contexto.
- `uvcontextprojection` incorpora parámetros triplanar (`tp_*`) y hex (`hex_*`) → el triplanar TAMBIÉN vive como **modo** dentro del contexto (`proj_type`).

**Tipos de dato / trampas de escritura** (verificado):
- `texturesampler.scale`, `.offset` y `uvcontextprojection.uv_offset` son `net.maxon.parametrictype.vec<2,float64>`. **No hay `maxon.Vector2d` en el Python de 2026.303**; `SetPortValue` rechaza `tuple` y `list` (`ValueError: A Maxon Datatype should be provided`) y **acepta `maxon.Vector(x, y, 0.0)`** (read-back `X:4.0, Y:4.0, Z:0.0`, y el render lo obedece). GraphDescription también acepta `maxon.Vector` como valor; una lista `[4.0,4.0]` revienta con `TypeError: Unsupported graph description value type`.
- `uvcontextprojection.uv_tiling` es `Int64` y **su valor 1 es HEX TILING**, no "tiling normal". Descubierto renderizando: con `uv_tiling=1` la imagen salió un mosaico hexagonal aleatorio (`r_B_CTX4.png`), h=15 / v=9 transiciones. **`uv_tiling=0` + `uv_tiles_u/v`** es la tesela rectangular esperada. Un writer que ponga `uv_tiling=1` "porque suena a activar el tiling" produce hexágonos.
- `uv_uniform_tiles` es `Bool` (default `True`): con él en `True`, `uv_tiles_v` sigue a `uv_tiles_u`.

## A.2 Precedencia — el experimento

Cinco materiales, misma textura, misma escena, render 256×256, conteo de transiciones sobre la scanline `y=128` (umbral 128) y sobre la columna `x=128`:

| material | sampler `scale` | `uv_context` | transiciones H | transiciones V | teselas en U |
|---|---|---|---|---|---|
| `E_NONE` | (1,1) | — | 1 | 0 | **1** |
| `A_SCALE4` | (4,4) | — | 7 | 0 | **4** |
| `B_CTX4` | (1,1) | ctx `uv_tiles=(4,4)` | 7 | 0 | **4** |
| `C_BOTH_S4_C2` | (4,4) | ctx `uv_tiles=(2,2)` | **15** | 0 | **8** |
| `D_S4_CIDENT` | (4,4) | ctx `uv_tiles=(1,1)` | 7 | 0 | **4** |

(`ctx` = `uvcontextprojection` con `proj_type=1` (UV Channel), `uv_tiling=0`, `uv_uniform_tiles=False`. Las transiciones son impares porque el borde del frame corta media franja; `E_NONE`=1 fija la escala del oráculo, y `A_SCALE4` se verificó visualmente: 8 franjas verticales limpias.)

**Lectura**:
- `C` = 4 × 2 = **8 teselas** → **el sampler y el contexto MULTIPLICAN**. No hay override en ninguna dirección.
- `D` (contexto identidad) mantiene las 4 teselas del sampler → **conectar un `uv_context` NO anula el `scale` propio del sampler**.
- `B` demuestra que el contexto por sí solo sí controla el tiling.

**Rotación también compone**: `F_ROT45` (sampler `scale=(4,4)`, `rotate=45`, ctx identidad conectado) → h=5, v=5 y la imagen (`r3_F_ROT45.png`) son franjas **diagonales**. El `rotate` del sampler sigue vivo con el contexto enchufado.

## A.3 Triplanar

Dos cosas distintas con el mismo nombre, ambas presentes:

1. **Nodo `…nodes.core.triplanar`**: sampler-replacement (recibe las imágenes en `imagex/imagey/imagez`, tiene sus propios `scale/offset/rotation`). Existe en este build.
2. **Modo del contexto**: `uvcontextprojection.proj_type = 2` → el `texturesampler` normal se proyecta triplanar sin cambiar de nodo.

Y el modo triplanar **también compone** con el `scale` del sampler:

| material | sampler `scale` | ctx `proj_type` | transiciones H |
|---|---|---|---|
| `G_TRI_S1` | (1,1) | 2 (Tri-Planar) | 9 |
| `H_TRI_S4` | (4,4) | 2 (Tri-Planar) | 33 |

9 → 33 transiciones ≈ **×3.8** al multiplicar el scale por 4 (la desviación respecto de ×4 es el corte de media franja en los bordes del frame). Es decir: en modo triplanar el UniTransform del sampler **sigue mandando**, encima de la proyección.

## A.4 ¿Se puede compartir UN contexto entre todos los samplers?

Sí, pero **no declarativamente**. Reconfirmado el hallazgo de `docs/research/2026-07-29-matwire-spike.md` §C (GraphDescription no tiene `$ref` y duplica los scopes repetidos). La vía que funciona es la misma receta imperativa del splitter ORM: apply aislado del contexto + `Connect` en una transacción.

```python
maxon.GraphDescription.ApplyDescription(g, {
    '$type': '#' + S + 'uvcontextprojection',
    '#<' + UC + 'proj_type': 1, '#<' + UC + 'uv_tiling': 0,
    '#<' + UC + 'uv_tiles_u': 3.0, '#<' + UC + 'uv_tiles_v': 3.0})
# localizar por assetid y conectar a TODOS los samplers:
with g.BeginTransaction() as tr:
    for s in samplers:
        ctx.GetOutputs().FindChild(UC + 'outcontext').Connect(
            s.GetInputs().FindChild(TS + 'uv_context'))
    tr.Commit()
```

Read-back (material `SHARED_CTX`, 2 samplers) y en el material `ART` de la pregunta B (4 samplers):

```
n_samplers: 2   outcontext outgoing conns: 2   sampler_ctx_in: [1, 1]
ART: ctx_fanout = 4   (4 samplers, un único uvcontextprojection)
```

El `outcontext` **hace fan-out sin límite práctico**: un solo nodo de contexto para todo el material.

## Conclusión A

**No colisionan. Componen.** El `scale`/`offset`/`rotate` del `texturesampler` y la transformación del `uvcontextprojection` se **multiplican**: el contexto no pisa ni desactiva los valores del sampler (`D_S4_CIDENT` lo prueba), y el sampler no ignora el contexto (`B_CTX4` lo prueba); juntos dan el producto (`C_BOTH_S4_C2` = 4×2 = 8 teselas). Vale igual en modo triplanar (`G`/`H`: el scale del sampler sigue multiplicando sobre la proyección).

Consecuencias para el diseño:

- Un **UniTransform estilo TexToMatO** (un control que escribe `scale/offset/rotate` en cada sampler) es **seguro y future-proof**: si algún día el artista añade un UV Context a mano, su transform y el nuestro se suman en vez de pelearse. Lo que el artista pierde es sólo la *ilusión* de un único punto de verdad: acaba con dos transformaciones encadenadas, no con una rota.
- El **equivalente moderno** — un único `uvcontextprojection` compartido por el `uv_context` de todos los samplers — es igual de construible (fan-out verificado), es **un nodo en vez de N escrituras**, y regala gratis triplanar (`proj_type=2`) y hex-tiling (`uv_tiling=1`) con un solo parámetro. Su coste: no es declarativo (requiere la receta imperativa de `Connect`, ya en producción para el splitter ORM) y depende de que el nodo exista (RS 2026.2+; probar con `FindLatestAsset(...).IsNullValue()`, ya implementado).
- **Recomendación A**: construir **el contexto compartido**, no el UniTransform por-sampler. Un nodo, un sitio donde tocar, el mismo idioma que RS empuja, y encima abre triplanar/hex sin rediseñar nada. Los puertos `scale/offset/rotate` del sampler se dejan **intactos en su default** — así el artista que quiera un ajuste por-textura lo tiene libre y sabe que se multiplica encima del contexto global. Si el nodo no existiera (build antiguo), el fallback natural es el UniTransform por-sampler, que hemos verificado que no entra en conflicto con nada.

---

# QUESTION B — ¿cuesta render un grafo "artist-ready"?

## B.1 Los dos materiales

Texturas comunes (256×256 generadas con `c4d.bitmaps`): `bc.png` (color), `rough.png` (ruido), `nrm.png` (normal plana 128,128,255), `ao.png` (**blanco puro** = AO neutro).

**`MIN`** — lo que Sentinel construye hoy (6 nodos):

```
output.surface ← standardmaterial
   base_color      ← texturesampler(bc.png,   sRGB)
   refl_roughness  ← texturesampler(rough.png, RAW)
   bump_input      ← bumpmap(inputtype=1) ← texturesampler(nrm.png, RAW)
```

**`ART`** — forma TexToMatO (11 nodos), todos con valores **neutros**:

```
census: {output:1, standardmaterial:1, bumpmap:1, texturesampler:4,
         rscolorcorrection:1, rsramp:2, rscolorlayer:1, uvcontextprojection:1}

base_color     ← rscolorlayer(base ← rscolorcorrection ← sampler(bc),
                              layer1 = rsramp ← sampler(ao blanco), blend_mode = MULTIPLY)
refl_roughness ← rsramp ← sampler(rough)
bump_input     ← bumpmap ← sampler(nrm)
uv_context de los 4 samplers ← UN uvcontextprojection compartido (proj_type=1, tiles 1×1 = identidad)
```

**Descubrimiento necesario para que "neutro" fuese neutro de verdad**: `rscolorlayer.layer1_blend_mode` es un enum sin documentar aquí. Barrido de valores comparando contra `MIN` (AO blanco → multiply debe ser identidad exacta):

```
blend 0 → max 117, mean 55.6      blend 4 → max 0, mean 0.0   ← MULTIPLY
blend 1 → max  96, mean 28.0      blend 5 → max 94, mean 39.7
blend 2 → max 153, mean 71.4      blend 6 → max 129, mean 55.7
blend 3 → max  99, mean 33.9      blend 7 → max 0, mean 0.0    (probablemente Darken; también neutro con blanco)
                                  blend 8 → max 129, mean 55.7
```

**`layer1_blend_mode = 4` = Multiply.** (El primer intento usó `2` y produjo una esfera muy sobreexpuesta — el error salió a la luz precisamente por medir píxeles.)

## B.2 Equivalencia visual (paso 3 del encargo, hecho ANTES de cronometrar)

**Suelo de ruido primero**: `MIN` renderizado dos veces seguidas → **`max_diff = 0, mean_diff = 0.0`**. RS es determinista con settings idénticos, así que cualquier diferencia de píxel es señal, no ruido.

Aislando cada nodo extra por separado (render 320², 441 puntos de muestreo dentro del disco de la esfera, diff vs `MIN`):

```
T_CC        (solo rscolorcorrection en basecolor) : max 0,  mean 0.00    ← identidad EXACTA
T_LAYEROFF  (rscolorlayer con layer1 desactivado) : max 0,  mean 0.00    ← identidad EXACTA
T_LAYER     (rscolorlayer + AO blanco, blend 4)   : max 0,  mean 0.00    ← identidad EXACTA
T_RAMP      (rsramp en roughness, ramp default)   : max 47, mean 0.89    ← NO es identidad
```

`ART` completo vs `MIN` a 640×640 (1681 muestras dentro de la esfera):

```
max_diff 60 · mean_diff 0.709 · píxeles idénticos 1043/1681 (62%)
histograma de la diferencia: 0→1043, 1→518, 2→43, 3→26, 4→13, 5→8, 6→9, 7→3, … (cola hasta 60)
```

**Honestidad**: el grafo artist-ready **no es bit-exacto**. El culpable está identificado y es uno solo: **`rsramp` con su rampa por defecto no es la identidad** sobre el canal roughness (`T_RAMP` en solitario ya da mean 0.89 / max 47). Los demás nodos (`rscolorcorrection`, `rscolorlayer` con AO blanco en Multiply, el `uvcontextprojection` identidad) son **exactamente** identidad: diff 0 sobre cientos de muestras con suelo de ruido 0. La desviación resultante es pequeña (mean 0.71/255 ≈ 0.3%) y se concentra en los píxeles especulares (la cola de 60), pero **existe**: un preset artist-ready que prometa "misma imagen" debe o bien fijar la rampa a identidad explícita, o bien admitir que el ramp de roughness cambia mínimamente el specular.

## B.3 Tiempos

Mismos settings, misma escena, misma geometría; sólo cambia el material del texture tag. Cronometrado con `time.monotonic()` alrededor de `RenderDocument`. Alternando A,B,A,B… y con dos calentamientos descartados.

### 640×640 — 13 renders por material

```
MIN: 2.449 2.451 2.457 2.452 2.457 | 2.692 2.451 2.456 2.463 2.456 2.455 2.450 2.647
ART: 2.689 2.658 2.652 2.457 2.472 | 2.453 2.456 2.464 2.455 2.461 2.458 2.451 2.459

MIN  media 2.487 s   mediana 2.456 s   rango 2.449 – 2.692
ART  media 2.507 s   mediana 2.458 s   rango 2.451 – 2.689
Δ media  +0.019 s (+0.8 %)      Δ mediana +0.002 s (+0.08 %)
```

Hay outliers esporádicos de ~+0.20 s (≈ +10%) que aparecen **en los dos materiales por igual** (MIN: 2.692, 2.647 · ART: 2.689, 2.658, 2.652). **La diferencia entre materiales está muy por debajo de ese suelo de ruido**: a esta resolución, la respuesta honesta es "no se mide".

### 1280×1280 — 6 parejas balanceadas por orden

A 640² el render son 2.45 s de los que una parte grande es coste fijo. Ajustando `t = c + k·px` con las dos resoluciones (2.45 s a 640², ~7.1 s a 1280²) sale **c ≈ 0.9 s de coste fijo** y ~6.2 s de trabajo por píxel a 1280² — o sea, a 1280² el shading pesa mucho más y un efecto pequeño puede emerger. Para cancelar el orden, tres parejas se corrieron MIN→ART y tres ART→MIN:

```
pareja 1 (MIN primero): MIN 7.333  ART 7.534   Δ +0.201
pareja 2 (MIN primero): MIN 7.127  ART 7.317   Δ +0.190
pareja 3 (ART primero): ART 7.759  MIN 6.904   Δ +0.855
pareja 4 (ART primero): ART 7.529  MIN 6.888   Δ +0.641
pareja 5 (MIN primero): MIN 7.330  ART 7.751   Δ +0.421
pareja 6 (ART primero): ART 7.964  MIN 7.925   Δ +0.039

MIN  media 7.251 s   rango 6.888 – 7.925
ART  media 7.642 s   rango 7.317 – 7.964
Δ media +0.391 s = +5.4 %      6 de 6 parejas con Δ > 0  (signo consistente, p = 0.016 en test de signos)
```

Desglose por nodo a 1280² (una pareja cada uno, contra MIN medido en la misma llamada):

```
MIN 7.320 · T_CC    6.922 · MIN 7.117    → rscolorcorrection: dentro del ruido (incluso más rápido) ≈ GRATIS
MIN 7.114 · T_RAMP  7.338               → rsramp:        +0.22 s (≈ +3 %)
MIN 7.114 · T_LAYER 7.316               → rscolorlayer:  +0.20 s (≈ +3 %)
```

Los incrementos por nodo son aproximadamente aditivos y suman lo que mide `ART` completo (+0.39 s): el coste real está en el **ramp** y en el **color layer** (que arrastra un sampler AO extra); el color correct sale gratis y el contexto UV compartido no aparece como coste medible.

## Conclusión B

- **A 640×640 no hay diferencia medible**: Δ mediana +0.08 %, muy por debajo de outliers de ±10 % que aparecen en ambos materiales por igual.
- **A 1280×1280, con el shading dominando el reloj, sí hay un efecto pequeño y consistente**: **+0.39 s sobre 7.25 s = +5.4 %**, con signo positivo en las 6 parejas balanceadas. No es ruido: el suelo de ruido de imagen es 0 y el diseño balanceado por orden cancela el calentamiento.
- El coste se localiza: `rsramp` ≈ +3 %, `rscolorlayer` (+ su sampler AO) ≈ +3 %, `rscolorcorrection` ≈ 0 %, `uvcontextprojection` compartido ≈ 0 %.
- **Puesto en contexto de producción**: +5 % en un test *diseñado* para maximizar la fracción de shading (una esfera de un solo material llenando el frame, sin GI pesada, sin volúmenes, sin AO trazado, sin geometría densa, sin motion blur). En un shot real, donde el material es una de docenas y el reloj se lo comen rayos secundarios, GI y geometría, ese 5 % del shading de un material se diluye a algo que nadie va a notar. Y buena parte de él la paga un nodo (**el ramp de roughness**) que además **no es neutro**: quien lo pone es porque lo va a usar.
- **Por tanto: la premisa del preset "Minimal" no se sostiene por rendimiento.** El ahorro medible sólo aparece a resoluciones altas con el shading dominante, vale ~5 % del render de ese material, y desaparece en cualquier escena realista. Sentinel debe **enviar UNA sola forma de grafo**. Si algún día se quiere una salida más ligera, la palanca honesta no es "menos nodos utilitarios" sino "no crear el ramp de AO/roughness cuando no hay mapa que lo justifique" — que es exactamente lo que ya hace el writer al construir sólo los canales presentes.

---

# Recomendación para la fase

1. **Construir el control de transform como UN `uvcontextprojection` compartido** (`proj_type=1`, `uv_tiling=0`), conectado al `uv_context` de **todos** los samplers del material mediante la receta imperativa ya en producción (apply aislado + `Connect` en una transacción, patrón del splitter ORM). Un nodo, un punto de edición, y triplanar/hex a un parámetro de distancia.
   - Gate de existencia con el probe habitual (`FindLatestAsset(...).IsNullValue()`), porque el nodo es RS 2026.2+.
   - **Fallback si no existe**: escribir `scale/offset/rotate` por sampler (UniTransform clásico). Verificado que no colisiona con nada.
   - **No** escribir `scale/offset/rotate` del sampler cuando se use el contexto: dejarlos en su default. Se multiplican con el contexto (medido), así que dejarlos limpios mantiene un único punto de verdad y deja el ajuste por-textura libre para el artista.
   - **Trampas a respetar en el writer**: `uv_tiling=1` es **hex tiling** (usar `0`); los vec2 se escriben con `maxon.Vector(x, y, 0.0)` (`tuple`/`list` no valen y GraphDescription rechaza listas).
2. **Enviar UNA sola forma de grafo, la artist-ready.** Retirar del plan el par de presets Minimal/Artist-ready: el coste medido (~5 % sólo en el caso extremo, 0 % a resolución de trabajo) no justifica una bifurcación de producto ni el mantenimiento de dos writers.
3. **Si el grafo artist-ready se documenta como "neutro", fijar explícitamente la rampa** de `rsramp` a identidad (o aceptar y documentar que el ramp de roughness altera ligeramente el specular: mean 0.89/255, max 47/255 en solitario). `rscolorcorrection` y `rscolorlayer`+AO blanco en Multiply **sí** son identidad exacta y no necesitan nada.
4. **Anotar los enums descubiertos** en el catálogo del writer: `rscolorlayer.layer1_blend_mode = 4` es **Multiply** (7 = Darken, también neutro con blanco); `uvcontextprojection.proj_type`: 1 = UV Channel, 2 = Tri-Planar; `uv_tiling`: 0 = rectangular, 1 = hexagonal.
5. **Deuda anotada, no en esta fase**: el nodo `triplanar` como sampler-replacement existe, pero con el contexto compartido en `proj_type=2` se cubre el caso sin duplicar nodos por textura — no hay razón para construir triplanars por-textura.

---

## Limpieza de C4D (verificado)

Al terminar, `KillDocument` del throwaway y reactivación del documento del usuario:

```
docs   : ['Untitled 1']            ← sólo el documento del usuario, el spike ya no existe
active : 'Untitled 1'
mats   : ['plaster_','wall','metal','plaster','wood_B','wood_A','old','UWS GRID','GREY MAT',
          'chrome_shiny002_MAT','metal_painted_grey002_MAT','paper_cardboard_macbeth002_MAT']
objs   : ['EFFECTORS',' ','BACKGROUND','OBJECTS','SPACE',' ','CAMERAS','LIGHTS']
```

Ningún material ni objeto del spike (`MIN`, `ART`, `T_*`, `A_SCALE4`, `SPHERE`, `CAM`, `LT`, …) sobrevive en el documento del usuario. Las imágenes y texturas de evidencia quedan en `/tmp/sentinel_uvctx/` (fuera del proyecto).

**Nota de método para futuros spikes**: el transporte MCP corta la llamada a los **60 s** aunque se pase `timeout_ms` mayor (una tanda de 10 renders a 1280² se perdió así, y C4D quedó ocupado ~90 s). Trocear siempre en ops de ≤ 2 renders pesados.
