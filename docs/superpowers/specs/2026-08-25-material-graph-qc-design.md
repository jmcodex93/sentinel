# Material Graph QC — colorspace audit + nodos muertos (2 checks nuevos)

- **Fecha:** 2026-08-25
- **Origen:** spike Wrangler (`Node Wrangler/docs/spikes/2026-08-25-wrangler-spike.md`). Veredicto: el Wrangler standalone es NO-GO (Render Flow de Boghma ocupa la autoría), pero la **auditoría** de grafos de materiales RS es territorio Sentinel y nadie la tiene: Render Flow/NodeFlow asigna colorspace *al crear*; nadie audita *lo ya existente* (material de Gumroad, heredado, hecho a mano).
- **Posicionamiento:** refuerza el claim "el único preflight de render de C4D". Auditoría, NO autoría — cero hotkeys, cero insert interactivo, cero solo/preview (eso quedó descartado explícitamente).

---

## Check A — "RS Colorspace" (auditoría de colorspace en materiales Redshift)

### Goal
Nuevo check QC (nº 13/14 según orden con el QC de assets del estándar) que recorre **cada Texture Sampler de cada material RS node-based** del documento y compara el colorspace asignado en el puerto contra el que el canal debería tener según el nombre del fichero. Mismatch típico que caza: roughness/normal/metalness/displacement marcados **sRGB** (render incorrecto, la trampa ACEScg del spike), o basecolor/emission en **Raw** (lavado). Botones: **Select** (ciclar materiales infractores) / **Info** (detalle por textura: canal inferido, asignado, esperado, y el porqué) / **Fix** (corregir el colorspace de todos los infractores).

### Constraints
1. **Single source de verdad = MatWire.** El canal se infiere con el motor existente (`matwire._match_channel` + tablas `_CHANNEL_VARIANTS`) y el colorspace esperado con `matwire.channel_colorspace` (extendida si hace falta, nunca duplicada). Si MatWire cambia su tabla, el check cambia con ella — una sola tabla en todo Sentinel.
2. **Motor puro primero** (doctrina del repo): `plugin/sentinel/checks/` gana un módulo puro testeable sin `import c4d` con la firma aproximada `audit_colorspaces(entries) -> verdicts`, donde `entries = [(material, filename, assigned_cs)]` y `verdicts` clasifica `ok | mismatch | unknown`. La capa c4d solo recolecta entries y aplica fixes.
3. **Sin falsos positivos por diseño:** canal no reconocido por MatWire → `unknown` → el check **no opina** (ni warning ni fix). Packed ORM/ARM → raw. Igual para colorspaces no estándar (OCIO custom): si `assigned_cs` no es uno de los valores conocidos del combo RS, reportar como `info`, no como fallo.
4. **Recolección:** reutilizar el patrón de escaneo recursivo de puertos maxon que ya usa el check Assets — vive en **`sentinel/textures.py`** (`scan_all_texture_paths`, el walk de GraphNodes que lee los puertos de los Texture Samplers; `assets.py` es el motor puro de merge/clasificación y no toca el grafo). Mismo walk, leyendo además el puerto de colorspace del Texture Sampler. No introducir dependencia de la lib Boghma `renderEngine` para esto — el patrón propio ya existe (y su propio walk tuvo bugs hasta 2026-08: `GetConnectedPorts` devolvía siempre `None` por un `or` que debía ser `and`).
5. **Los valores reales del combo RS** (los strings que acepta el puerto colorspace) se descubren en vivo y quedan en el módulo c4d con comentario de procedencia; ojo divergencia pre/post-OCIO obligatorio (2025.2+) — gate por versión si difieren.
6. **Fix undo-safe:** un solo paso de undo por pulsación de Fix (todos los puertos corregidos dentro de una transacción + `StartUndo/AddUndo(UNDOTYPE_CHANGE, mat)/EndUndo`, patrón confirmado en el spike §2). El Fix nunca corre solo: opt-in por click, como el resto de checks.
7. Materiales no-RS / no node-based: se ignoran en silencio (mismo comportamiento que Assets).
8. **Evidencia de done:** tests del motor puro (mismatch sRGB-en-roughness, Raw-en-basecolor, unknown, ORM) + ciclo live en C4D 2026: material con roughness en sRGB → check rojo → Fix → check verde → undo → rojo otra vez.

