# Auditoria supervisor tecnico — Sentinel

Fecha: 2026-06-12  
Rol: Head of Production / Supervisor tecnico de estudio motion design top  
Veredicto global: **FIX FIRST**. No lo adoptaria manana en una entrega con cliente sin una semana de estabilizacion y pruebas.

## TL;DR (5 lineas)

1. Sentinel tiene una identidad potente: watchdog + delivery multi-formato, y las ultimas features atacan problemas reales de estudio (`CLAUDE.md:4`, `CLAUDE.md:20`).
2. No hay evidencia de verificacion automatizada: el checklist oficial esta todo sin marcar (`CLAUDE.md:203`) y el repo no contiene suite de tests; por criterio de auditoria, ninguna feature queda verificada.
3. Los loops de confianza estan rotos: Save Version resume 11 checks (`plugin/sentinel_panel.pyp:2803`), QC Report no exporta Cross-Aspect (`plugin/sentinel_panel.pyp:9553`), y Scene Collector preflight solo revisa un subconjunto (`plugin/sentinel_panel.pyp:6839`).
4. El working tree mezcla release v1.5.7 con trabajo v1.5.8/v1.6.0 sin commitear: `git status` muestra `M plugin/sentinel_panel.pyp`, recursos Camera Frame `??`, y borrado del instalador trackeado `D INSTALL_YS_GUARDIAN.bat`.
5. Adoptable, si: pero primero hay que cerrar release hygiene, instalacion C4D 2026 macOS/Windows, y una escalera de verificacion tipo OctaneLens (`../11 C4D DEV/OctaneLens/CLAUDE.md:111`).

## Veredicto por feature

