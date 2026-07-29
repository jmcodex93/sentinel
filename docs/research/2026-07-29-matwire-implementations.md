# Investigación: implementaciones instaladas de auto-wire textura→material RS (para spec v1.32)

**Fecha**: 2026-07-29
**Fuentes** (solo lectura, en `~/Library/Preferences/Maxon/Maxon Cinema 4D 2026_9D810372/plugins/`):
1. **SOM Node Ninja** — `School of Motion/School of Motion\SOMNodeNinja.pyp` (1880 líneas, Python plano, NO ofuscado)
2. **RS Node Tools — Auto Connect PBR Textures** — `RS Node Tools/Auto_Connect_PBR_Textures.pyp` + `mw_utils/redshift_utils.py`
3. **TexToMatO v10.2** — `TexToMatO/TexToMatO.pyp` + paquete `Salad/` (fork del renderEngine de DunHou)

Regla aplicada: **estudiar-sí / copiar-no**. Los ID strings de nodos/puertos son hechos de la API de Redshift (no expresión con copyright); los patrones de código de cada plugin NO se copian salvo donde la licencia lo permita (ver §Licencias).

---

## 1. SOM Node Ninja (School of Motion)

### Licencia
**Sin licencia ni copyright en el código ni en el manual** (`SOM_Node_Ninja_Manual.md` no menciona términos). Plugin gratuito pero *all rights reserved* por defecto → **estudiar-sí / copiar-no estricto**. Los ID strings y valores de puerto sí son reutilizables como hechos.

### Tabla de sufijos (verbatim, LISTA ORDENADA — el orden es semántica)
```python
PBR_PATTERNS = [
    ("normal_dx",    ["normaldx", "normal_dx", "nrm_dx", "dx_normal", "nor_dx"]),
    ("normal_gl",    ["normalgl", "normal_gl", "nrm_gl", "gl_normal", "nor_gl"]),
    ("normal",       ["normal", "nrm", "nor", "nmap"]),
    ("displacement", ["displacement", "displace", "disp", "height"]),
    ("roughness",    ["roughness", "rough", "rgh"]),
    ("metalness",    ["metalness", "metallic", "metal"]),
    ("sss",          ["subsurface", "sss", "scatter"]),
    ("ao",           ["ambientocclusion", "ambient_occlusion", "occlusion", "occ", "ao"]),
    ("emission",     ["emissive", "emission", "emit"]),
    ("opacity",      ["opacity", "alpha", "transparency", "translucency"]),
    ("specular",     ["specular", "spec"]),
    ("albedo",       ["albedo", "basecolor", "base_color", "diffuse", "color", "col", "diff"]),
]
IMG_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".hdr", ".tx", ".tga", ".bmp"}
_COLOR_TYPES = frozenset({"albedo", "emission", "sss"})   # todo lo demás → Raw
```
Notas de diseño: DX/GL van ANTES que "normal" para que `NormalGL` no caiga en el catch-all; `ambientocclusion` sin separador cubre Poliigon/ambientCG; `color` cubre `_Color` de ambientCG. **No hay glossiness** (Node Ninja no soporta packs spec/gloss).

### Estrategia de matching
```python
stem = re.sub(r'[-\s]+', '_', os.path.splitext(filename)[0].lower())
re.search(r'(?<![a-z])' + re.escape(kw) + r'(?:_?map)?(?![a-z])', stem)
```
- Normaliza guiones Y ESPACIOS a `_`, lowercase.
- Frontera por **letra** (`(?<![a-z])…(?![a-z])`), no por `\b`: dígitos adyacentes SÍ matchean (`rough2` matchea `rough`).
- `(?:_?map)?` tolera `RoughnessMap` / `Normal_Map` sin listar variantes.
- Primera entrada de la tabla que matchea gana (orden = precedencia); primer ARCHIVO por canal gana (`sorted(os.listdir)` → orden alfabético determinista).
- Post-proceso: si hay `normal_gl` → descarta DX y genérico y usa GL; si SOLO hay DX → lo mantiene como `normal_dx` y el wiring activa **flipy** en el Bump Map.

