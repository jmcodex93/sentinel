# Tools quick-wins — cleanup + keyframe shift + render notification (v1.30)

**Fecha**: 2026-07-29
**Estado**: aprobado en brainstorm (decisiones del usuario: limpiadores como botones de Tools, no QC; empty null = sin hijos y sin tags, cascada; material tags = rotos + duplicados exactos; keyframes = todas las pistas de selección+hijos; render notify ON con umbral 30s)
**Contexto**: primera fase del arco "expansión de Tools" (investigación: `docs/research/2026-07-28-c4d-community-tools.md`). El arco completo, en orden acordado: **v1.30 quick-wins (este spec) → v1.31 Batch Rename (form con tokens+preview) → v1.32 RS auto-wire desde carpeta (vía Asset Hub) → v1.33 Recall-checkpoint y/o scene-template**. Base: main con v1.29.0 (Frame v2.1) mergeado y live-verified.

## Decisiones cerradas

1. **Los limpiadores viven en Tools** (botones acción→toast, un undo), NO como QC checks — decisión explícita del usuario contra la recomendación de QC #13/extensión de #7. Sin cambios de registry ni score.
2. **Empty null borrable** = `Onull` sin hijos y sin NINGÚN tag (cualquier tag lo salva: XPresso/constraint/UserData/lo que sea). **Cascada**: un null cuyos descendientes son solo nulls vacíos también cae (evaluación bottom-up).
3. **Material tags borrables** = `Ttexture` con material muerto/None (link roto) + duplicados EXACTOS en el mismo objeto (mismo material Y misma restricción de selección) conservando el ÚLTIMO (el que C4D prioriza). Los huérfanos de selección (restricción → selección inexistente) quedan FUERA (v1).
4. **Keyframe offset/stagger** = TODAS las pistas (`CTrack`: PSR, params, UserData) de la selección + sus hijos, con dedupe (un hijo también seleccionado no se desplaza dos veces). N entero ±. Stagger = 0·N·2N… por objeto RAÍZ de la selección en orden del Object Manager; los hijos heredan el offset de su raíz (no escalonan entre sí).
5. **Render notification** ON por defecto con **umbral 30s** (los test-renders no molestan); toggle persistido en `sentinel_settings.json` (clave `render_notify`). macOS only en v1 (Windows diferido, sin hardware — patrón del repo).

## Diseño

### Motor

- **`scene_tools.py`**: dos núcleos sin-diálogo nuevos (patrón v1.21/v1.23 — dict de estado, jamás un `MessageDialog` en la ruta del op; tests `_forbid_dialog`):
  - `_delete_empty_nulls_core(doc)` — walk bottom-up del árbol; borrable si `GetType()==Onull` y `GetDown() is None` (tras procesar descendientes) y `GetFirstTag() is None`. Todo el lote en un undo (`StartUndo`/`AddUndo(DELETE)`/`Remove`). Devuelve `{"removed": N}`.
  - `_clean_material_tags_core(doc)` — por objeto: pasa 1 borra `Ttexture` cuyo `TEXTURETAG_MATERIAL` resuelve a None; pasa 2 agrupa los restantes por `(material, restricción)` y borra todos menos el último de cada grupo duplicado. Un undo. Devuelve `{"removed_broken": N, "removed_dupes": M}`.
- **`keyframes.py` (módulo nuevo)** — la lógica de recolección/plan pura e importable sin c4d donde sea posible (orden y offsets de stagger, dedupe de jerarquía), con un adapter c4d fino:
  - `shift_object_tracks(doc, objs, frames)` — para cada objeto del conjunto dedupeado (selección + hijos), recorre `GetCTracks()` y desplaza cada `CKey` `frames` frames (vía `CCurve`; N negativo permitido; el desplazamiento usa `BaseTime` derivado del FPS del doc). Un undo para todo el lote.
  - `stagger_object_tracks(doc, roots, frames)` — raíces de selección en orden del Object Manager: raíz i (y todos sus hijos) desplazados `i*frames`. Reusa `shift`.
  - Devuelven `{"objects": N, "keys": M}` para el toast.
- **`renderwatch.py` (módulo nuevo)** — máquina de estados PURA (`RenderWatch`: `idle→rendering→done`; reloj inyectable, pytest cubre umbral/transiciones/duración) + adapter c4d:
  - `tick()` llamado desde el `CoreMessage` del **`FrameSyncMessageData` existente** (ya late a 250 ms; un segundo MessageData gastaría otro plugin-id sin ganancia — alternativa considerada y descartada).
  - Detección: `c4d.CheckIsRunning(c4d.CHECKISRUNNING_EXTERNALRENDERING)`. Transición rendering→idle con duración > **30 s** y `render_notify` activo → notificación.
  - Notificación macOS: `osascript -e 'display notification ...'` (subprocess, best-effort silencioso) con la duración formateada ("Render finished — 12m 34s"). Nada bloquea el tick.

### Ops (`panel_tools_ops.py`)

- `panel/tools/delete_empty_nulls`, `panel/tools/clean_material_tags` — sin payload.
- `panel/tools/keyframe_offset`, `panel/tools/keyframe_stagger` — payload `{"frames": int}` (validado: entero, != 0, clamp razonable ±10000); sin selección o sin keys → estado warn (toast accionable), nunca un diálogo.
- El toggle `render_notify` entra por el op de Settings existente (`form/settings/*`) + su checkbox.

### UI (panel SPA)

- **Tools** gana el grupo **Cleanup** (Delete Empty Nulls · Clean Material Tags) tras Layout & Hierarchy — `TOOL_GROUPS` en `panelTools.ts`.
- **Animation** gana una fila con campo numérico **Frames** (entero ±, default 5, estado local de `ToolsSection`) + botones **Offset** y **Stagger**. Primer control con parámetro de Tools; mismo lock `busyTool` y toasts.
- `toolToast`: copys nuevas — éxito con conteos ("Removed 7 empty nulls", "Removed 3 broken + 2 duplicate tags", "Shifted 240 keys across 12 objects (stagger 5f)") y warns accionables ("Select one or more animated objects first", "No empty nulls found", …).
- **Settings** (form nativo + página SPA): checkbox "Notify when render finishes (>30s)".

## Errores / no-regresión

- Cero cambios en QC/registry/score, cero confirms (todo Cmd+Z-able; la notificación no muta nada).
- Las herramientas existentes de Tools no cambian de op ni de copy.
- El tick de `FrameSyncMessageData` no puede romper el auto-sync: el render-watch va en try/except propio y jamás lanza.

## Verificación

- pytest: cascada/tags de empty nulls y dedupe de material tags (fakes de árbol), plan de stagger puro (orden, offsets, dedupe selección+hijos), máquina de estados del render-watch (umbral 30s, duraciones, toggle), contratos de ops (`_forbid_dialog`, validación de `frames`).
- Live (matriz): escena con nulls anidados vacíos + uno salvado por tag XPresso → borra los correctos, un Cmd+Z; tags rotos+duplicados → conteos correctos; offset ±N y stagger sobre un rig con hijos animados (dedupe verificado); render PV corto (sin notificación) y largo >30s (notificación con duración); toggle OFF la silencia.

## Fuera de alcance (backlog del arco)

- Batch Rename con tokens (v1.31), RS auto-wire (v1.32), Recall/template (v1.33).
- Huérfanos de restricción de selección en material tags; Windows notification; umbral configurable.