| Feature listada en `CLAUDE.md` What Works | Veredicto | Evidencia concreta | Por que |
|---|---:|---|---|
| All 12 Quality Checks: lights, visibility, keyframes, camera shift, presets, assets/textures, unused materials, default names, output paths, take validation, FPS/frame range, cross-aspect safe area (`CLAUDE.md:81`) | **FIX FIRST** | UI refresh ejecuta 12 checks (`plugin/sentinel_panel.pyp:8683`), pero Save Version sigue en 11 (`plugin/sentinel_panel.pyp:2803`) y el checklist manual esta sin marcar (`CLAUDE.md:203`). | Como panel de supervision promete 12, pero los artefactos de entrega no comparten la misma verdad. No confiaria en el score esta noche. |
| Auto-fix: lights, camera shift, unused materials, FPS/range (`CLAUDE.md:82`) | **FIX FIRST** | Funciones existen (`plugin/sentinel_panel.pyp:2230`, `plugin/sentinel_panel.pyp:2303`, `plugin/sentinel_panel.pyp:2337`, `plugin/sentinel_panel.pyp:2358`); verificacion pendiente (`CLAUDE.md:207`). | El potencial es bueno, pero un auto-fix sin prueba fixture puede destruir una escena a horas de delivery. |
| Smart Save Version (`CLAUDE.md:83`) | **FIX FIRST** | Orquestador existe (`plugin/sentinel_panel.pyp:3009`), pero `_build_qc_summary` excluye QC #12 y documenta "11 QC checks" (`plugin/sentinel_panel.pyp:2803`). | Guardar versiones con score incorrecto es peor que no tener score: genera confianza falsa. |
| Review Status Tags (`CLAUDE.md:84`) | **FIX FIRST** | Parser/build filename existe (`plugin/sentinel_panel.pyp:2549`, `plugin/sentinel_panel.pyp:2575`); dialogo documenta status (`plugin/sentinel_panel.pyp:3014`). | Buena feature de mograph, pero depende del Smart Save no verificado. |
| Continue from this version (`CLAUDE.md:85`) | **FIX FIRST** | Prompt/continuacion tras TR/CR/FINAL existe (`plugin/sentinel_panel.pyp:9685`). | Protege snapshots de review, pero no hay test de overwrite, cancel, path ni version bump mixto (`CLAUDE.md:218`). |
| Last version pillbox (`CLAUDE.md:86`) | **FIX FIRST** | Update de caption existe (`plugin/sentinel_panel.pyp:8480`); README lo promete (`README.md:151`). | UX util, pero depende de history sidecar y no hay verificacion automatizada de estados vacios/tiempo. |
| Browse Recent Versions (`CLAUDE.md:87`) | **FIX FIRST** | `HistoryArea` existe (`plugin/sentinel_panel.pyp:7379`), filtro se refresca (`plugin/sentinel_panel.pyp:8530`). | Necesita fixtures de history JSON, archivos borrados, mismo doc y unsaved changes antes de confiar en LoadFile. |
| Scene Notes & TODOs (`CLAUDE.md:88`) | **FIX FIRST** | Helpers/dialogo existen (`plugin/sentinel_panel.pyp:3164`, `plugin/sentinel_panel.pyp:3511`); collector copia sidecar (`plugin/sentinel_panel.pyp:7006`). | Buena disciplina de produccion, pero hay que probar persistencia/cancel/copy; checklist pendiente (`CLAUDE.md:225`). |
| Scene Collector clean delivery naming (`CLAUDE.md:89`) | **FIX FIRST** | Captura nombre original y clean base antes de SaveProject (`plugin/sentinel_panel.pyp:6817`). | La idea es correcta, pero Scene Collector no hace preflight completo de 12 checks (`plugin/sentinel_panel.pyp:6839`). |
| Tabbed UI (`CLAUDE.md:90`) | **FIX FIRST** | Layout dinamico descrito en codigo (`plugin/sentinel_panel.pyp:8196`) y limitacion C4D documentada (`CLAUDE.md:110`). | Aceptable como UI, pero sin prueba de carga/rebuild por tab; cualquier ID roto bloquea produccion. |
| QC Report Export (`CLAUDE.md:91`) | **FIX FIRST** | Export existe (`plugin/sentinel_panel.pyp:2375`), pero los resultados pasados no incluyen `_cross_aspect_bad` (`plugin/sentinel_panel.pyp:9553`) y el summary cuenta solo lo exportado (`plugin/sentinel_panel.pyp:2468`). | Para supervisor, un report que omite QC #12 no es report de entrega. |
| RS AOV Management (`CLAUDE.md:92`) | **FIX FIRST** | Definiciones y force tier existen (`plugin/sentinel_panel.pyp:1694`, `plugin/sentinel_panel.pyp:1863`); ROADMAP declara IDs documentados (`ROADMAP.md:50`). | Central para delivery, pero no hay test Redshift ni fixture de AOVs; mantener como feature core, no como garantizada. |
| Light Groups AOV (`CLAUDE.md:93`) | **FIX FIRST** | Toggle en Beauty AOV existe (`plugin/sentinel_panel.pyp:9760`, `plugin/sentinel_panel.pyp:9807`). | Feature correcta para comp, pero necesita escena fixture con grouped/ungrouped lights y verificacion de no explotar AOVs. |
| Scene Collector (`CLAUDE.md:94`) | **FIX FIRST** | Usa SaveProject + manifest (`plugin/sentinel_panel.pyp:6890`, `plugin/sentinel_panel.pyp:6957`), pero preflight solo lista lights/vis/textures/unused/names/takes/output (`plugin/sentinel_panel.pyp:6839`). | La feature se vende como pre-flight QC; si no revisa keyframes, camera shift, presets, FPS y safe area, no es gate de entrega. |
| Take Validation (`CLAUDE.md:95`) | **FIX FIRST** | `check_takes` existe (`plugin/sentinel_panel.pyp:1972`); README promete camera + `$take` (`README.md:34`). | Importante para multi-take delivery, pero no hay pruebas con herencia de render data ni paths por take. |
| Render Presets (`CLAUDE.md:96`) | **FIX FIRST** | Apply/reset/toggle existen (`plugin/sentinel_panel.pyp:8619`, `plugin/sentinel_panel.pyp:10017`, `plugin/sentinel_panel.pyp:10085`). | Util, pero aun hay drift documental: README habla de C4D 2024+ y presets fijos; roadmap backlog pide presets dinamicos (`ROADMAP.md:570`). |
| Multi-Format Render Setup (`CLAUDE.md:97`) | **FIX FIRST** | Orquestador existe (`plugin/sentinel_panel.pyp:4185`), pero working tree introduce modo `preserve_vertical` v1.5.8 mientras `PLUGIN_NAME` sigue v1.5.7 (`plugin/sentinel_panel.pyp:53`, `plugin/sentinel_panel.pyp:3944`). | Es el futuro correcto del producto, pero ahora esta mezclado con WIP no releaseado. |
| Cross-Aspect Safe Area QC (`CLAUDE.md:98`) | **FIX FIRST** | Check existe (`plugin/sentinel_panel.pyp:5163`) y auto-refresh usa current frame (`plugin/sentinel_panel.pyp:8694`). | Excelente idea, pero no entra en Save Version ni QC Report; como gate de delivery aun no cierra el loop. |
| Safe-Area Viewport Overlay (`CLAUDE.md:99`) | **FIX FIRST** | State/ObjectData existe (`plugin/sentinel_panel.pyp:5372`, `plugin/sentinel_panel.pyp:5473`); working tree anade mask v1.5.8 (`plugin/sentinel_panel.pyp:8063`). | Visualmente valioso, pero sin verificacion de viewport C4D 2026 y con WIP mezclado. |
| Texture Repathing (`CLAUDE.md:100`) | **FIX FIRST** | Scan/writer/dialog existen (`plugin/sentinel_panel.pyp:1131`, `plugin/sentinel_panel.pyp:1424`, `plugin/sentinel_panel.pyp:6223`); fue commit grande `8273b20` tras tres commits WIP (`40047a1`, `eb7b984`, `69f249f`). | Alta prioridad real. Pero toca node graphs, undo y paths Windows: sin fixtures automatizados o escenas probe, no se shippea como herramienta de batch. |
| Snapshot System (`CLAUDE.md:101`) | **FIX FIRST** | Converter ACES existe (`plugin/exr_converter_external.py:23`, `plugin/exr_converter_external.py:70`); README exige deps inconsistentes entre Pillow/NumPy y OpenEXR (`README.md:244`, `README.md:262`). | Para cliente, color review es sensible. Sin test de color/EXR y con setup manual Redshift, no lo usaria como delivery authority. |
| Scene Tools: Hierarchy, H->Layers, Solo, Drop, Vibrate, ABC Retime, Camera Rigs (`CLAUDE.md:102`) | **KILL** | Botones/funciones existen (`README.md:327`, `plugin/sentinel_panel.pyp:10274`, `plugin/sentinel_panel.pyp:10661`, `plugin/sentinel_panel.pyp:10821`). | Son utilidades historicas, no watchdog ni delivery multi-formato. Mantenerlas aumenta superficie de rotura; mover a legacy/unsupported o plugin separado. |
| CoreMessage dirty-flag (`CLAUDE.md:103`) | **FIX FIRST** | CoreMessage marca dirty (`plugin/sentinel_panel.pyp:8996`), pero Timer llama `_refresh()` igualmente y `_refresh()` limpia cache cada vez que pasa cooldown (`plugin/sentinel_panel.pyp:8989`, `plugin/sentinel_panel.pyp:8679`). | La intencion es buena; la implementacion actual aun se comporta como polling throttled. Medir antes de vender "no polling waste". |
| Cross-platform macOS + Windows (`CLAUDE.md:104`) | **FIX FIRST** | `open_in_explorer` es multiplataforma (`plugin/sentinel_panel.pyp:21`), pero instalador Windows esta hardcoded a C4D 2024 (`INSTALL_SENTINEL.bat:23`) y el manual macOS es copiar carpeta (`README.md:259`). | No sobrevive primer contacto en maquinas limpias 2026. Necesita installer/verify para macOS y Windows 2026. |