### Agrupación de sets / UDIM / variantes de resolución
- **Set = CARPETA**, no raíz de nombre: escanea la carpeta raíz + 2 niveles de subcarpetas (`scan_for_sets`); cada carpeta con texturas = 1 material con el nombre de la carpeta. Una carpeta con dos sets mezclados produce UN material mal mezclado (nuestro grouping por raíz es superior).
- **UDIM: nada**. **Variantes de resolución: nada** (primer archivo alfabético gana — `_2K` gana a `_4K` por azar alfabético).
- Colisión de nombre de material: diálogo Replace / Duplicate (`name_02`) / Skip; helper `_unique_mat_name`.

### API de grafo
**GraphNode imperativo** (AddChild + búsqueda de puertos + `Connect`), NO GraphDescription. Transacción: `graph.BeginTransaction()` … `tx.Commit()` / `tx.Rollback()` en except. IDs de nodo:
```
nodespace  com.redshift3d.redshift4c4d.class.nodespace
StandardMat com.redshift3d.redshift4c4d.nodes.core.standardmaterial
OpenPBR     com.redshift3d.redshift4c4d.nodes.core.openpbrmaterial
TexSampler  com.redshift3d.redshift4c4d.nodes.core.texturesampler
Bump Map    com.redshift3d.redshift4c4d.nodes.core.bumpmap
Displacem.  com.redshift3d.redshift4c4d.nodes.core.displacement
Output      com.redshift3d.redshift4c4d.node.output
Triplanar   com.redshift3d.redshift4c4d.nodes.core.triplanar
ShaderSwitch com.redshift3d.redshift4c4d.nodes.core.rsshaderswitch
Color Layer com.redshift3d.redshift4c4d.nodes.core.rscolorlayer
Value node  net.maxon.node.type       (datatype/in/out; para masters Scale/Offset/Rot)
UV Context  com.redshift3d.redshift4c4d.nodes.core.uvcontextprojection   (RS 2026.2+)
```
Puertos (matching por sufijo local del id): Standard → `base_color, refl_roughness, metalness, emission_color, opacity_color, refl_color, ms_color, bump_input, outcolor`; OpenPBR → `base_color, specular_roughness, base_metalness, emission_color, geometry_opacity, specular_color, subsurface_color, geometry_normal`. Output → `surface`, `displacement`, `rs_uv_context`.

### Path de textura + colorspace (mecánica exacta)
- `tex0` es un puerto GRUPO: `tex_node.GetInputs().FindChild("…texturesampler.tex0")` → `FindChild("path")` → `SetPortValue(maxon.Url(...))`.
- **Gotcha documentado en el código**: construyen la URL a mano `maxon.Url("file:///" + path.replace("\\","/"))` porque `pathlib.as_uri()` codifica espacios como `%20` y C4D guarda el string codificado literal y luego NO encuentra el archivo.
- Colorspace: `tex0.FindChild("colorspace").SetPortValue(maxon.String("RS_INPUT_COLORSPACE_RAW"))`. Los tipos color (albedo/emission/sss) se dejan en **default** (auto/sRGB) — no fuerzan sRGB. El header admite: "exact port ID / value string may vary by RS version… skipped silently" → no es OCIO-name-aware; usa los tokens legacy `RS_INPUT_COLORSPACE_*` que RS mapea internamente bajo OCIO.

### Wiring por canal
- **Normal** → Bump Map con `inputtype = 1` (Tangent-Space Normal; prueba varios nombres de puerto `inputtype/maptype/...` y varios tipos `Int64/Int32` por variación de versión RS); DX → `flipy = True` (puerto confirmado `…bumpmap.flipy`); tex→`input`, bump `out` → mat `bump_input` (Std) / `geometry_normal` (OpenPBR).
- **Displacement** → tex `outcolor` → disp `texmap`; disp `out` → **output** `displacement`. NO tocan scale/midlevel/newrange.
- **AO**: SÍ se conecta — `rscolorlayer` "AO × Albedo" con `layer1_enable=True`, `layer1_blend_mode=4` (Multiply); albedo → `base_color` (del layer), AO → `layer1_color`, layer `outcolor` → mat `base_color`.
- **Specular** → `refl_color`. Sin inversión de gloss (no soportado).
- **Triplanar**: 3 modos — solo-UV, solo-Triplanar (un nodo triplanar por textura, `sameimageoneachaxis=True`, tex→`imagex`), o ambos con `rsshaderswitch` (shader0=UV, shader1=triplanar, selector=value-node bool "Triplanar Switch"). Masters Scale/Offset/Rotation = nodos `net.maxon.node.type` (datatype `net.maxon.parametrictype.vec<2,float64>` para UV, `vec<3,float>` para triplanar) conectados a `scale/offset/rotate` del sampler o del triplanar.
- **RS 2026.2+**: detecta el nodo **UV Context Projection** y entonces UN solo nodo `uvcontextprojection` (`proj_type`: 1=UV Channel, 2=Tri-Planar) → output `rs_uv_context` controla TODAS las texturas — elimina triplanars/masters por textura.
- **OpenPBR**: detección por repositorio de assets — `maxon.AssetDataBasesInterface.GetUserPrefsRepository().FindLatestAsset(maxon.AssetTypes.NodeTemplate(), maxon.Id(node_id), …).IsPopulated()` — patrón limpio de **feature-probing por versión de RS** (lo usan también para UV Context). Fallback a Standard Material.

