# Material Graph — QC de colorspace (check #13) + Clean Dead Nodes (Tools)

- **Fecha:** 2026-08-25 (borrador del spike) · **2026-08-26: diseño aprobado en brainstorm, pendiente de plan.**
- **Origen:** spike Wrangler (`Node Wrangler/docs/spikes/2026-08-25-wrangler-spike.md`). Veredicto: el Wrangler standalone es NO-GO (Render Flow de Boghma ocupa la autoría), pero la **auditoría** de grafos de materiales RS es territorio Sentinel y nadie la tiene: Render Flow/NodeFlow asigna colorspace *al crear*; nadie audita *lo ya existente* (material de Gumroad, heredado, hecho a mano).
- **Posicionamiento:** refuerza el claim "el único preflight de render de C4D". Auditoría, NO autoría — cero hotkeys, cero insert interactivo, cero solo/preview (descartado explícitamente; ver Fuera de alcance).

## Decisiones cerradas en brainstorm (2026-08-26)

1. **Reparto de puertas — la decisión que reestructura el spec.** El colorspace es **QC** (check #13, FAIL, ON): fallo silencioso que renderiza píxeles mal y entra en la escena cada vez que se mergea un material ajeno — necesita vigilancia continua, no un botón que haya que recordar. Los nodos muertos **NO son QC**: no cambian ni un píxel — son limpieza, y la decisión de producto de la v1.30 ya fijó que **los limpiadores viven en Tools como botones acción→toast, no como checks** (por eso Delete Empty Nulls y Clean Material Tags no son checks). Un WARN casi-siempre-ámbar-y-casi-nunca-importante enseña a ignorar el panel. → **"Clean Dead Nodes" va a Tools → Cleanup**, junto a sus hermanos. El score pasa a **X/13**. Corolario: B pierde la identidad de baseline (no hay fila que aceptar) — se cae la parte más discutible del diseño anterior. Lo que se renuncia, dicho: la basura no aparece en el informe QC del Collector; para basura que no afecta a la entrega, correcto.
2. **Severidad y default del check A**: **FAIL, ON por defecto**. Consecuencia aceptada (lección v1.36.5): escenas viejas mostrarán violaciones nuevas de golpe — información verdadera. Severidad/on-off ajustables por proyecto con el mecanismo per-check existente; **cero claves nuevas de ruleset**.
3. **El valor "auto"** (check A): violación **solo si el auto resuelve MAL**. Resuelto legible y correcto → OK; resuelve distinto → `mismatch` con Fix a explícito; ilegible → fila **Info "auto, sin verificar"**, sin contar como fallo. (La regla "siempre explícito" de matwire rige lo que creamos; aquí auditamos lo existente, y castigar todo auto sería ruido que enseña a ignorar el check.)
4. **Inferencia de canal** (check A): **doble señal** — nombre de fichero (tablas MatWire, fuente única) **y puerto BRDF de destino** (tabla nueva puerto→canal). Una sola señal → se usa; ambas coinciden → confianza máxima; **discrepan → Info sin Fix** (no adivinamos). Caza el caso real más común: `textura_final_v3.png` sin nombre reconocible enchufada a roughness en sRGB, invisible para la inferencia solo-por-nombre.

---

## Arquitectura (espejo del split matwire/matwire_c4d)

- **`plugin/sentinel/matgraph.py`** — motor puro (sin `import c4d`, pytest directo), compartido por el check y la herramienta:
  - `infer_channel(filename, dest_port)` — combina las dos señales. Nombres: `matwire._match_channel`/`_CHANNEL_VARIANTS` (única fuente; si MatWire cambia su tabla, el check cambia con ella). Destinos: tabla nueva puerto-BRDF→canal en este módulo.
  - `audit_colorspaces(entries) -> verdicts` con vocabulario `ok | mismatch | conflict | auto_unverified | unknown | foreign_cs`. Colorspace esperado vía `matwire.channel_colorspace` (extendida si hace falta, nunca duplicada).
  - `find_dead_nodes(nodes, edges, roots, sink_ids) -> dead_ids` — BFS inverso desde roots ∪ sinks, O(nodos+aristas), un walk.
- **`plugin/sentinel/matgraph_c4d.py`** — adapter c4d: **un solo walk por material** (`collect(doc)`) que alimenta al check Y a la herramienta — nodos, aristas (`GetConnectedPorts`), y por cada Texture Sampler: path, colorspace asignado (sub-puerto `tex0/colorspace`, que `textures.py` ya conoce), a qué resuelve el auto si es legible, y el puerto BRDF de destino **rastreado a través de los utilities conocidos** (Color Correct, Ramp, Invert/rsmathinv, Bump, Color Layer — la lista exacta que matwire interpone). Cadena rota o utility desconocido → señal de puerto ausente, se cae a solo-nombre. NO se toca `scan_all_texture_paths` (Assets intacto); se reutiliza su patrón, no su función. Sin dependencia de la lib Boghma `renderEngine`.
- **Registry**: UNA entrada nueva — `rs_colorspace` (FAIL, ON, Select+Info+Fix). Score a **X/13** solo por añadirla (denominador = len(registry)); pasada de branding «12 checks»→13 en docs/README/CLAUDE.md. El «QC de assets del proyecto» reservado en ROADMAP será el #14.
- **Caché**: para el QC, `collect(doc)` corre bajo el `check_cache` normal (el stamp ya mide dirty de materiales desde v1.17). La herramienta de Tools re-colecta al pulsarse (es on-demand, no cacheable por definición).

## Check A — QC #13 "RS Colorspace"

### Goal
Recorre cada Texture Sampler de cada material RS node-based y compara el colorspace asignado contra el que el canal inferido exige. Mismatch típico: roughness/normal/metalness/displacement en **sRGB** (render incorrecto, la trampa ACEScg), basecolor/emission en **Raw** (lavado). Botones: **Select** (ciclar materiales infractores) / **Info** (por textura: canal inferido y por qué señal, asignado, esperado) / **Fix** (corregir todos los infractores).

### Semántica de verdictos
- `mismatch` (explícito ≠ esperado) → violación con Fix.
- `auto` que resuelve mal → `mismatch` con Fix a explícito (decisión 3).
- `auto` ilegible → Info "auto, sin verificar" (no cuenta).
- `conflict` (nombre vs puerto discrepan) → Info sin Fix.
- Colorspace fuera del vocabulario RS conocido (OCIO custom) → Info, no fallo.
- Canal no inferible por ninguna señal → silencio (`unknown`). **Sin falsos positivos por diseño.** Packed ORM/ARM → Raw.

### Fix
Todos los puertos infractores del documento en **un** paso de undo: transacción maxon + ancla `AddUndo(UNDOTYPE_CHANGE, mat)` por material (patrón medido de matwire/repathing), escribiendo por la misma vía que `matwire_c4d._rs_colorspace`. Opt-in por click, jamás auto.

### Identidad (baseline)
`check_id` + nombre del material + basename de la textura + canal inferido (`field`) — se puede aceptar UN mismatch concreto («este roughness en sRGB es a propósito») sin sellar el material entero.

## Herramienta B — Tools → Cleanup → "Clean Dead Nodes"

### Goal
Botón acción→toast junto a Delete Empty Nulls y Clean Material Tags: por cada material RS node-based, borra los **nodos sin camino al Output** (basura de lookdev: samplers colgando, islas, restos de pruebas). Toast con el parte exacto (`Cleaned 11 dead nodes in 3 materials.` / `No dead nodes found.`); **un solo Cmd+Z** revierte el lote entero.

### Semántica
- **Vivos** = alcanzable hacia atrás desde los **roots** (TODOS los puertos de entrada del Output: Surface, Displacement, Volume, Environment, …) ∪ **sinks legítimos** (`StoreColorToAOV`/`StoreScalarToAOV`/`StoreIntegerToAOV` y sus aguas-arriba). Muerto = el resto.
- **Conservador**: asset-id desconocido que parezca sink, o error leyendo el grafo → ese material **se salta y el toast lo cuenta** (`· 1 material skipped (unreadable graph)`), jamás se borra a ciegas. Solo cae lo demostrablemente inalcanzable. El Output y el material sin grafo legible nunca cuentan.
- Estrictamente más fuerte que el prior art (ver Referencias): RsMat Clean / `RemoveIsolateNodes` solo borran nodos con cero conexiones — una isla cableada entre sí sobrevive y no distinguen sinks AOV.

### Fontanería
Op `panel/tools/clean_dead_nodes` en el patrón de los cleanups de v1.30 (core sin diálogos, `_forbid_dialog` en test, dict de estado → toast; entrada en `TOOL_GROUPS` grupo Cleanup). Sin identidad de baseline, sin fila de QC, sin claves de ruleset.

## Materiales fuera del universo
No-RS / no node-based: se ignoran en silencio en ambas piezas (mismo comportamiento que Assets).

## Verificación (escalera)

1. **Mini-spike live obligatorio ANTES del writer** (doc throwaway, cero residuo): strings reales del combo colorspace pre/post-OCIO obligatorio (2025.2+; gate por versión si difieren), legibilidad del valor resuelto del auto, walk sobre un material RS **no creado por matwire**, y **medir el borrado de nodos + undo** — lo único destructivo y su receta de undo no está medida en este repo.
2. **Motores puros** con verificación por mutación de cada test; fakes con las dos superficies reales (grafo con aristas + sub-puertos) — el arnés miente hasta que se demuestre lo contrario (recurrencia nº10 documentada).
3. **Oráculo congelado**: `run_fixtures` gana UNA fila `ok` trivial (las fixtures no tienen materiales RS) — se regenera el expected, no es un fallo. Nota heredada: `build_fixtures.py` está roto para `violating.c4d` (deuda v1.36.5).
4. **Ciclo live**: roughness en sRGB → check #13 rojo → Fix → verde → Cmd+Z → rojo. Clean Dead Nodes sobre material con isla muerta + rama de displacement viva + sink AOV → solo la isla cae, toast con el conteo, un Cmd+Z la devuelve.

## Fuera de alcance (escrito para que nadie lo re-proponga)
- **Autoría de cualquier tipo** — insert de nodos, auto-wire interactivo, solo/preview, hotkeys. Eso es Render Flow (Boghma) y no competimos ahí (spike Wrangler §12).
- **Dead nodes como check de QC** — evaluado y descartado en este brainstorm por la decisión de producto v1.30 (limpiadores = Tools). Si alguien lo re-propone, la respuesta es la decisión 1 de arriba.
- Materiales no-RS.
- Perseguir el colorspace a través de utilities desconocidos (se cae a solo-nombre).
- Claves nuevas de ruleset (el per-check severity/on-off existente basta).

## Referencias
- `plugin/sentinel/matwire.py` (tablas de canal + `channel_colorspace`) y `matwire_c4d.py::_rs_colorspace` (el Fix escribe por la misma vía).
- `plugin/sentinel/textures.py` (walk maxon de puertos RS existente; su propio walk tuvo bugs hasta 2026-08: `GetConnectedPorts` devolvía siempre `None` por un `or` que debía ser `and` — motivo extra para el spike live).
- Spike Wrangler §6 (trampa ACEScg, con fuentes) y `Node Wrangler/spikes/wrangler/live_probe_log.md` (ids de nodo RS confirmados en vivo, p.ej. `...nodes.core.texturesampler`).
- **Prior art de Clean Dead Nodes**: RsMat Clean (Boghma, free, Windows-only) — estudio de comportamiento solamente, cero código. `renderEngine/utils/node_helper.py::RemoveIsolateNodes` (verificado leyendo la implementación 2026-08-26): solo borra nodos con cero conexiones (`IsNodeConnected`), sin reachability ni sinks AOV — prior art del gesto, NO el algoritmo; no adoptar como atajo.
- Decisión de producto v1.30 (CLAUDE.md): limpiadores en Tools como acción→toast, no como QC.
- Memoria Wrangler: `c4d-mcp-bridge-graph-limits` (por qué se verifica con plugin real, no vía MCP).

## Orden de trabajo
A primero (más valor); Clean Dead Nodes después reutilizando el walk. Estimación (con la fontanería en repo): A ≈ 2–4 días, B ≈ 1 día (encogido al perder fila/baseline).
