# Estudio: Redshift SMC v1.5.0 (Cataclysm VFX) frente a Matwire

**Fecha**: 2026-10-22 · C4D 2026.304 (macOS) · Redshift node materials
**Fuente**: plugin comprado (`~/Downloads/Redshift_SMC_v1.5.0`), estudiado en vivo en un documento desechable. Complementa `2026-07-29-matwire-implementations.md` (Node Ninja, RS Node Tools, TexToMatO).

Regla: **estudiar-sí / copiar-no**. El plugin está cifrado (`.pypv`); no se ha descifrado ni introspeccionado su código. Todo lo de abajo sale de su UI, de sus ficheros legibles y del grafo que genera.

## Qué contiene el paquete
- `Redshift_SMC_Alpha_v150.pypv`: el plugin, cifrado. Registra un único comando (id 1054418).
- `RedshiftWrapper/`: la librería open source de gr4ph0s (2020) para materiales RS **Xpresso** (legacy). No aporta nada a node materials.
- `res/StandardMat.c4d`: plantilla, un material RS Shader Graph **Xpresso** (tipo 1036224), sin grafo en el node space de RS.
- `res/Patterns.json`: tablas de sufijos por canal más los estados de los checkboxes.

## UI (capturas del usuario)
- **Main**: Material Name, ruta de carpeta (campo de texto + `...`), botones **Single Material** y **Multiple Materials**.
- **Settings**: Projection Node, Normal Y; un checkbox por canal (Ambient Occ., Diffuse, Reflection, Roughness, Bump, Normal, Displacement, Opacity); tipo de material (desplegable "RS Standard Material"); **Maxon Noise**; **Colorspace** (desplegable, "ACEScg"); **Edit Patterns**, que edita las tablas de sufijos desde la UI, con Update y Reset.
- Sufijos (verbatim de `Patterns.json`): AO `ao, ambient, occlusion, ambientocclusion` · Diffuse `diffuse, diff, albedo, col` · Reflection `refl, ref, spec, metal, mtl` · Roughness `rough, gloss` · Bump `bump, bmp, height` · Normal `norm, normal, nrm` · Displacement `disp, dsp, height, displacement` · Opacity `opacity, opac, alph, alpha`.

## Grafo generado (Multiple Materials sobre `rusty_metal_*` + `brick_wall_*`, todo activado)
22 nodos por material. Volcado completo de puertos y conexiones con un tag Python temporal (en 2026 el código del tag es el parámetro **400**, no `TPYTHON_CODE` 23). Valores comparados con un nodo recién creado de cada tipo (= default de RS):

| Pieza | Qué hace SMC | Default RS |
|---|---|---|
| Transformación compartida | 3 nodos titulados POSITION / SCALE / ROTATION (`rsmathabsvector`/`rsmathabs` usados como valor de paso) → `offset/scale/rotate` de **todos** los samplers | — |
| Base color | sampler → `base_color`, colorspace **ACEScg** | — |
| AO | sampler (colorspace **ACEScg**) → `color_multiplier` del sampler de base color: multiplica siempre, sin nodo extra | — |
| Normal | sampler RAW → Bump Map `inputtype=1` → Bump Blender `bumpinput0` | inputtype 0 |
| Height como bump | el mismo height → RS Ramp ("Bump") → Bump Map height → Bump Blender `baseinput` | — |
| Maxon Noise | `noise_type=8` → Bump Map → Bump Blender `bumpinput1` | noise_type 13 |
| Bump Blender | `bumpweight0=1`, `bumpweight1=1`, `additive=true` → `bump_input` | pesos 0, additive false |
| Displacement | height → RS Ramp ("Disp") → Displacement `newrange_min=-0.5`, `newrange_max=0.5` → output | newrange **0..1** |
| Roughness / Spec | sampler → RS Ramp ("Rough"/"Spec") → **sin conectar**. El BRDF queda con `refl_roughness`/`metalness` por defecto | — |
| Rampas | `linearknot` en las dos llaves (usadas como "niveles" ajustables) | smoothknot |

## Defectos observados
1. **Roughness y metalness no llegan al material.** Las rampas Rough/Spec terminan en el vacío: nodos muertos. El Clean Dead Nodes de Sentinel los borraría.
2. **"metal" como sufijo de Reflection rompe nombres y canales**: `rusty_metal_*` se llama `rusty`. Además, el sampler Specular de `rusty` carga el fichero **Roughness** (`rusty_metal_Roughness` contiene "metal"), y el Metalness no se carga.
3. **Colorspace "ACEScg" en PNG sRGB de 8 bits** (base color) y en el **AO**, que es un dato y debería ser RAW. El QC #13 de Sentinel lo reporta solo como `foreign_cs` (Info).
4. **Single Material en macOS crea un material Xpresso legacy vacío** (tipo 1036224, sin texturas). El propio vendedor dice que en macOS hay que usar Multiple.
5. Height con doble uso (bump + displacement) y Maxon Noise en el bump a peso 1, aditivo y siempre encendido.