### Layout de nodos
Posiciones manuales: `node.SetValue("net.maxon.node.base.xpos", maxon.Vector(x,0,0))` / `ypos`; título `net.maxon.node.attribute.title`; color `maxon.NODE.BASE.COLOR`; **scaffolds** (grupos visuales): AddChild `net.maxon.node.scaffold` + asignar `net.maxon.node.attribute.scaffoldid` a los miembros. Auto-arrange best-effort: `c4d.CallCommand(465002363)` ("Arrange All Nodes", Shift+L) — solo surte efecto con el Node Editor abierto con ese material activo (limitación admitida).

### Picker / UI
`c4d.storage.LoadDialog(type=c4d.FILESELECTTYPE_ANYTHING, flags=c4d.FILESELECT_DIRECTORY)` modal desde CommandData (seguro en GeDialog, NO en nuestro op-drain). Diálogo de opciones previo con estado persistente por sesión (dict de clase). Sin drag&drop.

---

## 2. RS Node Tools — Auto Connect PBR Textures (autor coreano, "mw")

### Licencia
**Sin licencia, sin header de copyright** → all rights reserved por defecto. Estudiar-sí / copiar-no.

### Por qué empaqueta PIL
**NO lo usa el auto-connect.** PIL (`dependencies/PIL`, wheel pillow-12.1.0 con binarios `cp311-win_amd64.pyd` → **solo Windows**) lo usa el plugin hermano `Resize_Texture_Resolution.pyp`: lee dimensiones y re-escala archivos de textura en disco (equivalente a nuestro Shrink de v1.18, que ya cubrimos con `imagemeta.py` + savers de C4D, sin dependencia externa y cross-platform). Sin relevancia para v1.32.

### Tabla de sufijos (verbatim)
```python
TEXTURE_CHANNELS = {
    "base_color":    ["basecolor","base","color","albedo","diffuse","diff","col","bc","alb","rgb","d","dif"],
    "normal":        ["normalgl","normalopengl","normal","norm","nrm","nml","nrml","nor","n"],
    "bump":          ["bump","b"],
    "ao":            ["ao","ambient","occlusion","occ","amb","ambientocclusion"],
    "metalness":     ["metallic","metalness","metal","mtl","met","m"],
    "refl_roughness":["roughness","rough","rgh","r"],
    "refl_weight":   ["specular","spec","s","refl","reflection"],
    "glossiness":    ["glossiness","gloss","g"],
    "opacity_color": ["opacity","opac","alpha","o","a","cutout"],
    "translucency":  ["translucency","transmission","trans","sss","subsurface","scatter","scattering"],
    "displacement":  ["displacement","disp","dsp","height","h"],
    "emission_color":["emissive","emission","emit","illu","illumination","selfillum","e"],
}
```
Incluye tokens de UNA letra (`d,n,b,m,r,s,g,o,a,h,e`) — cubre naming Substance `_N`, `_R`… pero es peligroso sin contexto (colisiones).

### Matching
`_split_into_components(fname)`: quita extensión, **elimina TODOS los dígitos**, reemplaza separadores (` . - __ -- #`) por `_`, split por `_`, lowercase. `GetTextureChannel`: recorre componentes **en orden inverso** (el último componente gana → prioridad al sufijo real) y compara por **igualdad exacta de componente** contra las listas. La eliminación de dígitos hace que `basecolor2`→`basecolor` y `4k`→`k` (los tokens de resolución se desintegran — colateral, no diseño).

