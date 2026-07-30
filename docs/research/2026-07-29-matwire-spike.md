# Spike live: recipe de construcción de grafos RS para matwire (v1.32, Task 2)

**Fecha**: 2026-07-29 · **C4D**: 2026.303 (live, vía MCP `exec_python`) · **Redshift node space**: `com.redshift3d.redshift4c4d.class.nodespace`
**Veredicto**: **GraphDescription puro cubre TODO el spec** — no hace falta ni un solo paso imperativo `GraphNode`+`BeginTransaction` para el wiring (solo para las posiciones de nodo, un `SetValue` trivial). Todos los items del checklist terminaron **VERIFIED** con read-back en el C4D vivo; ningún FAILED.

**Fix pass (2026-07-29, segunda sesión live tras review)**: cierra los huecos señalados — emission/metalness **wired-tested** de verdad (§2b), estado honesto de los canales extrapolados y de `rsmathinv` (§2b), y la **decisión** de vía de creación/undo con evidencia (§8: material-handle es el default del writer). Mismo protocolo: doc throwaway `SENTINEL_MATWIRE_SPIKE_FIX`, kill al final, doc del usuario verificado intacto (5 materiales originales, cero residuo).

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

### 2b. Cobertura de wiring por canal — qué se probó CONECTADO de verdad (fix pass)

El snippet de §2 solo cablea base_color/bump/roughness/displacement; emission y metalness iban como literal o extrapolados. Probe adicional en vivo (material nuevo `spikefix_emit`, mismo patrón de dict): sampler → `emission_color` **y** literal `emission_weight = 1.0` en el MISMO scope, más sampler → `metalness`, en un único ApplyDescription. Read-back literal:

```
census: {texturesampler: 2, output: 1, standardmaterial: 1}
emission_color <- texturesampler.outcolor
metalness      <- texturesampler.outcolor
emission_weight <- (sin conexión)  · GetPortValue() = maxon.Float64(1)   ← literal + sampler conviven en el mismo scope
sampler tex0/path: "/tmp/spike tex/emissive map.png", "/tmp/spike tex/metal map.png" (byte-idénticos, espacios OK)
```

**Estado por canal del spec** (honesto, tras el fix pass):

- **VERIFIED — wired-tested en vivo**: `base_color`, `bump_input` (+ `bumpmap.input`), `refl_roughness`, `displacement.texmap` (§2), `emission_color` + literal `emission_weight` en el mismo scope, `metalness` (§2b).
- **Extrapolados, mismo patrón — NO wired-tested independientemente**: `refl_color` (specular) y `opacity_color`. Ambos existen como inputs en el dump del nodo vivo (§3) y usarían la clave-sampler idéntica, pero nadie les conectó un sampler en vivo.
- **`rsmathinv`: NO confirmado y sin uso por diseño** — el spec resuelve glossiness con `refl_isglossiness = True` sobre `refl_roughness` (verificado §2); `rsmathinv` (invertir el mapa) era un fallback muerto. Ni su id de nodo ni sus puertos se probaron en vivo: si alguna vez se necesitara, verificar primero.

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

## 8. Creación del material + undo — DECISIÓN (fix pass live)

**Default del writer: la vía material-handle.** Es la que garantiza el ancla de undo Y el cleanup por-set en fallo, porque tienes la referencia al material en la mano desde el primer instante:

```python
doc.StartUndo()                                   # (en matwire lo posee el caller, alrededor del LOTE)
mat = c4d.BaseMaterial(c4d.Mmaterial)             # GetType() == 5703 — el "RS Node Material" moderno
mat.SetName(name)
doc.InsertMaterial(mat)
doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, mat)             # DESPUÉS de insertar (contrato de NEWOBJ)
doc.AddUndo(c4d.UNDOTYPE_CHANGE, mat)             # ancla: la transacción maxon del Apply se UNE a este paso (lección v1.5.7)
graph = maxon.GraphDescription.GetGraph(mat, nodeSpaceId=maxon.NodeSpaceIdentifiers.RedshiftMaterial)
maxon.GraphDescription.ApplyDescription(graph, desc)
doc.EndUndo()
```

