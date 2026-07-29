# Spike live: recipe de construcción de grafos RS para matwire (v1.32, Task 2)

**Fecha**: 2026-07-29 · **C4D**: 2026.303 (live, vía MCP `exec_python`) · **Redshift node space**: `com.redshift3d.redshift4c4d.class.nodespace`
**Veredicto**: **GraphDescription puro cubre TODO el spec** — no hace falta ni un solo paso imperativo `GraphNode`+`BeginTransaction` para el wiring (solo para las posiciones de nodo, un `SetValue` trivial). Todos los items del checklist terminaron **VERIFIED** con read-back en el C4D vivo; ningún FAILED.

Metodología: documento throwaway `SENTINEL_MATWIRE_SPIKE` insertado con `c4d.documents.InsertBaseDocument` + `SetActiveDocument`, todos los materiales de prueba creados ahí, y al final `KillDocument` + reactivación del doc del usuario (verificado: su doc quedó con sus 5 materiales originales, cero residuo). Texturas dummy reales en disco **con espacios en carpeta Y archivo** (`…/matwire spike tex/plaster base BaseColor.png`).

---

## 1. La sintaxis que FUNCIONA (la trampa que costó 4 intentos)

`ApplyDescription` acepta referencias por **label** ("Standard Material", "Base/Color") o por **ID**, pero la sintaxis de ID tiene marcadores obligatorios que NO están en los ejemplos locales del SDK (están en el manual online `manual_graphdescription.html`):

- **Tipo de nodo** (`$type`): `"#<id-completo-del-nodo>"` — prefijo `#`, id completo.
- **Puerto de entrada** (clave del dict): `"#<" + <id-completo-del-puerto>` — prefijo **`#<`** (el `<` marca "input port").
- **Hijo de puerto GRUPO** (tex0): el hijo se separa con **`/`**, y el nombre del hijo va SOLO (no id completo): `"#<…texturesampler.tex0/path"`.
- Puerto de salida explícito: sintaxis `"Puerto -> outPuerto"` (no la necesitamos — el puerto default de salida de cada nodo RS es el correcto en todos nuestros casos, ver §3).

Formas que **FALLAN** (verificado en vivo, error `is not associated with any IDs`): id pelado sin `#` (se interpreta como label), `maxon.Id(...)` como clave/valor (`AttributeError`), `#id.puerto` sin el `<` para puertos, `#surface` (fragmento suelto).

El writer usará **solo IDs** (versión-estables, catálogo verificado §3); los labels quedan descartados (dependen del idioma en-US y de unicidad de etiqueta).

## 2. Receta completa — el snippet EXACTO que corrió y su read-back

```python
import c4d, maxon

S = "com.redshift3d.redshift4c4d.nodes.core."
O = "com.redshift3d.redshift4c4d.node.output"

def sampler(path, cs):  # cs: "RS_INPUT_COLORSPACE_SRGB" | "RS_INPUT_COLORSPACE_RAW"
    return {
        "$type": "#" + S + "texturesampler",
        "#<" + S + "texturesampler.tex0/path": path,          # plain str, espacios OK (§4)
        "#<" + S + "texturesampler.tex0/colorspace": cs,
    }

# GetGraph(name=...) CREA el material (nodificado RS) en el DOCUMENTO ACTIVO y devuelve su grafo.
graph = maxon.GraphDescription.GetGraph(
    name="plaster", nodeSpaceId=maxon.NodeSpaceIdentifiers.RedshiftMaterial)

maxon.GraphDescription.ApplyDescription(graph, {
    "$type": "#" + O,
    "#<" + O + ".surface": {
        "$type": "#" + S + "standardmaterial",
        "#<" + S + "standardmaterial.base_color": sampler(bc_path, "RS_INPUT_COLORSPACE_SRGB"),
        "#<" + S + "standardmaterial.bump_input": {
            "$type": "#" + S + "bumpmap",
            "#<" + S + "bumpmap.inputtype": 1,        # 1 = Tangent-Space Normal
            "#<" + S + "bumpmap.flipy": True,          # solo cuando el set es DX-only
            "#<" + S + "bumpmap.input": sampler(normal_path, "RS_INPUT_COLORSPACE_RAW"),
        },
        "#<" + S + "standardmaterial.refl_roughness": sampler(gloss_path, "RS_INPUT_COLORSPACE_RAW"),
        "#<" + S + "standardmaterial.refl_isglossiness": True,   # solo con mapa gloss
        "#<" + S + "standardmaterial.emission_weight": 1.0,      # solo con mapa emission
    },
    "#<" + O + ".displacement": {
        "$type": "#" + S + "displacement",
        "#<" + S + "displacement.texmap": sampler(height_path, "RS_INPUT_COLORSPACE_RAW"),
    },
})
```