### Referencias
- `plugin/sentinel/matwire.py` (tablas de canal + `channel_colorspace`) y `matwire_c4d.py::_rs_colorspace` (cómo se escribe al crear — el Fix escribe por la misma vía).
- `plugin/sentinel/textures.py` (walk maxon de puertos RS existente, `scan_all_texture_paths`).
- Spike Wrangler §6 (trampa ACEScg, con fuentes) y `Node Wrangler/spikes/wrangler/live_probe_log.md` (ids de nodo RS confirmados en vivo, p.ej. `...nodes.core.texturesampler`).

---

## Check B — "RS Dead Nodes" (nodos aislados en grafos Redshift)

### Goal
Check QC que detecta, por cada material RS node-based, los **nodos sin camino al nodo Output** (basura acumulada de lookdev: samplers colgando, ramas muertas, restos de pruebas). Es el hermano dentro-del-grafo del check "Unused Materials". Botones: **Select** (ciclar materiales con basura) / **Info** (cuántos nodos muertos y cuáles) / **Fix** (borrarlos, undo 1 paso).

### Constraints
1. **Motor puro de alcanzabilidad:** módulo testeable sin `import c4d` con firma aproximada `find_dead_nodes(nodes, edges, roots) -> dead_ids`. La capa c4d solo extrae la lista de nodos/aristas del grafo maxon y pasa los roots.
2. **Roots = TODOS los puertos del Output** (Surface, Displacement, Volume, …), no solo Surface — un árbol de displacement válido no es basura.
3. **Sinks legítimos NO son basura:** `StoreColorToAOV` / `StoreScalarToAOV` / `StoreIntegerToAOV` y sus aguas-arriba cuentan como vivos aunque no lleguen al Output (escriben a AOVs — integra con el conocimiento AOV que Sentinel ya tiene). Lista de sink-assets excluidos en el motor puro, con test propio.
4. **Conservador por defecto:** ante cualquier asset-id desconocido que actúe de sink potencial, o error leyendo el grafo, el material se reporta `info`, nunca `fix`. Borrar solo lo demostrablemente inalcanzable.
5. **Fix undo-safe** (idéntico patrón al Check A) y opt-in. Nunca auto-fix.
6. Performance: un solo walk por material; sin límite artificial de nodos, pero el walk es O(nodos+aristas) y no relee el grafo por nodo (lección del bridge MCP: cada llamada al grafo cuesta).
7. **Evidencia de done:** tests del motor puro (cadena viva, isla muerta, rama de displacement, sink AOV, grafo vacío) + ciclo live: material con 3 nodos basura → rojo → Fix → verde → undo.

### Referencias
- Estudio de mercado: RsMat Clean (Boghma, free, Windows-only) hace esto standalone — **estudio de comportamiento solamente, cero código** (misma política que `docs/research/2026-07-29-matwire-implementations.md`).
- `renderEngine/utils/node_helper.py::RemoveIsolateNodes` (lib de Boghma, en `99 - CODEX/11 C4D DEV/renderEngine`, actualizada 2026-08-25; MIT declarado en `__init__.py`, sin archivo LICENSE en raíz) — **prior art del gesto, NO el algoritmo** (verificado leyendo la implementación 2026-08-26): solo borra nodos con **cero conexiones** (`IsNodeConnected`), no hace reachability desde el Output — una isla muerta (nodos cableados entre sí pero sin camino al Output) sobrevive, y tampoco distingue sinks AOV. La reachability propia del motor puro (`find_dead_nodes` con roots en todos los puertos del Output) es estrictamente más fuerte; no adoptar su enfoque como atajo.
- Memoria del proyecto Wrangler: `c4d-mcp-bridge-graph-limits` (por qué se verifica con plugin real, no vía MCP).

---

## Compartido / orden de trabajo

- Ambos checks comparten la recolección del grafo (un walk por material alimenta a los dos) — implementar la recolección una vez.
- Orden sugerido: **A primero** (más valor, menos riesgo de borrado), B después reutilizando el walk.
- UI: entran en el StatusArea como los 12 existentes, con el patrón Select/Info/Fix data-driven de Fase 2. Naming visible sugerido: **"RS Colorspace"** y **"RS Dead Nodes"** (grupo mental "Material Graph QC").
- Estimación (del spike, con la fontanería ya en repo): A ≈ 2–4 días, B ≈ 1–2 días.
- Fuera de alcance explícito: cualquier función de autoría (insert de nodos, auto-wire interactivo, solo/preview, hotkeys). Si alguien lo propone, la respuesta vive en el spike del Wrangler §12: eso es Render Flow, y no competimos ahí.
