# RS Material from Folder — auto-wire PBR desde carpeta de texturas (v1.32)

**Fecha**: 2026-07-29
**Estado**: LIVE-VERIFIED y mergeado (C4D 2026.303; pytest 1012 + vitest 169; matriz completa incl. lección maxon.Bool truthiness). Pulido v1.32.1 acordado: recursivo, ORM/ARM cableado, sufijos vía ruleset, import leftover. (decisiones del usuario: vive en Tools como sub-vista — NO en el Asset Hub, corrigiendo la sugerencia del researcher; set PBR completo + Spec/Gloss legacy; carpetas multi-set agrupan y crean N materiales)
**Contexto**: tercera fase del arco "expansión de Tools" (v1.30 quick-wins ✅ → v1.31 Batch Rename ✅ → **v1.32 este spec** → v1.33 Recall/template). Referencia de mercado: Node Ninja (School of Motion, free, muy citado, sin equivalente en Sentinel). Racional de ubicación (producto + supervisión): el auto-wire es AUTORÍA en momento look-dev (panel dockeado, ráfagas de packs), no inventario — el Hub es para assets YA en escena y entrega; además la IA de v1.23 fijó "Tools = utilidades de autoría" y podó las puertas redundantes. Valor Sentinel: **encodea la convención del estudio** (colorspaces, nodos correctos) — el material sale bien lo cablee quien lo cablee. Base: main con v1.31.0 mergeado y live-verified.

## Decisiones cerradas

1. **Ubicación**: sub-vista del panel en Tools ("Material from Folder →", patrón Batch Rename). SIN acceso duplicado desde el Hub (regla anti-puertas de v1.23).
2. **Canales reconocidos** (sufijo de nombre de archivo, case-insensitive, delimitado por `_`/`-`/`.`/espacio, con tolerancia al sufijo pegado `Map` — `RoughnessMap` — regla `(?:_?map)?`; sinónimos ampliados con la tabla verbatim del mercado, ver `docs/research/2026-07-29-matwire-implementations.md`): BaseColor (`basecolor|albedo|diffuse|col|diff|base|dif`) · Roughness (`roughness|rough|rgh`) · Metalness (`metalness|metallic|metal|met|mtl`) · Normal (`normal|nrm|nor|norm|nml|nrml|nmap`) — con distinción **GL/DX**: `normalgl|normal_gl|nor_gl|normalopengl` y `normaldx|normal_dx|nrm_dx|dx_normal|nor_dx`; GL gana sobre DX y sobre genérico, y si SOLO hay DX se cablea con `bumpmap.flipy=True` (FAB/Unreal exportan DX — sin esto el render sale mal) · Height/Displacement (`height|displacement|disp|dsp|depth`) · AO (`ao|ambientocclusion|ambient_occlusion|occlusion|occ`) · Opacity (`opacity|alpha|cutout|transparency`) · Emission (`emission|emissive|emit`) · **Specular (`specular|spec`) · Glossiness (`glossiness|gloss`)** para packs legacy. **Packs empaquetados ORM/ARM** (`orm|arm`): detectados y enviados a `ignored` con motivo `packed_orm` en v1 (v2 candidato: `rscolorsplitter` → AO/Rough/Metal con prioridad a mapas dedicados).
3. **Multi-set**: una carpeta con varios sets agrupa por RAÍZ común (nombre sin sufijo de canal ni token de resolución — reutiliza `split_res_token` de v1.18; TexToMatO valida el mismo modelo, Node Ninja agrupa por carpeta y mezcla sets — el nuestro es el bueno) y crea **N materiales de una pasada**; el preview lista cada set con checkbox para excluir. **Nombres deduplicados contra el Material Manager** (auto-sufijo `_02`… mostrado en el preview — server-driven, sin diálogos).
4. **Variantes de resolución**: por canal se elige la MÁS ALTA; el resto va a `ignored` con motivo (visible en preview). Conflicto sin variante (dos archivos → mismo canal): el primero gana, el otro a `ignored`.
5. **Sin auto-assign en v1**: crea los materiales en el Material Manager; asignar a selección = extensión futura. Todo el lote en un undo.