## Lo que Matwire no tiene (candidatos)
1. **Rango de displacement centrado** (`newrange -0.5..0.5`). Matwire solo escribe `texmap` y hereda el **0..1** de RS: un height con gris medio = "sin relieve" infla toda la superficie medio `scale`. Es una corrección pequeña, pero falta medir la convención de los packs reales (gris medio = 0) antes de fijarla.
2. **Height → bump cuando no hay normal map.** Hoy el height va solo a displacement, y eso no se ve sin teselación ni displacement activados en el objeto, así que el artista ve el material plano.
3. **Imperfecciones opt-in**: Maxon Noise → Bump Map → Bump Blender sobre el bump del set, con peso bajo y un preview que lo diga. El SMC lo aplica a peso 1, aditivo y por defecto.
4. **QC #13: un canal de datos (AO/rough/metal/normal/height) con un colorspace OCIO de color (p. ej. ACEScg) se trata como `foreign_cs` (Info).** Un plugin de mercado los produce, así que en escenas reales existen. Un mapa de datos con ese colorspace es inequívocamente erróneo, y el Fix a RAW está en la whitelist (`tex0/colorspace` acepta SRGB/RAW). Para los canales de color, ACEScg puede ser legítimo (texturas EXR ACEScg), así que seguiría como Info.
5. Menores: rampas de ajuste por canal (rough/bump/disp) y desactivar canales en el preview. Un editor de sufijos en la UI **no**: los sufijos son decisión de proyecto (`matwire_suffixes` en el ruleset).

## Contraste con otras herramientas (2026-10-23)
Antes de llevar los candidatos a producción, se comparó cada uno con cómo lo resuelven otros DCC e importadores. Fuentes: documentación oficial cuando la hay; los foros solo como indicio.

| Candidato | Qué hace el resto | Veredicto |
|---|---|---|
| 1. Displacement centrado en gris medio | Blender: `Midlevel` por defecto 0.5, "valor neutro que no desplaza" ([manual](https://docs.blender.org/manual/en/4.3/render/shader_nodes/vector/displacement.html)). ZBrush: 50 % gris = sin cambio ([manual](https://help.maxon.net/zbr/en-us/Content/html/reference-guide/tool/polymesh/displacement-map/displacement-map.html)). 3ds Max Displace: 50 % gris = cero ([docs](https://help.autodesk.com/cloudhelp/2017/ENU/3DSMax/files/GUID-12F0E0BA-3FCA-4C8F-8C9B-C77C8FB4A45C.htm)). Octane: Mid Level 0.5 para imágenes ([docs](https://docs.otoy.com/houdini/VertexDisplacement.html)). Adobe: el gris medio suele ser "plano" ([Stager](https://helpx.adobe.com/substance-3d-stager/features/material-displacement.html)). La doc del nodo de RS no documenta el remap ([Maxon](https://help.maxon.net/c4d/2027/en-us/Content/html/COM_REDSHIFT3D_REDSHIFT4C4D_NODES_CORE_DISPLACEMENT.html)). | **Sí — implementado.** Es la convención mayoritaria y el default 0..1 de RS es la excepción. Los formatos enteros (8/16 bits) se centran. Los float se deciden por sus píxeles (muestreo con stride): con valores negativos, cero en 0 → 0..1; todo en 0..1 con media a ±0.1 de 0.5 → gris medio → −0.5..0.5; cualquier otro caso → 0..1 marcado "no verificado" en el preview. |
| 2. Height → bump sin normal map | Blender renderiza el displacement **como bump por defecto** salvo que se active el displacement real (mismo manual). Pero Redshift ≥ 3.6.04 tiene **Automatic Displacement**: desplaza sin tag si el material tiene nodo Displacement, aunque no añade densidad de malla ([Maxon](https://help.maxon.net/c4d/2025/en-us/Content/html/SUBSTANCE_WITH_REDSHIFT.html)). | **Medido: no hace falta.** El Automatic Displacement de RS desplaza geometría real incluso en un plano de 1×1 sin tag de RS (la silueta se mueve), así que no se añade bump; duplicarlo sería el defecto de SMC. Ver `2026-10-23-matwire-height-only-displacement.md`. |
| 3. QC #13: mapa de datos con colorspace OCIO de color | Maya asigna el colorspace por **reglas de nombre de fichero** (`*normal*` → Raw) ([Autodesk](https://help.autodesk.com/cloudhelp/2018/ENU/Maya-Rendering/files/GUID-631C665F-3092-4B2B-90B7-2A94158870C9.htm)). Guía ACES: Utility-Raw para normal/displacement/bump/roughness ([ACEScentral](https://community.acescentral.com/t/data-normal-roughness-texture-conversion-clarification/3256)). Problema conocido en Arnold: la detección automática convirtió normal maps de 8 bits a ACEScg ([foro Arnold](https://answers.arnoldrenderer.com/questions/35868/aces-and-tx-conversion.html)). | **Sí — implementado** (PR aparte). El resto lo resuelve al crear el material; Sentinel es el único que lo audita después, y SMC demuestra que hay escenas con datos en ACEScg. Fix a RAW (whitelist). Los canales de color con ACEScg siguen como Info. |
| 4. Imperfecciones (Maxon Noise en el bump) | Ningún importador de referencia lo hace: Node Wrangler, Node Ninja, Substance→RS de Maxon y los importadores MaterialX de Houdini se limitan a cablear los mapas y asignar colorspaces. Las imperfecciones son lookdev (Megascans las vende como assets aparte). | **No en Matwire**: alteraría el aspecto de un material escaneado o autorizado. Como mucho, una acción de Tools aparte sobre un material seleccionado, si algún día se pide. |

Observación lateral: SMC escribe `tex0/colorspace = "ACEScg"` y C4D 2026.304 no se cae. El gotcha de CLAUDE.md ("cualquier string distinta de SRGB/RAW crashea") se midió con strings inválidas; los nombres OCIO válidos parecen aceptarse. Verificado después escribiéndolo nosotros (2026-10-23, gotcha actualizado en CLAUDE.md); el Fix sigue escribiendo solo SRGB/RAW.

## Lo que confirma el diseño de Matwire
Agrupado por raíz con separador obligatorio (evita el bug de "metal"), ORM/ARM, gloss→roughness, DX/GL con flip, variantes de resolución, OpenPBR, UV Context compartido, AO opt-in sin pisar el base color, colorspace por canal (sRGB solo en base color/emission), preview antes de crear y una sola Cmd+Z.
