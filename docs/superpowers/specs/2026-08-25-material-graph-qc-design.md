# Material Graph QC — colorspace audit + nodos muertos (2 checks nuevos)

- **Fecha:** 2026-08-25 (borrador del spike) · **2026-08-26: diseño aprobado en brainstorm, pendiente de plan.**
- **Origen:** spike Wrangler (`Node Wrangler/docs/spikes/2026-08-25-wrangler-spike.md`). Veredicto: el Wrangler standalone es NO-GO (Render Flow de Boghma ocupa la autoría), pero la **auditoría** de grafos de materiales RS es territorio Sentinel y nadie la tiene: Render Flow/NodeFlow asigna colorspace *al crear*; nadie audita *lo ya existente* (material de Gumroad, heredado, hecho a mano).
- **Posicionamiento:** refuerza el claim "el único preflight de render de C4D". Auditoría, NO autoría — cero hotkeys, cero insert interactivo, cero solo/preview (descartado explícitamente; ver Fuera de alcance).

## Decisiones cerradas en brainstorm (2026-08-26)

1. **Severidad y defaults**: A (`rs_colorspace`) = **FAIL**, B (`rs_dead_nodes`) = **WARN**; **ambos ON por defecto**. Un colorspace mal renderiza píxeles incorrectos (la trampa ACEScg) — eso es FAIL; los nodos muertos no cambian la imagen — WARN. Quien no use RS ve OK trivial. Consecuencia aceptada (lección v1.36.5): escenas viejas mostrarán violaciones nuevas de golpe — información verdadera. Severidad y on/off ajustables por proyecto con el mecanismo per-check existente del ruleset; **cero claves nuevas**.
2. **El valor "auto"** (check A): violación **solo si el auto resuelve MAL**. Si el valor resuelto es legible y coincide con lo esperado → OK; si resuelve distinto → `mismatch` con Fix a explícito; si no es legible → fila **Info "auto, sin verificar"**, sin contar como fallo. (La regla "siempre explícito" de matwire rige lo que creamos; aquí auditamos lo existente, y castigar todo auto sería ruido que enseña a ignorar el check.)
3. **Inferencia de canal** (check A): **doble señal** — nombre de fichero (tablas MatWire, fuente única) **y puerto BRDF de destino** (tabla nueva puerto→canal). Una sola señal disponible → se usa; ambas coinciden → confianza máxima; **discrepan → Info sin Fix** (no adivinamos). Caza el caso real más común: `textura_final_v3.png` sin nombre reconocible enchufada a roughness en sRGB, invisible para la inferencia solo-por-nombre.

---

## Arquitectura (espejo del split matwire/matwire_c4d)

- **`plugin/sentinel/matgraph.py`** — motor puro (sin `import c4d`, pytest directo):
  - `infer_channel(filename, dest_port)` — combina las dos señales. Nombres: `matwire._match_channel`/`_CHANNEL_VARIANTS` (única fuente; si MatWire cambia su tabla, el check cambia con ella). Destinos: tabla nueva puerto-BRDF→canal en este módulo.
  - `audit_colorspaces(entries) -> verdicts` con vocabulario `ok | mismatch | conflict | auto_unverified | unknown | foreign_cs`. Colorspace esperado vía `matwire.channel_colorspace` (extendida si hace falta, nunca duplicada).
  - `find_dead_nodes(nodes, edges, roots, sink_ids) -> dead_ids` — BFS inverso desde roots ∪ sinks, O(nodos+aristas), un walk.
- **`plugin/sentinel/matgraph_c4d.py`** — adapter c4d: **un solo walk por material** (`collect(doc)`) que alimenta a AMBOS checks — nodos, aristas (`GetConnectedPorts`), y por cada Texture Sampler: path, colorspace asignado (sub-puerto `tex0/colorspace`, que `textures.py` ya conoce), a qué resuelve el auto si es legible, y el puerto BRDF de destino **rastreado a través de los utilities conocidos** (Color Correct, Ramp, Invert/rsmathinv, Bump, Color Layer — la lista exacta que matwire interpone). Cadena rota o utility desconocido → señal de puerto ausente, se cae a solo-nombre. NO se toca `scan_all_texture_paths` (Assets intacto); se reutiliza su patrón, no su función. Sin dependencia de la lib Boghma `renderEngine`.
- **Registry**: dos entradas — `rs_colorspace` (FAIL, ON, Select+Info+Fix) y `rs_dead_nodes` (WARN, ON, Select+Info+Fix). El score pasa a **X/14** solo por añadir las entradas (denominador = len(registry)); pasada de branding «12 checks»→14 en docs/README/CLAUDE.md. El «QC de assets del proyecto» reservado en ROADMAP será el #15.
- **Caché**: `collect(doc)` corre una vez por pasada de QC y sirve a ambos checks, bajo el `check_cache` normal (el stamp ya mide dirty de materiales desde v1.17).

## Check A — "RS Colorspace"

### Goal
Recorre cada Texture Sampler de cada material RS node-based y compara el colorspace asignado contra el que el canal inferido exige. Mismatch típico: roughness/normal/metalness/displacement en **sRGB** (render incorrecto), basecolor/emission en **Raw** (lavado). Botones: **Select** (ciclar materiales infractores) / **Info** (por textura: canal inferido y por qué señal, asignado, esperado) / **Fix** (corregir todos los infractores).

### Semántica de verdictos
- `mismatch` (explícito ≠ esperado) → violación con Fix.
- `auto` que resuelve mal → `mismatch` con Fix a explícito (decisión 2).
- `auto` ilegible → Info "auto, sin verificar" (no cuenta).
- `conflict` (nombre vs puerto discrepan) → Info sin Fix.
- Colorspace fuera del vocabulario RS conocido (OCIO custom) → Info, no fallo.
- Canal no inferible por ninguna señal → silencio (`unknown`). **Sin falsos positivos por diseño.** Packed ORM/ARM → Raw.