### Entrada: multi-FILE, no carpeta + auto-expand de set
Picker Win32 nativo por ctypes (`GetOpenFileNameW`, `OFN_ALLOWMULTISELECT`) — **solo Windows**. Truco de UX interesante: si el usuario elige UN solo archivo, escanea el directorio y auto-selecciona todos los archivos cuyo **primer componente** coincide (raíz del set) → "elige una textura del set y te traigo el set entero". Sin UDIM, sin variantes de resolución, sin multi-set (asume un set por invocación). Trabaja sobre el material ACTIVO existente (o crea uno vía `CallCommand(1040264, 1012)`), no crea N materiales.

### IDs de nodo/puerto (oro — strings COMPLETOS verbatim de `redshift_utils.py`)
```python
ID_RS_NODESPACE           = "com.redshift3d.redshift4c4d.class.nodespace"
ID_RS_STANDARD_MATERIAL   = "com.redshift3d.redshift4c4d.nodes.core.standardmaterial"
ID_RS_OUTPUT              = "com.redshift3d.redshift4c4d.node.output"
ID_RS_TEXTURESAMPLER      = "com.redshift3d.redshift4c4d.nodes.core.texturesampler"
ID_RS_BUMPMAP             = "com.redshift3d.redshift4c4d.nodes.core.bumpmap"
ID_RS_DISPLACEMENT        = "com.redshift3d.redshift4c4d.nodes.core.displacement"
ID_RS_UV_CONTEXT_PROJECTION = "com.redshift3d.redshift4c4d.nodes.core.uvcontextprojection"
ID_RS_MATH_VECTOR_MULTIPLY = "com.redshift3d.redshift4c4d.nodes.core.rsmathmulvector"
ID_RS_MATH_INVERT         = "com.redshift3d.redshift4c4d.nodes.core.rsmathinv"
ID_RS_COLOR_CORRECT       = "com.redshift3d.redshift4c4d.nodes.core.rscolorcorrection"
ID_RS_TRIPLANAR           = "com.redshift3d.redshift4c4d.nodes.core.triplanar"

# Standard Material
…standardmaterial.base_color / .metalness / .refl_roughness / .refl_weight
…standardmaterial.opacity_color / .emission_color / .bump_input / .outcolor

# Texture Sampler
…texturesampler.tex0            # GRUPO; hijos: "path", "colorspace"
…texturesampler.scale / .offset / .rotate / .outcolor / .uv_context

# Bump Map
…bumpmap.input / .out / .inputtype     # inputtype: 1=Tangent-Space Normal, 0=Height Field

# Invert (para gloss→roughness)
…rsmathinv.input / …rsmathinv.out

# Vector Multiply (base×AO)
…rsmathmulvector.input1 / .input2 / .out

# Color Correct
…rscolorcorrection.input / .outcolor

# Displacement
…displacement.texmap / …displacement.out
…node.output.displacement / …node.output.surface

# UV Context Projection
…uvcontextprojection.outcontext / .proj_type   # 0=Passthrough, 1=UV Channel, 2=Triplanar
```

### Wiring y decisiones
- Transacción única `with graph.BeginTransaction() as t: … t.Commit()`.
- **Re-cableo idempotente**: antes de conectar a un puerto de material, `remove_connections()` (busca el puerto, `GetConnections(maxon.PORT_DIR.INPUT, …)`, `maxon.GraphModelHelper.RemoveConnection(src, dst)`).
- Base×AO: `rsmathmulvector` (base→input1, ao→input2) → **siempre** intercala `rscolorcorrection` → `base_color` (CC de cortesía para grading rápido).
- Normal vs Bump conviven como canales distintos; conflicto → QuestionDialog (Normal=inputtype 1, Bump=inputtype 0/Height Field).
- Roughness vs Glossiness: conflicto → QuestionDialog; gloss elegida → nodo `rsmathinv` intermedio.
- Specular → `refl_weight` (¡no `refl_color`! — interpreta el mapa spec como peso, criterio distinto a Node Ninja y TexToMatO).
- Colorspace Raw para todo salvo `base_color, emission_color, opacity_color, translucency` (nota: deja opacity en sRGB — cuestionable; los otros dos plugins la tratan raw/data).
- Selección de nodos creados (`maxon.GraphModelHelper.SelectNode`) + `c4d.CallCommand(465002311)` ("Arrange Selected Nodes" — segundo command-id de arrange, complementa el 465002363 de NN).
- Búsqueda de material/output existentes: `root.GetInnerNodes(mask=maxon.NODE_KIND.NODE, includeThis=False)` comparando `GetValue("net.maxon.node.attribute.assetid")[0]`.