Evidencia live (2026.303, doc throwaway `SENTINEL_MATWIRE_SPIKE_FIX`):

- **(a) Cómo se crea y cómo se obtiene el grafo con handle** — re-ejecutado en esta sesión: `BaseMaterial(c4d.Mmaterial)` (`mat_type: 5703`) + `InsertMaterial` + `GetGraph(mat, nodeSpaceId=…)` nodifica el material y devuelve su grafo: read-back `hasspace_rs: true` (`com.redshift3d.redshift4c4d.class.nodespace`) y el ApplyDescription posterior construyó `{output: 1, standardmaterial: 1, texturesampler: 1}` con `base_color` cableado. La afirmación previa de este § era correcta; ahora con evidencia pegada.
- **(b) UN undo elimina el material** — con la secuencia de arriba (ambos `AddUndo`), un solo `doc.DoUndo()` desde una llamada fresca devolvió el census de materiales al baseline (`spikefix_anchor` desapareció, material + grafo de una vez: `{"i": 0, "ok": true, "mats": [sin spikefix_anchor]}`). **Sin** el ancla `UNDOTYPE_CHANGE` hicieron falta DOS pasos de undo (la transacción maxon del Apply quedó como paso propio) — el ancla es obligatoria, no decorativa. **Caveat**: `doc.DoUndo()` desde script es orientativo (lección v1.5.7: no es proxy fiel de Cmd+Z; ejecutado en el mismo frame que el build ni siquiera surte efecto visible — se observó en vivo). La confirmación final es Cmd+Z real vía menú Edit en la verificación live de Task 3/4.
- **(c) Cleanup por-set en fallo** — con el handle, `mat.Remove()` saca el material del doc: census 3 → 2, el material eliminado ya no aparece en el listado. Verificado también tras nodificar (`GetGraph(mat)` ya llamado).

**Vía alternativa (DEMOVIDA a código de spike/prueba)**: `GetGraph(name=…, nodeSpaceId=…)` crea material+grafo de una vez **en el documento activo** y con ese nombre (verificado — §2 la usó), pero **no devuelve el material**: sin handle no hay `AddUndo` anclado, no hay `mat.Remove()` de cleanup, y habría que re-localizar el material a posteriori. El writer NO la usa.

**Lookup grafo→material** (por si algún código acaba con solo el grafo en la mano): escanear `doc.GetFirstMaterial()`…`GetNext()` comparando `m.GetNodeMaterialReference().GetGraph("com.redshift3d.redshift4c4d.class.nodespace") == graph` — la **igualdad de grafos funciona** y encontró el material correcto en vivo (`graph_to_material_lookup: "spikefix_lookup"`). En el writer no hace falta nunca: la vía material-handle tiene el material desde el principio (media razón de la decisión).

## 9. Qué NO necesitó fallback imperativo

Grupo tex0 con hijos, bool ports (`refl_isglossiness`, `flipy`), enum int (`inputtype`), float literal (`emission_weight`), puerto displacement del nodo Output, nodo suelto sin conexiones: **todo expresable en GraphDescription**. El único `GraphNode` imperativo de la receta es el `SetValue` de xpos/ypos (§6) y la lectura de verificación.

---

## Receta para `matwire_c4d.py` (Task 3 — seguir verbatim)