### Fix
Todos los puertos infractores del documento en **un** paso de undo: transacción maxon + ancla `AddUndo(UNDOTYPE_CHANGE, mat)` por material (patrón medido de matwire/repathing), escribiendo por la misma vía que `matwire_c4d._rs_colorspace`. Opt-in por click, jamás auto.

### Identidad (baseline)
`check_id` + nombre del material + basename de la textura + canal inferido (`field`) — se puede aceptar UN mismatch concreto («este roughness en sRGB es a propósito») sin sellar el material entero.

## Check B — "RS Dead Nodes"

### Goal
Por cada material RS node-based, los **nodos sin camino al Output** (basura de lookdev: samplers colgando, islas, restos de pruebas). Hermano dentro-del-grafo de "Unused Materials". Botones: **Select** / **Info** (cuántos y cuáles por material) / **Fix** (borrarlos, un undo).

### Semántica
- **Vivos** = alcanzable hacia atrás desde los **roots** (TODOS los puertos de entrada del Output: Surface, Displacement, Volume, Environment, …) ∪ **sinks legítimos** (`StoreColorToAOV`/`StoreScalarToAOV`/`StoreIntegerToAOV` y sus aguas-arriba). Muerto = el resto.
- **Conservador**: asset-id desconocido que parezca sink, o error leyendo el grafo → el material se reporta **Info, jamás Fix**. Solo se borra lo demostrablemente inalcanzable. El Output y el material sin grafo legible nunca cuentan.
- **La fila dice el alcance**: `3 materials with dead nodes (11 nodes)` — conteo en la fila, detalle en Info (regla de la casa v1.35).
- Estrictamente más fuerte que el prior art (ver Referencias): RsMat Clean / `RemoveIsolateNodes` solo borran nodos con cero conexiones — una isla cableada entre sí sobrevive y no distinguen sinks AOV.

### Fix
Borra los nodos muertos de todos los materiales infractores en **un** paso de undo (mismo patrón que A). Nunca auto.

### Identidad (baseline)
`check_id` + nombre del material + **snapshot del conteo de nodos muertos** como valor paramétrico (mecanismo existente de checks paramétricos): aceptar sella «N nodos muertos a propósito» (ramas aparcadas deliberadas); si N cambia, se re-arma. No hay identidad por-nodo: los ids de nodo maxon no tienen garantía de supervivencia a guardar+cargar (lección de identidad C4D), y nadie acepta basura nodo a nodo.

## Materiales fuera del universo
No-RS / no node-based: se ignoran en silencio (mismo comportamiento que Assets).

## Verificación (escalera)

1. **Mini-spike live obligatorio ANTES del writer** (doc throwaway, cero residuo): strings reales del combo colorspace pre/post-OCIO obligatorio (2025.2+; gate por versión si difieren), legibilidad del valor resuelto del auto, walk sobre un material RS **no creado por matwire**, y **medir el borrado de nodos + undo** — el fix de B es lo único destructivo y su receta de undo no está medida en este repo.
2. **Motores puros** con verificación por mutación de cada test; fakes con las dos superficies reales (grafo con aristas + sub-puertos) — el arnés miente hasta que se demuestre lo contrario (recurrencia nº10 documentada).
3. **Oráculo congelado**: `run_fixtures` gana dos filas `ok` triviales (las fixtures no tienen materiales RS) — se regenera el expected, no es un fallo. Nota heredada: `build_fixtures.py` está roto para `violating.c4d` (deuda v1.36.5).
4. **Ciclo live**: roughness en sRGB → rojo → Fix → verde → Cmd+Z → rojo. Isla muerta + rama de displacement viva + sink AOV → solo la isla cae. Fila y Info con el copy exacto.

## Fuera de alcance (escrito para que nadie lo re-proponga)
- **Autoría de cualquier tipo** — insert de nodos, auto-wire interactivo, solo/preview, hotkeys. Eso es Render Flow (Boghma) y no competimos ahí (spike Wrangler §12).
- Materiales no-RS.
- Perseguir el colorspace a través de utilities desconocidos (se cae a solo-nombre).
- Claves nuevas de ruleset (el per-check severity/on-off existente basta).

## Referencias
- `plugin/sentinel/matwire.py` (tablas de canal + `channel_colorspace`) y `matwire_c4d.py::_rs_colorspace` (el Fix escribe por la misma vía).
- `plugin/sentinel/textures.py` (walk maxon de puertos RS existente; su propio walk tuvo bugs hasta 2026-08: `GetConnectedPorts` devolvía siempre `None` por un `or` que debía ser `and` — motivo extra para el spike live).
- Spike Wrangler §6 (trampa ACEScg, con fuentes) y `Node Wrangler/spikes/wrangler/live_probe_log.md` (ids de nodo RS confirmados en vivo, p.ej. `...nodes.core.texturesampler`).
- **Prior art de B**: RsMat Clean (Boghma, free, Windows-only) — estudio de comportamiento solamente, cero código. `renderEngine/utils/node_helper.py::RemoveIsolateNodes` (verificado leyendo la implementación 2026-08-26): solo borra nodos con cero conexiones (`IsNodeConnected`), sin reachability ni sinks AOV — prior art del gesto, NO el algoritmo; no adoptar como atajo.
- Memoria Wrangler: `c4d-mcp-bridge-graph-limits` (por qué se verifica con plugin real, no vía MCP).

## Orden de trabajo
A primero (más valor, menos riesgo de borrado); B después reutilizando el walk. Estimación del spike (con la fontanería en repo): A ≈ 2–4 días, B ≈ 1–2 días.