---

## 3. TexToMatO v10.2 (Jérôme Stephan) + backend Salad

### Licencia — la más matizada
- `TexToMatO.pyp`: **"©2026 by Jérôme Stephan. All rights reserved."** (comercial, Gumroad) → copiar-no.
- `Salad/__init__.py`: `__author__ = "DunHou"`, `__license__ = "MIT license"` — **Salad es un fork del renderEngine de DunHou declarado MIT en su header**. Ojo: el repo upstream `renderEngine` que tenemos clonado NO trae fichero LICENSE (el CLAUDE.md ya lo marca "no license — do NOT copy verbatim without permission"). El header MIT dentro de Salad es una declaración del propio autor, pero al venir distribuido DENTRO de un producto all-rights-reserved, la postura segura para Sentinel: **usar los ID strings y el conocimiento de patrones (hechos), no copiar código de ninguno de los dos**. Nuestro plan GraphDescription además hace innecesario el copy.

### Tabla de sufijos (verbatim, defaults + extensible por JSON)
```python
defaults = {
  "extensions":   ["png","jpeg","jpg","dds","tga","tif","tiff","bmp","exr"],
  "albedo":       ["Base_Color","BaseColor","basecolor","color","COL","Color","Albedo","albedo","col","Base","diff","_D-","_D."],
  "normal":       ["Normal_OpenGL","normal","NRM","Normal","nml","nrml","Norm","_N.","_N(","nor_gl","nmap"],
  "bump":         ["Bump","bump","BUMP","bump_map"],
  "ao":           ["Mixed_AO","ao","AO","AmbientOcclusion"],
  "metalness":    ["Metallic","Meta","_M.","metal.","metalness"],
  "roughness":    ["Roughness","roughness","Roug","_R.","rough."],
  "specular":     ["Specular","specular","_S."],
  "glossiness":   ["GLOSS","glossiness","gloss","Glossiness"],
  "alpha":        ["opacity","alpha","opac","_O.","Opacity"],
  "transmission": ["_L.","_L_","Translucency","Transmission"],
  "displacement": ["height","DISP","disp","Displacement","depth"],
  "arm":          ["ARM","arm"],
  "misc":         ["soft-mask","color-mask","mix-mask","tint-mask","paint-mask","mask","_M(","_MSK","OVERLAY","blend"],
}
```
- Tokens de una letra **CON delimitador incorporado** (`_D.`, `_N(`, `_R.`) — mucho más seguro que las letras sueltas de RS Node Tools.
- **`custom_regex.json`** (res/ default + user/ override): por canal `{"regex": [...], "add": true|false}` — añade o REEMPLAZA la lista. Precedente directo para un futuro override por `sentinel_rules.json`.
- Case-sensitivity es un toggle (`caseInsensitive`); por defecto sensible (por eso las listas duplican mayúsculas).

### Matching y agrupación multi-set (el más cercano a nuestro spec)
- Compila TODAS las listas en una alternation regex ordenada por longitud desc: `texture_regex = r'^(.*?)(<CHANNELS>)(.*?)(?:<EXTS>)\b'` — el token puede aparecer en CUALQUIER posición, no solo sufijo.
- **`prefix = match.group(1)` = raíz del set** → `image_groups.setdefault(prefix, []).append((channel_name, filepath))` → **N materiales por carpeta, agrupados por raíz de nombre** (exactamente nuestro modelo multi-set). Con scan de subcarpetas activo, el prefix pasa a ser el nombre de la subcarpeta.
- Conserva TODOS los archivos por canal (lista), y `_pick_primary_texture` elige el primario; para normal **prefiere el candidato no-DX** (`re.search(r"(dx|directx)", basename, IGNORECASE)` para filtrar).
- **`import_leftovers`**: los archivos no cableados (segundos roughness, masks, misc) se importan igualmente como TextureSamplers SUELTOS en el grafo, con colorspace correcto por canal — alternativa de producto a nuestro `ignored` (visible en el grafo en vez de solo en el preview).
- **Import from base**: modo que parte de un material existente, lee la ruta de su TextureSampler y deriva el set completo de esa carpeta (regex ancla el prefijo del archivo base). Fuera de nuestro alcance pero es LA feature diferencial de TexToMatO.
- UDIM: **nada** en los tres plugins. Variantes de resolución: **nada** (nuestro `split_res_token` es diferencial).