## Diseño

### Motor

- **`matwire.py` (módulo nuevo)** — núcleo PURO (sin `import c4d`, pytest directo):
  - `scan_texture_sets(filenames) -> [{"name", "channels": {channel: filename}, "ignored": [(filename, reason)]}]` — reconocimiento por la tabla de sufijos, agrupación por raíz, resolución de variantes/conflictos. Archivos sin canal reconocible → `ignored` (`no_channel`). Solo extensiones de imagen (allowlist: jpg/jpeg/png/tif/tiff/exr/hdr/tga/bmp/webp/**tx**; dds/psd anotados como opcionales).
  - `channel_colorspace(channel) -> "srgb"|"raw"` — BaseColor/Emission → sRGB; TODO lo demás raw. Fuente única (el preview la muestra, el wiring la aplica — nunca dos tablas).
  - Reglas de precedencia puras: Spec/Gloss SOLO se cablean si el set NO tiene Roughness/Metalness (PBR moderno gana si conviven); Glossiness va a roughness con el flag nativo `refl_isglossiness` (ver Wiring — sin nodo invert).
- **Wiring RS** (adapter c4d): un material **Redshift Standard** por set vía la API oficial declarativa `maxon.GraphDescription` (C4D 2024+). **Los ID strings de nodos/puertos están CONFIRMADOS en 3 implementaciones vivas** y catalogados en `docs/research/2026-07-29-matwire-implementations.md` §Recomendación 5 (nodespace `com.redshift3d.redshift4c4d.class.nodespace`; `texturesampler.tex0` es puerto GRUPO con hijos `path` y `colorspace`; colorspace SIEMPRE explícito en ambos sentidos — `"RS_INPUT_COLORSPACE_RAW"`/`"RS_INPUT_COLORSPACE_SRGB"`, nunca confiar en el default auto) — la matriz de verificación coteja lo que emita GraphDescription contra esos IDs. Gotchas heredados del research: rutas como URL construidas A MANO si hace falta `maxon.Url` (`pathlib.as_uri()` percent-encodea espacios y C4D no abre la textura — bug documentado en Node Ninja; verificar en el spike qué acepta GraphDescription); layout de nodos — si GraphDescription no posiciona solo, plan B = `net.maxon.node.base.xpos/ypos` explícitos (JAMÁS `CallCommand` de arrange: solo funciona con el Node Editor abierto); disponibilidad de nodos por versión de RS sondeable vía `FindLatestAsset(NodeTemplate, Id(node_id)).IsPopulated()` para un `redshift_unavailable` fino. Por canal:
  - BaseColor → base color (sRGB) · Roughness → refl. roughness (raw) · Metalness → metalness (raw) · Opacity → opacity (raw) · Emission → emission color (sRGB) **+ `emission_weight = 1.0`** (default 0.0 — los tres plugins del mercado entregan emisión invisible; corrección diferencial).
  - Normal → nodo Bump Map en modo Tangent-Space Normal → bump input.
  - Height → nodo Displacement → output de displacement del material (no al grafo de superficie).
  - Glossiness → directo a `refl_roughness` + puerto bool `refl_isglossiness = True` del Standard Material (semántica nativa RS, cero nodos extra — hallazgo de TexToMatO; fallback `rsmathinv` solo si el puerto no existiera). Specular → refl. color solo en workflow legacy.
  - **AO: el nodo de textura se CREA pero queda sin conectar** — conectarlo es decisión de shading; visible en el grafo, el artista decide. (Contexto de mercado: los TRES plugins estudiados lo conectan por color-layer multiply — la nuestra es una decisión contra-mercado consciente, anotada como toggle candidato de ruleset en deuda.)
- **Ops** (`panel_tools_ops.py`): `panel/tools/matwire_preview` (payload `{folder}` → sets/canales/colorspaces/ignorados; read-only; errores `no_document|bad_folder|no_sets|redshift_unavailable`) y `panel/tools/matwire_create` (payload `{folder, exclude: [set_names], names: {set: custom_name}}`; **re-deriva server-side** — patrón v1.31; un undo; devuelve `{created: N, materials: [...]}`). Dialog-free (`_forbid_dialog`).
- **Picker de carpeta**: wrinkle conocido — un `LoadDialog` nativo es MODAL y congelaría el drain de la cola. Resolver en el plan siguiendo el precedente del Hub ("Search Folder for Missing" en la SPA: cómo obtiene la carpeta esa ruta). Fallback siempre disponible: campo de texto con la ruta.

### UI (sub-vista en Tools)

- El grupo **Naming** de Tools se renombra a **Authoring** y acoge Batch Rename + **"Material from Folder →"** (decisión de agrupación fina delegada al plan si el espacio pide otra cosa).
- Sub-vista `MatwireSubview`: campo carpeta + Browse; por cada set detectado: checkbox incluir, **nombre editable** (default = raíz), lista de canales con archivo y colorspace, `ignored` plegado con motivos; **Create N materials** primary → toast "Created N RS material(s)." + un Cmd+Z revierte el lote; `← Tools` con `restoreFocus` (lección v1.18/lib/focus.ts). Redshift no disponible → estado inline.
- Preview server-driven SIEMPRE (patrón v1.31: el cliente jamás re-implementa el reconocimiento).

## Errores / no-regresión

- Cero cambios en QC/registry/Hub; herramientas existentes de Tools intactas.
- Sin Redshift instalado la sub-vista degrada honesta (`redshift_unavailable`), nunca crea materiales a medias: si un set falla a mitad de wiring, se reporta por set (`errors` en la respuesta) y el undo global sigue siendo uno.
- El motor puro no toca disco fuera del listado de la carpeta dada (sin escritura de archivos).

## Verificación

- pytest: tabla de sufijos (todos los canales + case/delimitadores), agrupación multi-set, variantes de resolución (gana la más alta) y conflictos, precedencia Spec/Gloss vs PBR, colorspace única fuente, allowlist de extensiones, contratos de ops (`_forbid_dialog`, re-derivación, exclude/names).
- vitest: shapes + copys de toast.
- Live (matriz): carpeta real de pack (Quixel/Poliigon) single-set → material RS con todos los nodos y colorspaces correctos (verificación en el node editor + render); carpeta multi-set → N materiales; pack legacy spec/gloss → gloss invertida; variantes 4k/8k → gana 8k e ignora 4k visiblemente; AO presente sin conectar; un Cmd+Z revierte el lote entero; sin Redshift (si es posible probar) → estado honesto.

## Fuera de alcance

- Auto-assign a selección; triplanar/UDIM (el camino moderno si llega: UV Context Projection, RS 2026.2+); otros renderers (Arnold/Octane); presets de mapeo configurables por ruleset (precedente: `custom_regex.json` de TexToMatO → nuestra versión iría en `sentinel_rules.json`); drag&drop de carpeta al panel; AO conectado como toggle; opacity vía nodo Sprite (perf de cutouts); splitter ORM/ARM (v2); mid-level 0.5 para height 16-bit int vía `imagemeta.py` (nadie del mercado lo resuelve — diferencial futuro); "import from base" (derivar set de un material existente).

## Procedencia

- Investigación de implementaciones reales (Node Ninja/SOM, Auto_Connect_PBR/RS Node Tools, TexToMatO): `docs/research/2026-07-29-matwire-implementations.md`. **Licencias: los tres son estudiar-sí/copiar-no** (sin licencia o all-rights-reserved; Salad declara MIT pero embebido en producto propietario y sin LICENSE upstream) — de ellos tomamos HECHOS (IDs, valores, precedencias), cero código. Nuestro motor puro + GraphDescription no necesita copiar nada.
