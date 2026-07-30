# Matwire — UV Context compartido, Color Correct y AO opcional (v1.33)

**Fecha**: 2026-07-30
**Estado**: implementado en rama `feat/matwire-uvcontext` (pytest 1110, vitest 201), pendiente de verificación live. Decisiones del brainstorm: solo *Projection* expuesto en la sub-vista; Color Correct siempre; AO como checkbox de la sub-vista; un solo grafo, sin presets.
**Contexto**: cuarta fase del arco matwire (v1.32 base → v1.32.1 pulido → **v1.33 este spec**). Nace de comparar el grafo de TexToMatO con el nuestro y de un **spike live que midió las dos preguntas abiertas** (`docs/research/2026-07-30-uvcontext-and-graph-cost.md`):

1. **Un control de transform compartido NO choca con el UV Context de Redshift** — se multiplican (medido: sampler 4× + contexto 2× = 8 teselas). Pero el camino correcto no es el "UniTransform" de TexToMatO (un grupo con N×3 cables), sino **UN `uvcontextprojection` compartido** por el `uv_context` de todos los samplers: un nodo, un punto de edición, y triplanar como parámetro.
2. **El par de presets Minimal/Artist-ready no se sostiene**: a resolución de trabajo la diferencia está en el ruido; a 1280² el grafo completo cuesta **+5,4 %**, y el desglose manda el diseño — UV Context ≈0 %, Color Correct ≈0 %, `rsramp` +3 %, `rscolorlayer` (AO) +3 %. Es decir: **lo que no cuesta es justo lo que debe ir siempre, y lo que cuesta es justo lo que no debe ir por defecto**.

Corrección registrada en el mismo spike (objeción del usuario, verificada): el `rsramp` por defecto no es identidad porque sus knots vienen con `interpolation = 'smoothknot'`, no porque un ramp lo sea intrínsecamente. Un ramp *puede* ser identidad exacta escribiendo `linear` explícito — mismo principio "nunca dependas de los defaults del nodo" que ya rige colorspaces y `flipy`. Aun así los ramps quedan fuera **por su coste**, no por alterar.

## Decisiones cerradas

1. **Un solo grafo** — se retira del roadmap la bifurcación Minimal/Artist-ready.
2. **`uvcontextprojection` compartido**: creado siempre (si el nodo existe), en identidad, con su `outcontext` conectado al `uv_context` de **todos** los samplers del material — incluidos el del ORM y los leftovers, para que el tiling cubra el material entero.
3. **Único control expuesto antes de crear: Projection** (UV Channel = `proj_type` 1, por defecto · Tri-Planar = `proj_type` 2). El tiling/rotación se ajusta después en el AM del nodo, viendo el render — que es donde tiene sentido.
4. **Color Correct siempre** (`rscolorcorrection` entre el sampler de basecolor y `base_color`), en identidad: coste ≈0 y es donde el artista acaba tocando.
5. **AO multiplicado = checkbox de la sub-vista** (off por defecto). Encendido, el AO va a `base_color` vía `rscolorlayer` en Multiply; apagado, sigue como sampler suelto (comportamiento v1.32).
6. **Nodos renombrados** semánticamente en todos los casos.
7. **El nodo `triplanar` clásico NO se usa**: verificado por introspección que es un *sampler-replacement* (13 entradas, con `imagex/imagey/imagez` y salida `outcolor`), mientras el contexto es un *generador de coordenadas* (43 entradas, salida `outcontext`). Para una textura por canal — el 99 % de matwire — el contexto compartido es estrictamente superior y evita un triplanar por textura. Lo único que el clásico sabe y el contexto no es usar textura distinta por eje (fuera de alcance).

## Diseño

### Motor / writer (`matwire_c4d.py`)

