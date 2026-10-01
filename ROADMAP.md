# Sentinel — Roadmap

Solo lo pendiente. Lo entregado, con su porqué, está en [`docs/HISTORY.md`](docs/HISTORY.md).

## Estado (2026-10-01)
- `main`: **v1.39.0**. Incluye la estabilización para beta (antes rama `codex/product-readiness`) y el endurecimiento de la aceptación en Windows. Objetivo del estudio: **C4D 2026.4.0**.
- Aceptada en Windows 11 + C4D 2026.4.0 (perfil limpio, Sentinel como único plugin de terceros) tras tres rondas externas, y verificada en vivo en macOS + C4D 2026.304. Evidencia: [`docs/audit/2026-09-24-windows-acceptance.md`](docs/audit/2026-09-24-windows-acceptance.md), [product readiness](docs/audit/2026-09-05-product-readiness.md), [beta](docs/audit/2026-09-05-beta-acceptance.md), [GUI](docs/audit/2026-09-05-gui-acceptance.md).
- CI en cada PR y push a `main`: pytest en Linux, macOS y Windows + web.

## Para cerrar la beta
- [ ] Windows: comprobar a ojo la casilla "Save snapshots as EXR" de RenderView en la máquina de pruebas.
- [ ] Windows: repetir Frame (expandir el tag) y Hub (Switch res) con los plugins habituales del estudio cargados; la ronda 3 los probó con Sentinel solo.
- [ ] `http.handler_failed` visto una vez en la consola de Windows: capturar el texto completo si reaparece (no reproducido en macOS).
- [ ] Usabilidad: la ventana de Settings ya abierta puede quedar detrás del panel al pedirla otra vez (`open_form` reutiliza sin traer al frente; no romper la protección contra cerrar/abrir un HTML viewer vivo). El nombre de artista del Overview no se refresca hasta reabrir el panel.

**Limitación conocida, no se persigue:** en Windows con C4D 2026.3.4, expandir el tag Sentinel Frame en el Attribute Manager puede cerrar C4D (llamada nativa a dirección nula en `gui.module`, sin Python en la pila, causa sin aislar). No ocurre en 2026.4.0 ni en macOS.

## Antes de distribuir comercialmente
Detalle en la tabla *Before distributing a commercial product* del informe de product-readiness.
- [ ] Titularidad y licencia: el `LICENSE` nombra a Javier Melgar / Yambo Studio. Sentinel parte de YS Guardian v1.0 (5 checks, presets, herramientas de escena, snapshots) y todo lo posterior es desarrollo propio; hay que acordar con los titulares los derechos sobre el código original y la licencia del producto.
- [ ] `abc_retime` (AXISFX): permiso de redistribución o sacarlo del paquete.
- [ ] Assets `.c4d` empaquetados: origen y permiso de cada uno. (Los iconos son propios desde la v1.39.)
- [ ] Plugin IDs: confirmar el registro con Maxon.
- [ ] Matriz soportada con nombre (C4D / Redshift / SO) y plantilla de soporte.

## Features siguientes
- **QC #14 — assets que declara el proyecto.** Necesita su propio spec (identidad, baseline y fontanería de informe). Aporta valor aunque no se use "nuevo shot".
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

## Backlog
- Sentinel Frame: catálogo de formatos cine (2.39 / 1.85 / 2:1) y print (A4 / A3 / Letter); check de "take override drift" tras guardar; presets de safe-area por plataforma versionados; cámaras stage/ortho; confirmar si la ponderación FAIL/WARN del score sigue siendo solo visual.
- Keyboard shortcuts (Export QC, refresh, panel).
- Denoise por AOV (GI, SSS); necesita sondear el param ID.
- Webhook Slack/Teams al hacer Collect o pasar el QC.
- Comp Tag Manager: ver y editar Object Buffer IDs en bloque, detectar duplicados.
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