### Texturas empaquetadas ARM/ORM (nuestro spec NO lo cubre)
Config `multiTex` (default: BASE=ARM, R=AO, G=Roughness, B=Metalness): el archivo `*_ARM.*` pasa por `rscolorsplitter`:
```
…rscolorsplitter.outr / .outg / .outb   (input: entrada del splitter)
```
y cada canal se enruta a su puerto; con lógica de prioridad: si existe un mapa dedicado para ese canal, el canal del splitter se omite (y el par roughness/glossiness cuenta como equivalente). AO del splitter reutiliza el árbol AO normal vía `ao_input_port`.

### Wiring RS (vía Salad/renderEngine, GraphNode + EasyTransaction)
- Material: `BaseMaterial(c4d.Mmaterial)` → `GetNodeMaterialReference().CreateDefaultGraph(RS_NODESPACE)`; localiza el BRDF root por lista `REDSHIFT_BRDF_IDS`. Cachea puertos del Standard (`base_color, metalness, refl_color, refl_weight, refl_roughness, refl_isglossiness, refl_aniso, ms_color/ms_amount, opacity_color, bump_input, overall_color, refr_color/refr_thin_walled, emission_*`) y del OpenPBR (`base_color, base_metalness, specular_color/weight/roughness, subsurface_color/weight, geometry_opacity, geometry_normal, geometry_thin_walled`).
- **Gloss sin nodo invert**: Standard Material tiene el puerto BOOL `…standardmaterial.refl_isglossiness` — si hay mapa gloss, lo conecta DIRECTO a `refl_roughness` y pone `refl_isglossiness=True` (el material interpreta la entrada como gloss). Solo si el puerto no existe (OpenPBR) cae a `rsmathinv`. **Más limpio que nuestra inversión por nodo** — cero nodos extra y editable después.
- Colorspace: idéntico a los otros — `tex0` → hijo `colorspace` → `"RS_INPUT_COLORSPACE_RAW"` o `"RS_INPUT_COLORSPACE_SRGB"` (aquí sí fuerzan sRGB explícito en los mapas color). También existe `…texturesampler.tex0_gamma`. Nada OCIO-aware.
- AO: `AddAOTree` — `rscolorlayer` (`…rscolorlayer.base_color`, `.layer1_color`, `layer1_blend_mode=4` Multiply) → `base_color`, **y además conecta AO → `refl_weight`** (atenúa reflexión en oclusión — decisión de shading opinada).
- Roughness/metalness/alpha llevan opcionalmente `rsscalarramp` (`…rsscalarramp.input/.out`) como "CC de datos" remapeable; albedo/emission llevan `rscolorcorrection`.
- Opacity → **modo sprite opcional** (`spriteOpacity`, default ON para RS): nodo `com.redshift3d.redshift4c4d.nodes.core.sprite` — grupo `sprite.tex0` (hijos path/colorspace), `sprite.input` ← BRDF `outcolor`, `sprite.outcolor` → output `surface` (se intercala entre material y output; es la vía recomendada por RS para cutouts, mucho más barata que opacity_color).
- Displacement: sampler raw → `displacement.texmap` → `displacement.out` → `output.displacement`. **Ninguno de los tres toca scale / midlevel / newrange-oldrange del nodo Displacement** (el mid-level 0.5 de un height 16-bit queda en manos del artista).
- Emission → `emission_color` (sRGB). Nota: NINGUNO de los tres pone `emission_weight` — en Standard Material el default de `emission_weight` es 0.0, así que cablear solo `emission_color` produce emisión invisible (TexToMatO al menos expone el puerto en el editor vía `AddPort`). Bug de mercado que podemos no repetir.
- Transform masters: grupo de nodos (`maxon.GraphModelHelper.CreateInputPort/CreateOutputPort` sobre un group root) exponiendo Scale/UniScale — equivalente sofisticado de los value-masters de NN.
- Detección de renderer/estado: `c4d.plugins.FindPlugin(ID_REDSHIFT, PLUGINTYPE_ANY)` + `Redshift.IsNodeBased()` → nuestro `redshift_unavailable`.