## Documentacion vs benchmark OctaneLens

OctaneLens esta mejor separado para adopcion por un estudio:

- README operativo y acotado: declara layout y workflow diario sin tragarse todo el changelog (`../11 C4D DEV/OctaneLens/README.md:5`, `../11 C4D DEV/OctaneLens/README.md:9`).
- CLAUDE dev contiene comandos y una verification ladder clara, con rungs ejecutables sin Octane (`../11 C4D DEV/OctaneLens/CLAUDE.md:35`, `../11 C4D DEV/OctaneLens/CLAUDE.md:111`).
- Guia de controles artista separada, con rango/default/sweet spot/validacion por control (`../11 C4D DEV/OctaneLens/docs/controls_guide.md:1`, `../11 C4D DEV/OctaneLens/docs/controls_guide.md:15`).
- Guia visual con assets y paginas artist-facing (`../11 C4D DEV/OctaneLens/docs/visual-guide/index.md:1`, `../11 C4D DEV/OctaneLens/docs/visual-guide/index.md:20`).

Sentinel no esta a ese nivel:

- No existe `docs/` en el repo antes de este informe; README mezcla usuario, instalacion, changelog, arquitectura y soporte.
- `CLAUDE.md` es fuente de verdad, pero tambien contiene checklist manual sin completar (`CLAUDE.md:203`) y referencias viejas como "All 10 QC checks" (`CLAUDE.md:55`).
- README todavia tiene drift: Scene Collector dice "Runs all 10 QC checks" (`README.md:136`) aunque el producto declara 12 (`README.md:287`).
- Guia de instalacion referencia un `RUN_INSTALLER.bat` inexistente en el listado trackeado/untrackeado (`INSTALLATION_README.md:77`), y el instalador nuevo no esta trackeado segun `git status`.
- No hay una guia visual de primer contacto para: activar plugin, primera escena, corregir un fallo QC, generar formatos, marcar safe-area subjects, exportar report, collect delivery.

Mi veredicto documental: **FIX FIRST**. OctaneLens parece un producto tecnico con escalera de prueba; Sentinel parece un plugin potente con diario de desarrollo y marketing mezclados.

## Roadmap reordenado con justificacion