**Read-back del grafo resultante** (iteración `graph.GetViewRoot().GetInnerNodes(mask=maxon.NODE_KIND.NODE, includeThis=False)`):

Censo de nodos: `{displacement: 1, texturesampler: 4, standardmaterial: 1, output: 1, bumpmap: 1}` — exactamente lo descrito, sin duplicados.

Conexiones (leídas con `port.GetConnections(maxon.PORT_DIR.INPUT)` → lista de `(GraphNode-puerto-origen, Wires)`):

```
standardmaterial.base_color     <- texturesampler.outcolor
standardmaterial.bump_input     <- bumpmap.out
standardmaterial.refl_roughness <- texturesampler.outcolor
bumpmap.input                   <- texturesampler.outcolor
displacement.texmap             <- texturesampler.outcolor
output.surface                  <- standardmaterial.outcolor
output.displacement             <- displacement.out
```

Valores (read-back `GetPortValue()`): `inputtype = maxon.Int32(1)`, `flipy = maxon.Bool(true)`, `refl_isglossiness = maxon.Bool(true)`, `emission_weight = maxon.Float64(1)`, `tex0/colorspace = maxon.String("RS_INPUT_COLORSPACE_SRGB"|"…RAW")` por sampler según lo descrito, `tex0/path` = la ruta con espacios byte-idéntica (§4).

Nota de dirección: la descripción se escribe del nodo TERMINAL hacia atrás (Output → material → samplers); al conectar un scope hijo a un puerto de entrada, GraphDescription elige el **puerto de salida default** del hijo — que en los 4 nodos RS que usamos es exactamente el del catálogo (`outcolor`/`out`), así que nunca necesitamos la sintaxis `->`.

## 3. Catálogo de IDs — cotejado 1:1 contra el grafo vivo

Todos los ids del Global Constraints aparecieron VERBATIM en el read-back (assetid del nodo + ids de puerto completos `nodo.puerto`):

- Nodos: `…nodes.core.standardmaterial | texturesampler | bumpmap | displacement`, `…node.output` ✓ (assetid leído: `net.maxon.node.attribute.assetid`).
- `standardmaterial`: `base_color, refl_roughness, refl_isglossiness, metalness, refl_color, refl_weight, opacity_color, emission_color, emission_weight, bump_input` como inputs y `outcolor` como único output — TODOS presentes en el dump del nodo vivo.
- `output`: inputs `surface, displacement` (además `environment, volume, light, contour, materialid, viewport, rs_uv_context`).
- `bumpmap.input/.out/.inputtype/.flipy`, `displacement.texmap/.out`, `texturesampler.tex0` (grupo con hijos `path`, `colorspace`) + `texturesampler.outcolor` ✓.

## 4. Path: string plano GANA (y la trampa `as_uri` confirmada de refilón)