### Picker / UI
`c4d.storage.LoadDialog(c4d.FILESELECTTYPE_ANYTHING, "Select texture folder", c4d.FILESELECT_DIRECTORY, "Select")` + campo de texto persistido en `settings.json` (patrón dual picker+texto — igual que nuestro plan de fallback). Sin drag&drop. Undo: `doc.StartUndo()/EndUndo()` alrededor del LOTE completo de materiales + `AddUndo(UNDOTYPE_NEWOBJ, mat)` por material (paridad con nuestro "un undo por lote").

---

## 4. Síntesis transversal

| Aspecto | Node Ninja | RS Node Tools | TexToMatO | Spec v1.32 |
|---|---|---|---|---|
| API grafo | GraphNode + tx | GraphNode + tx | GraphNode + tx (renderEngine) | **GraphDescription** (nadie lo usa aún — diferencial, menos código, layout automático) |
| Agrupación | por carpeta | 1 set/invocación | **por raíz de nombre** | por raíz ✓ |
| Variantes res | no | no (borra dígitos) | no | **sí** (diferencial) |
| UDIM | no | no | no | out of scope ✓ |
| Gloss | no soporta | invert node | **refl_isglossiness bool** | invert (mejorable) |
| AO | conectado (colorlayer×) | conectado (mulvector×) | conectado (colorlayer× + refl_weight) | **sin conectar** (decisión consciente, contra-mercado) |
| Normal DX/GL | GL>DX, flipy | conflicto→pregunta | prefiere no-DX | **no distingue** (gap) |
| ORM/ARM | no | no | **sí (colorsplitter)** | no (gap) |
| Sprite opacity | no | no | **sí** | no |
| Colorspace | raw explícito, color=default | raw explícito, sRGB=default | raw Y srgb explícitos | tabla única ✓ (usar tokens `RS_INPUT_COLORSPACE_*`) |
| Picker | LoadDialog modal | Win32 ctypes | LoadDialog modal + texto | op-drain: texto + resolver Browse en plan ✓ |

Command-ids útiles (no documentados): `465002363` Arrange All Nodes · `465002311` Arrange Selected Nodes · `465002328` Select Active Material in Node Editor · `1040264(,1012)` crear material RS Standard.

---

## Recomendaciones para el spec v1.32 (ordenadas por valor)