1. `redshift_available()`: probe §7 (`GetUserPrefsRepository` + `FindLatestAsset` + `IsNullValue()`), try/except → False.
2. `create_material_for_set(doc, folder, tex_set, name)` — **vía material-handle (DECIDIDO, §8)**:
   a. `mat = c4d.BaseMaterial(c4d.Mmaterial)` → `mat.SetName(name)` (nombre ya dedupeado) → `doc.InsertMaterial(mat)` → `doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, mat)` → `doc.AddUndo(c4d.UNDOTYPE_CHANGE, mat)` (ancla de la transacción maxon — sin ella el Apply es un paso de undo aparte, §8b) → `graph = maxon.GraphDescription.GetGraph(mat, nodeSpaceId=maxon.NodeSpaceIdentifiers.RedshiftMaterial)`. **No** usar `GetGraph(name=…)`: no devuelve el material → sin ancla de undo ni cleanup (§8, demovida).
   b. Montar UN dict de descripción (§2) desde `tex_set["channels"]`: siempre `output` + `standardmaterial`; por canal presente añadir su clave (basecolor→`base_color` srgb; roughness→`refl_roughness` raw; metalness→`metalness` raw [wired-tested §2b]; normal→sub-scope bumpmap con `inputtype=1` (+`flipy=True` si `normal_flipy`); height→scope displacement colgado de `#<…output.displacement`; opacity→`opacity_color` raw [extrapolado §2b]; emission→`emission_color` srgb **+ literal `emission_weight: 1.0`** [wired-tested juntos en el mismo scope, §2b]; specular→`refl_color` raw [extrapolado §2b]; glossiness→`refl_roughness` raw **+ literal `refl_isglossiness: True`**). Rutas = `os.path.join(folder, filename)` como **str plano** (§4).
   c. `ApplyDescription(graph, desc)` — transaccional todo-o-nada.
   d. Si hay AO: segundo `ApplyDescription` con el sampler suelto (§5).
   e. Posiciones: una transacción, `SetValue("net.maxon.node.base.xpos"/"ypos", maxon.Float(...))` por nodo (§6), localizando por assetid + `tex0/path`.
   f. Excepción en cualquier paso posterior a la inserción → `mat.Remove()` (verificado §8c) y `{"ok": False, "error": str(e)}`; el lote sigue con el siguiente set.
3. El caller (op `matwire_create`) posee `StartUndo/EndUndo` alrededor del LOTE completo; los `AddUndo` por material se anidan dentro → un Cmd+Z revierte el lote entero.

Gotchas en una línea: `#<` para puertos y `/` para hijos de grupo (§1) · colorspaces SIEMPRE explícitos (`RS_INPUT_COLORSPACE_SRGB|RAW`) · nunca `pathlib.as_uri()` · nunca `IsPopulated()`/`bool()` en el probe (§7) · nunca `CallCommand` de arrange · `AddUndo(CHANGE, mat)` SIEMPRE antes del primer toque al grafo (§8b) · `rsmathinv` no confirmado, no usar sin verificar (§2b).

---

## Mini-spike v1.32.1: rscolorsplitter

**Fecha**: 2026-07-30 · **C4D**: 2026.303 (live, MCP `exec_python`) · doc throwaway `SENTINEL_ORM_SPIKE` (killed al final; doc del usuario `matwire_verify` verificado intacto, sus 7 materiales originales).

**Pregunta crítica**: ¿puede GraphDescription expresar UN splitter alimentando DOS puertos destino? **NO** — veredicto: la vía del writer para el splitter es **segundo ApplyDescription aislado + connects imperativos en una transacción** (recetas abajo, todas wired-tested).

### A. Puertos del nodo — confirmados por dump del nodo vivo

Asset `com.redshift3d.redshift4c4d.nodes.core.rscolorsplitter` existe (`FindLatestAsset(...).IsNullValue() == False`). Ports leídos del nodo creado:

```
inputs:  ['…rscolorsplitter.input']
outputs: ['…rscolorsplitter.outr', '…outg', '…outb', '…outa']   ← también hay outa
```

### B. Selección de puerto de salida declarativa — la sintaxis que FUNCIONA es `-> #>` + id COMPLETO

Para conectar un scope hijo por un output que no es el default, la clave lleva sufijo ` -> #>` + id completo del puerto de salida:

```python
SM + "refl_roughness -> #>" + S + "rscolorsplitter.outg": splitter_scope   # OK — read-back: refl_roughness <- rscolorsplitter.outg
```

