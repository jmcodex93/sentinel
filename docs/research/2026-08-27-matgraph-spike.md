# Spike Material Graph — colorspace port, conexiones, borrado+undo

- **Fecha:** 2026-08-27 · **Entorno:** C4D 2026.304, Redshift, macOS. Scripts throwaway vía Script Manager (el `exec_python` del bridge MCP estaba deshabilitado y la memoria del Wrangler manda verificar con C4D real, no vía bridge). Documentos `BaseDocument()` + `InsertBaseDocument` + `KillDocument` en `finally` — cero residuo.
- **Para:** spec `docs/superpowers/specs/2026-08-25-material-graph-qc-design.md` (QC #13 RS Colorspace + Tools Clean Dead Nodes).

## Q1 — vocabulario del puerto `tex0/colorspace`

- **El valor por defecto ("auto") es un puerto SIN valor**: `GetPortValue()` → `None`, `GetDefaultValue()` → `None`. NO existe un string `RS_INPUT_COLORSPACE_AUTO` almacenado. Para el motor: `assigned_cs=None` ⇔ auto.
- `RS_INPUT_COLORSPACE_SRGB` y `RS_INPUT_COLORSPACE_RAW` se escriben y releen **verbatim** (los dos valores que matwire committea en producción).
- **⚠ CRASH MEDIDO (la lección cara del spike): escribir strings fuera del vocabulario en ese puerto tumba C4D entero** — `EXC_BAD_ACCESS` con el hilo caído en `redshift4c4d.xlib` (run 2 escribía `totally_bogus_value_xyz`, strings estilo OCIO, etc.). **Regla para el writer del Fix: SOLO se escriben `RS_INPUT_COLORSPACE_SRGB`/`RAW`, jamás un valor derivado dinámicamente.** Y no hace falta enumerar el combo: por diseño, cualquier string desconocido leído es `foreign_cs` → Info.

## Q2 — ¿es legible a qué resuelve el auto?

**NO.** Dump completo de los hijos de `tex0` (`path, frameend, framestart, colorspace, layerset, framerate, animation, timing, rangestart, rangeend, loops, startoffset`) y de los 22 puertos top-level del sampler: no existe ningún puerto de "resolved colorspace". **Consecuencia de diseño: la rama «auto que resuelve MAL» del check A es inalcanzable** — auto (None) cae SIEMPRE a la fila Info «auto, sin verificar», nunca a violación. La decisión 3 del brainstorm queda en su fallback.

## Q3 — lectura del grafo (nodos, puertos, conexiones)

- Enumeración de nodos: `graph.GetViewRoot().GetInnerNodes(mask=maxon.NODE_KIND.NODE, includeThis=False)` (el idiom de matwire).
- **Los hijos de `GetInputs()`/`GetOutputs()` llevan IDs COMPLETOS** (`com...texturesampler.tex0`), así que `FindChild("tex0")` con nombre corto devuelve null (medido en run 1 — la nota de arquitectura de textures.py, reconfirmada). PERO los hijos de `tex0` llevan ids CORTOS (`path`, `colorspace`). Lookup robusto: matching por SUFIJO de `str(GetId())` en ambos niveles.
- **Conexiones**: `out_port.GetConnections(maxon.PORT_DIR.OUTPUT, lista)` (idiom oficial del SDK, `nodegraph_selection_r26.py`) funciona y el destino llega con nodo y puerto legibles: `standardmaterial@VkO2...<com...standardmaterial.refl_roughness` — suficiente para la inferencia por puerto destino Y para las aristas del reachability. Sampler muerto → lista vacía, `api_result: True` (lista vacía NO es error).
- Assetid de nodo: `str(node.GetValue("net.maxon.node.attribute.assetid") or "")`, matching por substring (idiom matwire).

## Q4 — borrado de nodo + undo (lo único destructivo)

- Borrado: `victim.Remove()` dentro de `graph.BeginTransaction()`/`Commit()` — funciona (4→3 nodos).
- **Receta de undo medida y correcta**: `doc.StartUndo()` + `doc.AddUndo(UNDOTYPE_CHANGE, mat)` (ancla ANTES de la transacción) + transacción con el Remove + `doc.EndUndo()` → **UNA pulsación de `CallCommand(12105)` restaura el nodo**.
- **La trampa que casi la da por rota**: las DOS primeras mediciones (spike v3 y las tres variantes de q4) reportaron «el undo no restaura» porque contaban nodos a través del **graph handle capturado antes del undo — que sigue mintiendo el estado viejo sin error alguno**. La lección documentada del spike de Variants («C4D reemplaza el objeto al restaurar; re-busca siempre») aplica también al grafo: **toda lectura post-undo debe re-adquirir doc → material → `GetGraph()` frescos**. Medido en q4b: mismo instante, `stale_count: 3` / `fresh_count: 4`.
- Corolario para los tests del adapter: un fake que no modele el reemplazo-en-restore no puede cazar este bug; y para la verificación live, contar siempre con handles frescos.

## OCIO

`DOCUMENT_OCIO_CONFIG = "$OCIO"`, render space id `1` en 2026.304. El gate por versión pre/post-OCIO del spec queda sin objeto para el vocabulario (no lo enumeramos); el check lee strings y solo distingue SRGB/RAW/None/desconocido.

## Registro de método

- Run 1: `FindChild` con nombres cortos → todos los probes en None (diagnóstico útil: ids completos).
- Run 2: **crash de C4D** por escrituras especulativas (arriba). Reescrito a v3: solo-lectura primero, escrituras solo de valores probados, JSON incremental con marcador de `stage` para que un crash se auto-diagnostique.
- Runs 3/q4/q4b: sin crashes, resultados arriba. JSONs en el scratchpad de la sesión.