1. **Normal GL/DX** (gap real, resultado incorrecto en render si entra un pack DX — FAB/Unreal exporta DX por defecto). Añadir a la tabla los sufijos `normaldx|normal_dx|nrm_dx|dx_normal|nor_dx` y `normalgl|normal_gl|nor_gl|normalopengl`; regla pura: GL gana sobre DX y sobre genérico; si SOLO hay DX, cablear con `…bumpmap.flipy = True`. Coste mínimo (un bool en el writer), corrección grande.
2. **Gloss vía `refl_isglossiness`, no nodo invert**: el Standard Material tiene el puerto bool `com.redshift3d.redshift4c4d.nodes.core.standardmaterial.refl_isglossiness`; conectar gloss directo a `refl_roughness` + poner ese bool = cero nodos extra, semántica nativa, editable. Cambiar la línea "Glossiness → inversión (nodo matemático…)" del spec. (Fallback `rsmathinv` con puertos `.input`/`.out` si el puerto no existiera.)
3. **`emission_weight = 1.0` cuando hay mapa de emisión**: default 0.0 → los tres plugins del mercado producen emisión invisible. Un `SetPortValue` nos diferencia con corrección real.
4. **Ampliar la tabla de sufijos** con los sinónimos verbatim del mercado (manteniendo nuestro delimitado por `_`/`-`/`.` que ya es más sano que las letras sueltas): roughness+`rgh`; metal+`met, mtl`; normal+`nrm` (ya), `nor` (ya), `norm, nml, nrml, nmap`; height+`dsp, depth`; ao+`occ, ambient_occlusion` (y aceptar `ambientocclusion` pegado — ya está); emission+`emit`; opacity+`cutout, transparency`; basecolor+`base, dif`. Y tolerar el sufijo `map` pegado (`RoughnessMap`) — regla `(?:_?map)?` de NN — y normalizar ESPACIOS como separador además de `_-.`.
5. **Matriz de verificación: los ID strings exactos** para cotejar lo que emita GraphDescription (todos confirmados idénticos en 2 o 3 implementaciones vivas sobre C4D 2026): nodespace `com.redshift3d.redshift4c4d.class.nodespace`; nodos `…nodes.core.standardmaterial / texturesampler / bumpmap / displacement / triplanar / rsmathinv / rscolorlayer / rscolorsplitter / sprite` y `…node.output`; puertos clave: `texturesampler.tex0` (GRUPO → hijos `path`, `colorspace`), `texturesampler.outcolor`, `bumpmap.input/.out/.inputtype(1=tangent normal, 0=height field)/.flipy`, `displacement.texmap/.out`, `node.output.surface/.displacement`, standard `base_color/refl_roughness/refl_isglossiness/metalness/refl_color/refl_weight/opacity_color/emission_color/emission_weight/bump_input/outcolor`. Colorspace = string `"RS_INPUT_COLORSPACE_RAW"` / `"RS_INPUT_COLORSPACE_SRGB"` (poner AMBOS explícitos, como TexToMatO — no confiar en el default "auto").
6. **Gotcha de path**: si el writer acaba pasando `maxon.Url`, construirla a mano (`"file:///" + path.replace("\\","/")`) — `pathlib.as_uri()` rompe rutas con espacios en C4D (bug documentado en NN). Verificar qué acepta GraphDescription (string vs Url) en el spike live.
7. **Packs ORM/ARM** (`_ORM`, `_ARM`, sufijo `arm`): mínimo detectarlos y mandarlos a `ignored` con motivo `packed_orm` (hoy caerían en `no_channel` o peor, matchearían otra cosa); ideal v2: `rscolorsplitter` (`.outr/.outg/.outb`) → AO/Rough/Metal con prioridad a mapas dedicados (modelo TexToMatO).
8. **Naming de material único**: al crear N materiales, deduplicar contra el Material Manager (`name_02`…). NN lo resuelve con diálogo; nosotros, al ser server-driven, auto-sufijo + mostrarlo en el preview.
9. **Layout de nodos**: confirmar en el spike que GraphDescription posiciona solo; si no, plan B = `net.maxon.node.base.xpos/ypos` (maxon.Vector) + títulos `net.maxon.node.attribute.title` — jamás depender de `CallCommand(465002363)` (solo funciona con el editor abierto). Un grafo con todo apilado en (0,0) sería percibido como roto.
10. **Feature-probing por asset repository**: `FindLatestAsset(maxon.AssetTypes.NodeTemplate(), maxon.Id(node_id)).IsPopulated()` como test de disponibilidad de un tipo de nodo (así detecta NN OpenPBR y UV Context) — útil para `redshift_unavailable` fino y para degradar honesto si algún nodo no existe en la versión de RS instalada.
11. **Extensiones**: añadir `tx` (mipmapped, común en packs) y opcionalmente `dds`/`psd` a la allowlist del spec (hoy: jpg/jpeg/png/tif/tiff/exr/hdr/tga/bmp/webp).
12. **Anotar deuda/futuro** (no v1.32): (a) AO conectado por color-layer multiply es el default de TODO el mercado — mantener nuestra decisión "creado sin conectar" pero anotarla como toggle candidato de ruleset; (b) opacity como nodo Sprite (perf de cutouts); (c) UV Context Projection (`uvcontextprojection.proj_type`, output `rs_uv_context`) = triplanar/tiling centralizado en RS 2026.2+, el camino moderno si algún día añadimos triplanar; (d) `custom_regex.json` de TexToMatO como precedente de tabla de sufijos extensible vía `sentinel_rules.json`; (e) "Import from base" (derivar set desde un material existente); (f) mid-level 0.5 para height 16-bit int — nadie lo resuelve, si lo hacemos que sea vía metadata de `imagemeta.py` (bit depth) y sería único en el mercado.
13. **Licencias — qué podemos tomar de cada uno**: Node Ninja y RS Node Tools sin licencia → solo hechos (IDs, valores, orden de tablas), cero código. TexToMatO ©-all-rights-reserved → ídem. Salad declara MIT (DunHou) pero llega embebido en un producto propietario y su upstream (renderEngine clonado) no trae LICENSE → tratar también como referencia-solo, que además es lo que ya manda el CLAUDE.md. Nuestro motor puro + GraphDescription hace que no necesitemos copiar nada.