Formas que **FALLAN** (error `is not associated with any IDs`): `-> #<full-id>` sin `>` (se interpreta contra el nodo output), `-> outg` pelado, `->outg` sin espacios, `-> #>outg` corto (el `#>` exige id completo), `-> #outg`.

### C. Compartir el splitter entre DOS puertos — NO expresable declarativamente (3 vías probadas, las 3 fallan)

1. **Dos dicts anidados idénticos** (uno bajo `refl_roughness -> #>outg`, otro bajo `metalness -> #>outb`): census `{rscolorsplitter: 2, texturesampler: 2}` — **duplica** splitter Y sampler.
2. **El MISMO objeto dict Python en ambas claves**: idéntico resultado — census 2/2 (la identidad de instancia no dedupea).
3. **`$id`/`$ref`**: `{"$ref": "split1"}` → `Missing node type declaration` (no existe mecanismo de referencia; los ejemplos oficiales del SDK solo usan `$type`).

Bonus descartado: **dos ApplyDescription terminales** (2º apply con `metalness -> #>outb`) — peor aún: duplica hasta el output y el standardmaterial (census `{standardmaterial: 2, output: 2, rscolorsplitter: 2}`). Un apply terminal NO matchea contra el grafo existente. (El caso AO §5 no duplica porque su scope raíz es un sampler aislado, no el terminal.)

### D. Receta imperativa — VERIFIED (la que usa el writer)

```python
# 1) apply principal SIN splitter; 2) apply aislado splitter+sampler (patrón AO §5):
maxon.GraphDescription.ApplyDescription(graph, {
    "$type": "#" + S + "rscolorsplitter",
    "#<" + S + "rscolorsplitter.input": sampler(orm_path, "RS_INPUT_COLORSPACE_RAW"),
})
# 3) localizar splitter + standardmaterial por assetid (GetInnerNodes, §6) y conectar:
with graph.BeginTransaction() as tr:
    split_node.GetOutputs().FindChild(S + "rscolorsplitter.outg").Connect(
        sm_node.GetInputs().FindChild(S + "standardmaterial.refl_roughness"))
    split_node.GetOutputs().FindChild(S + "rscolorsplitter.outb").Connect(
        sm_node.GetInputs().FindChild(S + "standardmaterial.metalness"))
    tr.Commit()
```

Read-back tras la receta completa (material `spike_imperative`):

```
census: {standardmaterial: 1, texturesampler: 2, output: 1, rscolorsplitter: 1}   ← UN splitter, cero duplicación
refl_roughness <- rscolorsplitter.outg
metalness      <- rscolorsplitter.outb
splitter.input <- texturesampler.outcolor
outr outgoing conns: 0                                                            ← AO libre, jamás conectado
```

**Decisión del writer**: vía imperativa SIEMPRE que el splitter exista (1 o 2 connects — un solo code path, la lista de pares varía); la forma declarativa `-> #>` (§B) queda documentada pero sin uso (solo cubriría el caso de un único output y bifurcaría la receta). Si AMBOS mapas dedicados existen, el splitter no contribuiría nada (outr nunca se conecta) → **no se crea** (skip total, decisión de juicio anotada).

**Honestidad (review M2)**: el Cmd+Z del recipe imperativo (transacción de Connects bajo el anchor CHANGE) NO se ejercitó en este mini-spike — queda en la checklist live de v1.32.1 junto con la verificación visual del layout en columnas (el bug del Pair en `_layout_nodes` significa que el layout de v1.32 nunca se vio funcionando). **Ajuste post-review (M1)**: con roughness+metalness dedicados el plan ya no se omite — degrada a un sampler ORM suelto sin conectar (filosofía AO/leftover: los archivos reconocidos nunca desaparecen en silencio); `_apply_orm_plan` retorna antes del lookup cuando `connects` está vacío.

---

## Corrección v1.32.1 (live, lote > 1 material)