- `uvcontext_available()` — probe del nodo con el idiom de siempre (`FindLatestAsset(...).IsNullValue()`); el nodo es RS 2026.2+.
- `build_uvcontext_plan(proj_type)` → desc del nodo + la lista de conexiones a realizar. Como el fan-out (un `outcontext` → N puertos `uv_context`) **no es expresable en GraphDescription** (misma limitación que el splitter ORM: el anidamiento duplica el nodo, no hay `$ref`), se materializa con la receta imperativa ya en producción: apply aislado + `Connect` en una transacción.
- Escrituras obligatorias del contexto (trampas medidas en el spike): `proj_type` explícito; **`uv_tiling = 0`** (el valor 1 es **hex tiling**, no "una tesela"); los vec2 con `maxon.Vector(x, y, 0.0)`.
- Los `scale`/`offset`/`rotate` de cada sampler **se dejan en su default** — se multiplican con el contexto (medido), así que dejarlos limpios mantiene un único punto de verdad y libera el ajuste por-textura para el artista.
- `build_description` gana: Color Correct interpuesto en basecolor (siempre) y, cuando `multiply_ao` está activo y hay AO, el `rscolorlayer` (`layer1_blend_mode = 4` = Multiply — enum verificado; 2 daba una imagen radicalmente distinta) entre el basecolor corregido y `base_color`, con el AO como Layer 1. Con `multiply_ao` activo el AO deja de emitirse como sampler suelto.
- Renombrado por `net.maxon.node.attribute.title`: `Base Color`, `Roughness`, `Metalness`, `Normal`, `Height`, `AO`, `ORM`, `Opacity`, `Emission`, `Color Correct`, `AO Multiply`, `UV Context`, `Bump`, `Displacement`; los leftovers, con su nombre de archivo.
- Layout: nueva columna `-900` para el UV Context (mecanismo por-columna existente, sin cambios estructurales).
- Todo dentro del contrato vigente: el grafo se construye **antes** de insertar el material (un Cmd+Z revierte el lote), colorspaces y flipy siempre explícitos.

### Ops

- `matwire_create` acepta `{"projection": "uv"|"triplanar", "multiply_ao": bool}` (defaults `"uv"` / `false`); re-derivación server-side intacta.
- `matwire_preview` informa `uvcontext_available: bool` (para deshabilitar el selector con razón) y refleja el destino del AO en su fila (`→ base color (multiply)` cuando el checkbox está activo, `unconnected` si no) — la fila de AO deja de mentir igual que hicimos con la de ORM.

### SPA

- Sub-vista: **Projection** (SegmentedControl UV Channel / Triplanar) y **checkbox "Multiply dedicated AO map into base color" (*dedicated* deliberado: en packs solo-ORM el AO vive en el canal rojo del splitter y el toggle no haría nada)** (off), junto al de leftovers. Si `uvcontext_available` es false, el selector se deshabilita con la razón inline.

## Errores / no-regresión

- `projection = uv` + `multiply_ao = off` ⇒ render idéntico a v1.32.1 (el contexto en identidad no altera — medido). El grafo gana dos nodos (contexto + color correct) de coste ≈0.
- Sin el nodo de contexto disponible: el material se construye exactamente como en v1.32.1 y el preview lo dice — nunca una promesa que el writer no cumple.
- Contrato de un-undo y orden "grafo antes de insertar": intactos.

## Verificación

- pytest: planes puros (contexto con `proj_type`, conexiones esperadas, Color Correct interpuesto, AO layer on/off y su efecto en el sampler suelto, títulos de nodo, columna de layout), contratos de ops (payload nuevo, `uvcontext_available`, re-derivación).
- vitest: selector + checkbox + copys + fila de AO.
- Live: geo SIN UVs con `projection = triplanar` → textura proyectada correctamente (render, no eyeball de params); UV Channel en geo con UVs; AO on/off comparado por píxeles; un solo Cmd+Z revierte el lote; nodo de contexto compartido por TODOS los samplers (censo de conexiones).

## Fuera de alcance

- Scalar Ramps por defecto (+3 % medido; y si se añadieran algún día, con `interpolation = linear` explícito).
- OpenPBR (fase propia: otra tabla de puertos, requiere su spike), Sprite opacity, import-from-base, textura por eje (`triplanar` clásico), hex tiling (disponible en el mismo nodo compartido el día que se quiera, sin arquitectura nueva).
