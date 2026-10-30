# Sentinel — Roadmap

Solo lo pendiente. Lo entregado, con su porqué, está en [`docs/HISTORY.md`](docs/HISTORY.md).

## Estado (2026-10-30)
- `main`: **v1.43.2** (etiqueta `v1.43.2`, PR #44: preview de Matwire sin desbordar el panel, "on disk" en el Hub). v1.43.1 (PR #41): Shrink UDIM desde el panel. v1.42.0 y v1.43.0 entraron juntas en el PR #39. La última aceptada en los dos sistemas es **v1.41.0** (etiqueta `v1.41.0`). Matriz soportada: **Cinema 4D 2025–2027**, macOS y Windows. Objetivo del estudio: **C4D 2026.4.0**.
- Aceptada en Windows 11 + C4D 2026.4.0 (ronda 6, con el código de v1.40.1) y en macOS + C4D 2026.304 (ronda Mac 1); C4D 2027.0 comprobado en vivo en macOS. Evidencia: [`docs/audit/2026-09-24-windows-acceptance.md`](docs/audit/2026-09-24-windows-acceptance.md) y [`docs/audit/2026-10-24-macos-acceptance.md`](docs/audit/2026-10-24-macos-acceptance.md).
- v1.42.0 (Matwire UDIM + export de Painter), v1.43.0 (acciones del Hub por tesela y QC #14), v1.43.1 y v1.43.2: comprobadas en vivo en macOS + C4D 2026.304. En el panel de la GUI (2026-10-30) pasaron las acciones del Hub por tesela, QC #14, Collect y Matwire UDIM con el export real de Painter del LOK-003. Sin ronda Windows (solo CI): checklist en [`docs/audit/2026-10-30-windows-udim-checklist.md`](docs/audit/2026-10-30-windows-udim-checklist.md).
- CI en cada PR y push a `main`: pytest en Linux, macOS y Windows + web.

## Para cerrar la beta
- [x] Windows: casilla "Save snapshots as EXR" de RenderView comprobada en las rondas 4 y 5 (y el aviso ámbar cuando falta).
- [ ] Windows: repetir Frame (expandir el tag) y Hub (Switch res) con los plugins habituales del estudio cargados. Dispensado por ahora: esos plugins solo están instalados en C4D 2025. En macOS se probó con ellos cargados (ronda Mac 1, sin fallos de Frame ni Hub).
- [ ] `http.handler_failed` visto una vez en la consola de Windows: capturar el texto completo si reaparece (no reproducido en macOS ni en las rondas 4 y 5).
- [ ] Usabilidad: la ventana de Settings ya abierta puede quedar detrás del panel al pedirla otra vez (`open_form` reutiliza sin traer al frente; no romper la protección contra cerrar/abrir un HTML viewer vivo). El nombre de artista del Overview no se refresca hasta reabrir el panel.

**Ronda Windows 7 (v1.43.2, 2026-10-30): 10 OK, 2 FAIL.** Los dos se reproducen también en macOS. Detalle en [`docs/audit/2026-09-24-windows-acceptance.md`](docs/audit/2026-09-24-windows-acceptance.md#round-7--2026-10-30-candidate-5128c00-v1432-c4d-202640--udim).
- [x] **Redo de un relink con varios mapas en un material.** Copy into project con 3 mapas: Undo repone los 3, Redo solo 1. Causa: la transacción del grafo con `UNDO_MODE.ADD`. Corregido con `NONE` + la instantánea del material, en la rama `fix/hub-relink-redo` (afecta a todo relink del Hub).
- [ ] **Material Graph: posible pérdida en Redo.** `matgraph_c4d` usa el mismo `UNDO_MODE.ADD` con varias transacciones por lote. Sin medir.
- [x] **UDIM sin tesela 1001.** Redshift resuelve el patrón solo a través de la 1001: sin ella, toda la textura sale `Not Found`. Un `1001` en otra parte de la ruta (carpeta `shot_1001`) también la rompe. QC #14 y la preview de Matwire avisan desde la rama `feat/udim-tile-1001-warning` (`udim.redshift_unresolved`); el Hub todavía no. Medición en `docs/research/2026-10-30-redshift-udim-needs-tile-1001.md`.
- [x] Toasts en crudo `scene_changed` tras Undo/Redo en el Hub. Causa medida: tras Undo/Redo, C4D sigue subiendo el dirty de los materiales unos segundos (+4 en ~2,5 s), el sello del Hub queda viejo y cada clic de fila lo rechaza. El Hub ahora refresca en silencio y reintenta una vez; si sigue cambiando, avisa legible. Rama `fix/hub-scene-changed-toasts`.
- [ ] En ese estado, Shift/Ctrl dejaron de ampliar la selección (Windows). Sin reproducir en macOS: los clics en segundo plano no llevan modificadores.
- [x] "Cmd+Z" en los diálogos Shrink y Switch res en Windows (y en la confirmación de Reset All): "Ctrl+Z" fuera de macOS, rama `fix/undo-shortcut-label`.
- [ ] Manifiesto de Collect: `original_path` es `relative:///<nombre>` y no la ubicación real; `hash` es `null` y no hay sello; `assets_collected: 91` frente a `collected: 18`.
- [ ] Switch res: con la fila enlazada a una familia incompleta, el diálogo lista "1K 1/1 available" sin aviso. Collect no restaura un Hub minimizado.

**Limitación conocida, no se persigue:** en Windows con C4D 2026.3.4, expandir el tag Sentinel Frame en el Attribute Manager puede cerrar C4D (llamada nativa a dirección nula en `gui.module`, sin Python en la pila, causa sin aislar). No ocurre en 2026.4.0 ni en macOS.

## Antes de distribuir comercialmente
Detalle en la tabla *Before distributing a commercial product* del informe de product-readiness.
- [ ] Titularidad y licencia: el `LICENSE` nombra a Javier Melgar / Yambo Studio. Sentinel parte de YS Guardian v1.0 (5 checks, presets, herramientas de escena, snapshots) y todo lo posterior es desarrollo propio; hay que acordar con los titulares los derechos sobre el código original y la licencia del producto.
- [ ] `abc_retime` (AXISFX): permiso de redistribución o sacarlo del paquete.
- [ ] Assets `.c4d` empaquetados: origen y permiso de cada uno. (Los iconos son propios desde la v1.39.)
- [x] Plugin IDs: registrados en Plugin Café (cuenta `jmelpri`, 2026-10-25) y en uso desde la v1.41: Panel 1072205, Command Palette 1072206, Frame tag 1072207, Frame Sync 1072208, Pin tag 1072209, Variants tag 1072210. Se retira el rango 2099xxx sin registrar; no había escenas de producción con esos tags.
- [x] Matriz soportada: Cinema 4D 2025–2027 en macOS y Windows (README y Doctor). Queda la plantilla de soporte.

## Features siguientes
- **QC #15 — assets que declara el proyecto** (el #14 es UDIM Tiles desde la v1.43). Necesita su propio spec (identidad, baseline y fontanería de informe). Aporta valor aunque no se use "nuevo shot".
- **Scene Complexity Budget.** Polígonos, VRAM estimada de texturas, objetos y luces frente a umbrales por estudio, con semáforo por métrica. Motivo: el artista no sabe que la escena pesa demasiado hasta que el render falla por memoria.

## Deuda técnica
- **Auditoría del undo de todas las operaciones.** Arnés repetible en C4D vivo: por operación, la escena cambia, un solo paso la revierte, rehacer la restaura. Hay evidencia real ("funciona con uno, se rompe con N" apareció en matwire, v1.35 y v1.36).
- **`id()` como identidad de nodos.** `keyframes.py` (dedupe del stagger) compara `id()` de envoltorios de C4D, que nunca coinciden entre lecturas. Sin confirmar en vivo. También usan `id()`: `frame_tag.py`, `panel_ops.py`, `textures.py`.
- **Pin:** parámetros anidados (`DescID` multinivel: gradientes, splines de falloff) sin medir; `Display Color`/`X-Ray` (907-909) no se restauran; `Shutter Offset` de la RS Camera (8105) sin diagnosticar.
- **Variants:** dos conjuntos con anclajes homónimos escriben los mismos nombres de archivo al renderizar todas las opciones.
- **Material Graph:** medir el rendimiento de `collect` en una escena de lookdev pesada.
- **Asset Hub (motor):** `create_zip_archive` puede dejar un `.zip` truncado si falla a mitad; letra de unidad en `canonical_asset_key` (un segmento POSIX tipo `a:/` truncaría la clave de dedupe); `abspath` inconsistente en `build_file_index`; colisión sintética con `tex_idx` `None` en el merge; bloque append-owner duplicado; tests de borde de `format_size` y de dos carpetas vacías en el índice.
- **Comentarios obsoletos** que citan clases borradas (`AssetListArea`, `AssetHubDialog`) en `assets.py`, `common/settings.py`, `gate.py`, `hub_ops.py`.

## Preguntas abiertas
**¿Fusionar Pin y Variants?** No decidido. Para iterar lighting sirven los dos, y elegir cuál es trabajo que la herramienta le pasa al artista. Lo que impide una fusión limpia es físico: el Pin no toca la jerarquía y pisa el estado actual al restaurar; Variants reestructura la jerarquía y no pisa nada. Camino intermedio si hace falta: un solo "Guardar estado" que elija el mecanismo según la selección y diga cuál eligió. Disparador: retomarlo solo si en unas semanas de uso el artista duda de cuál usar.

**¿Debe QC Assets comprobar que existe un archivo con ruta absoluta?** Hoy `_classify_texture_path` lo marca "absolute" sin mirar el disco, así que una textura absoluta que falta no aparece como "missing" en QC (el Hub sí lo comprueba). Afecta también a UDIM: un patrón sin ninguna tesela no lo avisa ni Assets ni el QC #14, que se lo deja a Assets. Decidir si "missing" debe ganar a "absolute" (cambia lo que cuenta QC). Visto en la pasada Matwire del 2026-10-30.

## Backlog
- Sentinel Frame: catálogo de formatos cine (2.39 / 1.85 / 2:1) y print (A4 / A3 / Letter); check de "take override drift" tras guardar; presets de safe-area por plataforma versionados; cámaras stage/ortho; confirmar si la ponderación FAIL/WARN del score sigue siendo solo visual.
- Keyboard shortcuts (Export QC, refresh, panel).
- Denoise por AOV (GI, SSS); necesita sondear el param ID.
- Webhook Slack/Teams al hacer Collect o pasar el QC.
- Comp Tag Manager: ver y editar Object Buffer IDs en bloque, detectar duplicados.
- Panel: la cabecera cuenta "QC 9/14" (los WARN pasan) y la pestaña QC "QC 8/14" (solo OK). Unificar el criterio o rotularlos distinto.
- Higiene del repo público: rutas absolutas personales (`/Users/...`) en 10 documentos antiguos de `docs/`. Sustituirlas en el contenido actual; no reescribir la historia.

**Retirado, no reponer:** Force 9:16 (v1.36.4). Lo supera Sentinel Frame y encajaba la resolución a escalones en vez de transponerla.

## Notas de investigación
**RS AOVs**
- IDs de parámetros en `RS_AOV_PARAM_IDS.md`. Las constantes existen en el módulo `c4d` pero no en la documentación del SDK (se descubren filtrando `dir(c4d)` y sondeando).
- Multi-Part EXR sobrescribe la profundidad y compresión por AOV con los ajustes globales.
- Caustics: param 9013 del VideoPost de RS. Volúmenes: buscar RS Environment (1036757) / RS Volume (1038655).
- C4D 2026 usa `GetViewRoot` (no `GetRoot`) y `GetPortValue` (no `GetDefaultValue`).

**Snapshots**
- `BaseBitmap.GetPixelDirect` recorta el HDR a 0-1, así que el tonemap ACES no se puede hacer en el Python de C4D. Solo Python externo + OpenEXR lee el float crudo.
- Pipeline ACES: matriz ACEScg→sRGB, exposición 0.6, curva de tone map, OETF sRGB.

**Compatibilidad de composición**
- Lenscare acepta Z crudo o normalizado; Z Normalized Inverted funciona directamente. Nuke ZDefocus espera Z crudo en unidades de mundo.
- RSMB Pro espera vectores normalizados 0-1 (0.5 = sin movimiento). Nuke VectorBlur espera desplazamiento crudo en píxeles.
- Depth: filtro Center Sample siempre. Motion vectors: filtrado siempre OFF (evita el smearing).
- Fuentes: [AOVs de RS (Maxon)](https://help.maxon.net/r3d/cinema/en-us/#html/Intro+to+AOVs.html), [Compositing Mentor](https://compositingmentor.com/category/cg-compositing-series/), [formato de vectores RSMB](https://revisionfx.com/faq/motion_vector/), [Lenscare](https://www.frischluft.com/lenscare/), y `vprsrenderer.h` / `drsaov.h` en la carpeta de plugins de C4D 2026.
