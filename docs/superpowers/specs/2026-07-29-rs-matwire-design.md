# RS Material from Folder — auto-wire PBR desde carpeta de texturas (v1.32)

**Fecha**: 2026-07-29
**Estado**: aprobado en brainstorm (decisiones del usuario: vive en Tools como sub-vista — NO en el Asset Hub, corrigiendo la sugerencia del researcher; set PBR completo + Spec/Gloss legacy; carpetas multi-set agrupan y crean N materiales)
**Contexto**: tercera fase del arco "expansión de Tools" (v1.30 quick-wins ✅ → v1.31 Batch Rename ✅ → **v1.32 este spec** → v1.33 Recall/template). Referencia de mercado: Node Ninja (School of Motion, free, muy citado, sin equivalente en Sentinel). Racional de ubicación (producto + supervisión): el auto-wire es AUTORÍA en momento look-dev (panel dockeado, ráfagas de packs), no inventario — el Hub es para assets YA en escena y entrega; además la IA de v1.23 fijó "Tools = utilidades de autoría" y podó las puertas redundantes. Valor Sentinel: **encodea la convención del estudio** (colorspaces, nodos correctos) — el material sale bien lo cablee quien lo cablee. Base: main con v1.31.0 mergeado y live-verified.

## Decisiones cerradas

1. **Ubicación**: sub-vista del panel en Tools ("Material from Folder →", patrón Batch Rename). SIN acceso duplicado desde el Hub (regla anti-puertas de v1.23).
2. **Canales reconocidos** (sufijo de nombre de archivo, case-insensitive, delimitado por `_`/`-`/`.`): BaseColor (`basecolor|albedo|diffuse|col|diff`) · Roughness (`roughness|rough`) · Metalness (`metalness|metallic|metal`) · Normal (`normal|nrm|nor`) · Height/Displacement (`height|displacement|disp`) · AO (`ao|ambientocclusion|occlusion`) · Opacity (`opacity|alpha`) · Emission (`emission|emissive`) · **Specular (`specular|spec`) · Glossiness (`glossiness|gloss`)** para packs legacy.
3. **Multi-set**: una carpeta con varios sets agrupa por RAÍZ común (nombre sin sufijo de canal ni token de resolución — reutiliza `split_res_token` de v1.18) y crea **N materiales de una pasada**; el preview lista cada set con checkbox para excluir.
4. **Variantes de resolución**: por canal se elige la MÁS ALTA; el resto va a `ignored` con motivo (visible en preview). Conflicto sin variante (dos archivos → mismo canal): el primero gana, el otro a `ignored`.
5. **Sin auto-assign en v1**: crea los materiales en el Material Manager; asignar a selección = extensión futura. Todo el lote en un undo.

## Diseño

### Motor

- **`matwire.py` (módulo nuevo)** — núcleo PURO (sin `import c4d`, pytest directo):
  - `scan_texture_sets(filenames) -> [{"name", "channels": {channel: filename}, "ignored": [(filename, reason)]}]` — reconocimiento por la tabla de sufijos, agrupación por raíz, resolución de variantes/conflictos. Archivos sin canal reconocible → `ignored` (`no_channel`). Solo extensiones de imagen (allowlist: jpg/jpeg/png/tif/tiff/exr/hdr/tga/bmp/webp).
  - `channel_colorspace(channel) -> "srgb"|"raw"` — BaseColor/Emission → sRGB; TODO lo demás raw. Fuente única (el preview la muestra, el wiring la aplica — nunca dos tablas).
  - Reglas de precedencia puras: Spec/Gloss SOLO se cablean si el set NO tiene Roughness/Metalness (PBR moderno gana si conviven); Glossiness se conecta INVERTIDA a roughness.
- **Wiring RS** (adapter c4d): un material **Redshift Standard** por set vía la API oficial declarativa `maxon.GraphDescription` (C4D 2024+; referencia cruzada obligatoria con `../11 C4D DEV/renderEngine/Redshift/material.py` y los ejemplos oficiales de Maxon antes de inventar patrones — regla del CLAUDE.md). Por canal:
  - BaseColor → base color (sRGB) · Roughness → refl. roughness (raw) · Metalness → metalness (raw) · Opacity → opacity (raw) · Emission → emission color (sRGB).
  - Normal → nodo Bump Map en modo Tangent-Space Normal → bump input.
  - Height → nodo Displacement → output de displacement del material (no al grafo de superficie).
  - Glossiness → inversión (nodo matemático 1−x o el invert propio del nodo si existe) → roughness. Specular → refl. color solo en workflow legacy.
  - **AO: el nodo de textura se CREA pero queda sin conectar** — conectarlo es decisión de shading; visible en el grafo, el artista decide.
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

- Auto-assign a selección; triplanar/UDIM; otros renderers (Arnold/Octane); presets de mapeo configurables por ruleset (candidato si los estudios piden otra convención); drag&drop de carpeta al panel.