1. **Release gate v1.5.7 real**: congelar o sacar a una rama todo v1.5.8/v1.6.0 del working tree; restaurar/commitear estrategia de instalador; versionar docs y codigo juntos. Justificacion: ahora `plugin/sentinel_panel.pyp` contiene Camera Frame v1.6.0 (`plugin/sentinel_panel.pyp:78`) y Preserve Vertical v1.5.8 (`plugin/sentinel_panel.pyp:3944`) mientras el producto se llama v1.5.7 (`plugin/sentinel_panel.pyp:53`).
2. **Verification ladder antes de nuevas features**: crear tests para helpers puros y fixtures C4D manuales reproducibles: version filenames, history/notes JSON, texture path classification, relative paths Windows/macOS, multiformat math, safe-area math, EXR transform smoke. Justificacion: el criterio actual esta en una checklist sin ejecutar (`CLAUDE.md:203`); OctaneLens demuestra el formato correcto (`../11 C4D DEV/OctaneLens/CLAUDE.md:111`).
3. **Unificar los 12 checks en todos los artefactos**: panel, Save Version, QC Report, Scene Collector manifest/preflight. Justificacion: el producto es watchdog; hoy los outputs criticos divergen (`plugin/sentinel_panel.pyp:2803`, `plugin/sentinel_panel.pyp:9553`, `plugin/sentinel_panel.pyp:6839`).
4. **Onboarding C4D 2026 macOS/Windows**: instalador Windows 2026 configurable, guia macOS real, smoke test "fresh machine", deps OpenEXR/Pillow/NumPy coherentes. Justificacion: README vende C4D 2024/2026 (`README.md:17`), pero el instalador apunta a 2024 (`INSTALL_SENTINEL.bat:23`).
5. **Post-Render Validation**: subirlo por encima de Scene Complexity. Justificacion: es core delivery y el roadmap ya explica el coste de frames faltantes tras 12h (`ROADMAP.md:543`).
6. **Texture Repathing hardening**: mantenerlo como prioridad alta, pero solo con escenas probe por renderer y undo verification. Justificacion: cierra QC #6 (`ROADMAP.md:95`) y toca el mayor riesgo de delivery.
7. **Scene Complexity Budget**: util, pero despues de post-render y repathing. Justificacion: ayuda antes de render, pero no valida entrega final (`ROADMAP.md:552`).
8. **FPS Settings UI + Review Slate**: hacer despues de gates; son polish de workflows ya existentes (`ROADMAP.md:523`, `ROADMAP.md:531`).
9. **Template configurable + dynamic presets**: priorizar sobre Slack/keyboard/denoise porque afecta delivery real (`ROADMAP.md:567`, `ROADMAP.md:570`).
10. **MessageData, Slack/Teams, Keyboard Shortcuts, Denoise, Comp Tag Manager**: backlog bajo hasta que el core sea verificable (`ROADMAP.md:564`, `ROADMAP.md:573`, `ROADMAP.md:576`, `ROADMAP.md:579`, `ROADMAP.md:582`).
11. **Scene Tools legacy**: no invertir roadmap salvo bug critico. Justificacion: no acerca la identidad watchdog + multi-format delivery.

## Riesgos top-3

1. **Confianza falsa en QC/delivery**. El panel dice 12 checks, pero Save Version y QC Report no cubren todos los 12 (`plugin/sentinel_panel.pyp:2803`, `plugin/sentinel_panel.pyp:9553`). En un estudio esto termina en "el report estaba verde" mientras una safe-area o FPS issue sale al cliente.
2. **Release contaminado por WIP**. Working tree mezcla v1.5.7 con v1.5.8/v1.6.0 (`plugin/sentinel_panel.pyp:78`, `plugin/sentinel_panel.pyp:3944`), recursos nuevos sin trackear, docs modificados y un instalador trackeado borrado. Eso es senal de alarma de disciplina, no detalle.
3. **Onboarding fragil**. Instalador Windows hardcoded a Cinema 4D 2024 (`INSTALL_SENTINEL.bat:23`), README/manual macOS generico (`README.md:259`), guia de instalacion con archivo inexistente (`INSTALLATION_README.md:77`) y dependencias documentadas de forma inconsistente (`README.md:244`, `README.md:262`).

## Las 3 acciones de la semana

1. **Lunes-martes: cerrar release hygiene**. Crear rama para Camera Frame/v1.6, dejar `main` limpio, alinear `PLUGIN_NAME`, README, CLAUDE, ROADMAP e instaladores, y producir un `git status` limpio salvo este informe.
2. **Miercoles-jueves: construir verificacion minima**. Tests puros para funciones sin C4D; escenas/guia de smoke manual para C4D 2026; cada item critico del checklist de `CLAUDE.md:203` debe quedar con evidencia, no con memoria.
3. **Viernes: reparar los artefactos de delivery**. Save Version, QC Report y Scene Collector deben usar la misma lista canonical de 12 checks y exportar Cross-Aspect/FPS/Take/Output de forma consistente; despues validar en una escena limpia macOS y una Windows 2026.