**⚠️ LA RECETA DE UNDO DEL §8 (y del punto 2.a/2.f/3 de "Receta para `matwire_c4d.py`") ES INCORRECTA PARA LOTES.** Lo que sigue la reemplaza. No re-derives la anterior.

**Fecha**: 2026-07-30 · **C4D**: 2026.303 (live, MCP `exec_python`) · reportado por el usuario en producción.

**Síntoma**: crear 2 materiales pedía **4+ Cmd+Z** y aun así no dejaba la escena limpia. El contrato "un Cmd+Z revierte el lote" estaba roto.

**Causa raíz**: las transacciones maxon que corren sobre un material **YA INSERTADO** en el documento (`ApplyDescription`, la transacción de `Connect` del ORM, la transacción de `SetValue` del layout) generan **cada una su propio paso de undo de documento**. El ancla `AddUndo(UNDOTYPE_CHANGE, mat)` del §8b solo hacía que se uniera la transacción de **UN** material — por eso el spike de un solo material (§8b) pasó y el bug se coló hasta producción. Es la limitación real del ancla, no una regresión del writer.

**Fix**: construir **TODO el grafo sobre un `BaseMaterial` AÚN NO INSERTADO** y insertar al final. `maxon.GraphDescription.GetGraph(mat, nodeSpaceId=…)` funciona perfectamente sobre un material fuera del documento (verificado). Así el documento solo ve N inserciones dentro del `StartUndo`/`EndUndo` del lote → **UN** paso de undo.

```python
doc.StartUndo()                                   # el caller, alrededor del LOTE
for name, desc in jobs:
    mat = c4d.BaseMaterial(c4d.Mmaterial)
    mat.SetName(name)
    graph = maxon.GraphDescription.GetGraph(       # OK fuera del documento
        mat, nodeSpaceId=maxon.NodeSpaceIdentifiers.RedshiftMaterial)
    maxon.GraphDescription.ApplyDescription(graph, desc)
    ...  # ORM connects, AO, leftovers, layout — TODO aquí, sin doc
    doc.InsertMaterial(mat)                        # ÚLTIMO paso
    doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, mat)          # DESPUÉS de insertar
doc.EndUndo()
```

Prueba live del coordinador (2 materiales, doc throwaway):

```
mats: ['spikeB','spikeA'];  undo #1 -> 0 materiales   (UN paso, ambos fuera)
```

Verificación del writer real (op `panel/tools/matwire_create`, 2 sets, doc throwaway con `SetDocumentPath` al folder del ruleset):

```
op_result: {'ok': True, 'created': 2, 'materials': ['plaster','wood'], 'errors': []}
census:    plaster {output, standardmaterial, bumpmap, texturesampler x3}   cols 300/0/-300/-600
           wood    {output, standardmaterial, texturesampler x2}            cols 300/0/-600
conns:     plaster base_color=1, refl_roughness=1, bump_input=1
           wood    base_color=1, refl_roughness=1, bump_input=0
undo_steps_to_zero: 1   (0 materiales restantes)
```

**Corolarios que cambian el §8:**

- El ancla `AddUndo(c4d.UNDOTYPE_CHANGE, mat)` **ya no se usa** — su único propósito era hacer que la transacción se uniera, y build-before-insert lo vuelve innecesario. Mantenerlo sería ruido.
- El **cleanup por fallo (§8c) desaparece**: como la inserción es el ÚLTIMO paso, cualquier excepción ocurre con el material FUERA del documento — no hay nada que quitar, ni registro `NEWOBJ` que balancear con un `UNDOTYPE_DELETE`. El writer solo reporta el error y el lote sigue. (`mat.Remove()` sigue siendo válido como API; simplemente ya no hay caso donde haga falta aquí.)
- Lo demás del §8 sigue en pie: `BaseMaterial(c4d.Mmaterial)` (type 5703), handle-sí / `GetGraph(name=…)`-no, `AddUndo(NEWOBJ)` DESPUÉS de insertar.