- **`tex0/path` acepta un `str` plano POSIX con espacios**: se almacena como `maxon.String` byte-idéntica (sin encoding) y **C4D lo RESUELVE** — `c4d.documents.GetAllAssetsNew(doc, …, flags=c4d.ASSETDATA_FLAG_TEXTURESONLY)` devolvió `exists: True` para `…/matwire spike tex/plaster base BaseColor.png` (carpeta Y archivo con espacio). **El writer usa `os.path.join(folder, filename)` tal cual — sin Url.**
- `maxon.Url("file:///" + path.lstrip("/"))` construida A MANO también funciona (se almacena como `maxon.Url` con los espacios sin codificar, `exists: True`). Si algún día hace falta la forma Url (Windows: `"file:///" + path.replace("\\", "/")`), construirla a mano — NUNCA `pathlib.as_uri()` (percent-encodea los espacios y C4D guarda el literal codificado; bug documentado por Node Ninja, y coherente con que aquí el valor se almacena crudo sin decodificar).

## 5. Sampler AO sin conectar — segundo ApplyDescription

Un scope de nivel superior cuyo `$type` es `texturesampler` crea un nodo **aislado** (GraphDescription no exige que el scope raíz sea el nodo terminal):

```python
maxon.GraphDescription.ApplyDescription(graph, {
    "$type": "#" + S + "texturesampler",
    "#<" + S + "texturesampler.tex0/path": ao_path,
    "#<" + S + "texturesampler.tex0/colorspace": "RS_INPUT_COLORSPACE_RAW",
})
```

Read-back: censo antes `{texturesampler: 4, …}` → después `{texturesampler: 5, …}` (**+1 exacto, cero duplicación** del output/material existentes) y `outcolor.GetConnections(maxon.PORT_DIR.OUTPUT)` del nuevo sampler = `0` conexiones. Sobrevive en el grafo. **VERIFIED**.

Orden en el writer: primero el apply grande, después el del AO (dos applies sobre el mismo `graph`; cada apply es transaccional todo-o-nada por sí mismo).

## 6. Posiciones de nodo

GraphDescription **no asigna posición**: `node.GetValue("net.maxon.node.base.xpos"/"ypos")` = `None` en todos los nodos tras el apply (= sin atributo; con el editor cerrado no hay auto-place verificable). Para no arriesgar un grafo apilado en (0,0), el writer las fija explícitamente — **write verificado con read-back**:

```python
with graph.BeginTransaction() as tr:
    node.SetValue("net.maxon.node.base.xpos", maxon.Float(300.0))   # readback: 300
    node.SetValue("net.maxon.node.base.ypos", maxon.Float(0.0))
    tr.Commit()
```

(`maxon.Float`, NO `maxon.Vector` — el Vector de Node Ninja no llegó a probarse porque Float entró a la primera.) Layout sugerido para el writer: columnas x = samplers −600, bump/displacement −300, material 0, output 300; y = índice de canal × 220. Localizar cada nodo tras el apply por su assetid (`net.maxon.node.attribute.assetid`) y, entre samplers, por `tex0/path`. Jamás `CallCommand(465002363)` (solo funciona con el Node Editor abierto).

## 7. Probe de disponibilidad Redshift / por-nodo

Las shapes de la literatura NO existen en 2026.303 (`AssetInterface.FindLatestAsset` → `AttributeError`; `AssetDataBasesInterface.GetUserPrefsRepository` → `AttributeError`). La llamada que SÍ funciona:

```python
repo = maxon.AssetInterface.GetUserPrefsRepository()
desc = repo.FindLatestAsset(
    maxon.AssetTypes.NodeTemplate(),
    maxon.Id("com.redshift3d.redshift4c4d.nodes.core.standardmaterial"),
    maxon.Id(), maxon.ASSET_FIND_MODE.LATEST)
available = not desc.IsNullValue()
```

Evidencia: id real → `IsNullValue()=False`; id bogus (`com.bogus.does.not.exist`) → devuelve AssetDescription **sin lanzar** con `IsNullValue()=True`. **Cuidado**: `bool(desc)` es `True` en ambos casos y el objeto NO tiene `IsPopulated()` (eso vive en otro tipo) — el discriminador es **`IsNullValue()`**. Envolver en try/except igualmente (defensa ante C4D sin RS instalado, no ejercitado en esta máquina).

## 8. Creación del material — dos vías verificadas

- **Vía principal (writer)**: `maxon.GraphDescription.GetGraph(name=<nombre>, nodeSpaceId=maxon.NodeSpaceIdentifiers.RedshiftMaterial)` crea el material **en el documento activo**, con ese nombre, y devuelve el grafo (vacío, `createEmpty=True` default — la descripción crea también el nodo Output). Read-back del material: `GetType() == c4d.Mmaterial` (5703 — NO el 1036224 del RS material clásico), `GetNodeMaterialReference().HasSpace("com.redshift3d.redshift4c4d.class.nodespace") == True`. Es el "RS Node Material" moderno.
- **Vía fallback / control de undo**: crear `c4d.BaseMaterial(c4d.Mmaterial)` + `doc.InsertMaterial(mat)` y luego `maxon.GraphDescription.GetGraph(mat, nodeSpaceId=…)` — nodifica el material existente (HasSpace RS pasa a True). Verificado OK. Útil si Task 3 quiere poseer la inserción para el anchor de undo (`doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, mat)` antes de tocar el grafo).
- `GetGraph(name=…)` inserta en el **documento activo** — en el op-drain del panel eso es el doc del usuario, que es exactamente donde matwire debe crear los materiales. (En el spike se activó el doc throwaway antes de cada GetGraph por esta misma razón.)

## 9. Qué NO necesitó fallback imperativo

Grupo tex0 con hijos, bool ports (`refl_isglossiness`, `flipy`), enum int (`inputtype`), float literal (`emission_weight`), puerto displacement del nodo Output, nodo suelto sin conexiones: **todo expresable en GraphDescription**. El único `GraphNode` imperativo de la receta es el `SetValue` de xpos/ypos (§6) y la lectura de verificación.

---

## Receta para `matwire_c4d.py` (Task 3 — seguir verbatim)

1. `redshift_available()`: probe §7 (`GetUserPrefsRepository` + `FindLatestAsset` + `IsNullValue()`), try/except → False.
2. `create_material_for_set(doc, folder, tex_set, name)`:
   a. `graph = maxon.GraphDescription.GetGraph(name=name, nodeSpaceId=maxon.NodeSpaceIdentifiers.RedshiftMaterial)` (el doc activo es `doc` — los ops corren en main thread con el doc del usuario activo; el material nace ya con el nombre dedupeado).
   b. Montar UN dict de descripción (§2) desde `tex_set["channels"]`: siempre `output` + `standardmaterial`; por canal presente añadir su clave (basecolor→`base_color` srgb; roughness→`refl_roughness` raw; metalness→`metalness` raw; normal→sub-scope bumpmap con `inputtype=1` (+`flipy=True` si `normal_flipy`); height→scope displacement colgado de `#<…output.displacement`; opacity→`opacity_color` raw; emission→`emission_color` srgb **+ literal `emission_weight: 1.0`**; specular→`refl_color` raw; glossiness→`refl_roughness` raw **+ literal `refl_isglossiness: True`**). Rutas = `os.path.join(folder, filename)` como **str plano** (§4).
   c. `ApplyDescription(graph, desc)` — transaccional todo-o-nada.
   d. Si hay AO: segundo `ApplyDescription` con el sampler suelto (§5).
   e. Posiciones: una transacción, `SetValue("net.maxon.node.base.xpos"/"ypos", maxon.Float(...))` por nodo (§6), localizando por assetid + `tex0/path`.
   f. Excepción en cualquier paso → `{"ok": False, "error": str(e)}`; el material a medias se elimina (`doc.GetActiveDocument`… el caller decide; con ApplyDescription atómico el caso realista es material vacío → borrarlo).
3. El caller (op `matwire_create`) posee `StartUndo/EndUndo` alrededor del LOTE completo.

Gotchas en una línea: `#<` para puertos y `/` para hijos de grupo (§1) · colorspaces SIEMPRE explícitos (`RS_INPUT_COLORSPACE_SRGB|RAW`) · nunca `pathlib.as_uri()` · nunca `IsPopulated()`/`bool()` en el probe (§7) · nunca `CallCommand` de arrange · `GetGraph(name=…)` escribe en el doc ACTIVO.
