# Fase 6.2 — Panel SPA: sección Render

**Fecha**: 2026-07-22
**Estado**: aprobado en brainstorm (companion visual — mockups en `.superpowers/brainstorm/51945-1784736330/content/render-layout.html`)
**Contexto**: tercera sección de contenido del panel SPA (tras Overview 6.0 y QC 6.1, v1.19/v1.20). Rediseño no port 1:1. Spec madre `2026-07-21-panel-spa-design.md`.

## Decisiones cerradas (brainstorm)

1. **Layout = bloques apilados (A) con status en la cabecera de cada bloque** — coherente con la sección QC; la sección Render es de ACCIÓN (el artista viene a hacer algo), así que acción directa sin plegar. El status en cabecera da el "de un vistazo" sin renunciar a la acción directa. Orden: Preset → Sentinel Frame → AOVs → Snapshots → Post-Render.
2. **Sentinel Frame = mínimo**: estado (¿hay tag? ¿en qué cámara?) + "Add to camera" + "Select tag" (lo selecciona para editarlo en el Attribute Manager). La config fina (formatos/nudges/HUD) sigue viviendo en el tag — su sitio natural.
3. **Show AOVs = expand inline** (lista + target + light groups + cobertura de tier), como el Info de QC. Sin popups.
4. **Destructivas con confirm inline** (contrato palette): Reset All (reescribe todos los presets), Force 9:16 (cambia resolución), aplicar tier AOV (sobrescribe el setup de AOVs).
5. **Validate = deep-link** a la página Reports → Render Validation (ya existe, fase 1.9/2). No se reimplementa.

## Diseño

### 1. Ops (`panel_render_ops.py`, nuevo — adaptadores finos, cero lógica duplicada)

- **`panel/render`** (read-only, bloques AISLADOS como `panel/overview`): estado de los 5 bloques:
  ```
  { "preset": {"active_name","resolution","fps","preset_names":[...]} | null,
    "frame":  {"has_tag": bool, "camera_name": str|null, "format_count": int|null} | null,
    "aovs":   {"count","multipart": bool,"target_name","light_groups": bool} | null,
    "snapshots": {"dir","origin": "auto"|"manual","watch_enabled": bool} | null,
    "postrender": {"last_report_age": str|null} | null }
  ```
  Fuentes: preset = `doc.GetActiveRenderData()` + iterate render datas; frame = frame-tag detector (grep `frame_tag`/`_add_sentinel_frame_tag`); aovs = `aovs.get_rs_aovs`/`get_aov_multipart`/`check_rs_aovs`; snapshots = `flows.get_effective_snapshot_dir()` + watch setting; postrender = último render-history sidecar. Nada inventado.
- **Mutaciones** (cada una → `{ok, error?, stamp, render}`; render = payload fresco embebido):
  - `panel/render/set_preset {preset}` — reutiliza el motor de aplicación de preset del panel nativo (`_apply_preset`/`scene_tools`).
  - `panel/render/reset_all` ⚠ — reutiliza `scene_tools._force_render_settings` (que hoy tiene `QuestionDialog`; el op NO abre popup — la confirmación va inline en la SPA vía el contrato; el op ejecuta el reset directamente cuando llega `confirm:true`).
  - `panel/render/force_vertical` ⚠ — reutiliza el motor de Force 9:16.
  - `panel/render/add_frame_tag` — `scene_tools._add_sentinel_frame_tag(doc)`.
  - `panel/render/select_frame_tag` — `SetActiveTag` del frame tag existente (`{ok:False, error:"no_tag"}` si no hay).
  - `panel/render/aov_tier {tier}` ⚠ — `aovs.force_aov_tier(doc, tier_list)` (tier ∈ essentials/production/light_groups; `_build_tier_list`).
  - `panel/render/toggle_multipart` — `aovs.set_scene_multipart(doc, not current)`.
  - `panel/render/toggle_watchfolder` — persiste el flag (`GlobalSettings`, misma clave que el panel nativo).
  - `panel/render/save_still` — `scene_tools._take_renderview_snapshot(artist_name)` (acción de filesystem+PV; devuelve mensaje).
  - `panel/render/open_folder` — abre el dir efectivo (opener cross-platform existente).
- **Confirm contract**: las ⚠ devuelven `{ok:False, error:"confirm_required", confirm_label}` sin `confirm:true` (patrón palette/gate). Validate → `runPaletteAction("open_reports_render_validation")` (id ya existe).
- Registrar `PANEL_RENDER_OPS` y mergear en `reports_dialog._OPS`.

### 2. SPA — `RenderSection` (reemplaza el placeholder de la sección Render)

- Bloques apilados, cada uno cabecera de status + acciones. Componentes: `RenderSection.tsx` + sub-bloques (`PresetBlock`, `FrameBlock`, `AovBlock`, `SnapshotBlock`, `PostRenderBlock`) o un `RenderBlock` genérico — a criterio de implementación, pero cada bloque testeable.
- **Preset**: `Render · 1920×1080 · 25fps` + `<select>` de preset (los nombres del payload) + Reset All ⚠ + Force 9:16 ⚠.
- **Sentinel Frame**: `sin frame tag` / `en <cámara> · N formatos` + Add to camera + Select tag (deshabilitado si no hay tag).
- **AOVs**: `N AOVs · Multi-Part ON/OFF · target` + Show AOVs (expand inline con la lista) + Essentials/Production/Light Groups ⚠ + toggle Multi-Part.
- **Snapshots**: `<dir efectivo>` + chip origen (auto/manual) + Save Still + Open Folder + toggle Watch.
- **Post-Render**: `último informe: hace Xh` / `sin informe` + Validate render output → deep-link.
- Fetch `panel/render` al entrar + en cambio de stamp; mutaciones → toast + aplicar `render` embebido + re-anclar stamp; confirm inline para las ⚠ (reutilizar el patrón de QC/Overview). Bloque null → estado "no disponible" (resiliencia como overview).
- Badge del rail Render: opcional, no en 6.2 (el rail ya existe; render no tiene un contador de estado obvio — dejar sin badge).
- Lógica pura (formato de status por bloque, qué acciones/confirm por bloque) en `panelRender.ts` + vitest.

## Manejo de errores

- Ops nunca lanzan; bloques aislados. Redshift no disponible → aovs block `{error:"redshift_unavailable"}` renderizado como nota, no crash. save_still/open_folder devuelven mensaje (toast). Confirm contract para destructivas.

## Fuera de alcance

- Config fina del Sentinel Frame (vive en el tag/AM).
- Reimplementar Multi-Format/validate (se reutiliza/deep-linkea).
- Compositor target / Multi-Part default de estudio (viven en Settings — 6.3/6.4).
- Tocar los motores (aovs/frame_tag/snapshots/postrender/presets — solo consumir; si `_force_render_settings`/`_apply_preset` están acoplados a UI con `QuestionDialog`, extraer un núcleo sin diálogo reutilizable por op y nativo — mejora mínima justificada, no reescritura).
- Retirar la pestaña Render nativa (6.4).

## Verificación

- pytest: `panel/render` (bloques aislados, un fallo no blanquea; fuentes reales), cada mutación (contrato, no_document, confirm de las ⚠, no_tag en select_frame_tag), redshift-unavailable degradado. Harness fake-c4d.
- vitest: status por bloque + acciones/confirm por bloque (pura), confirm gating.
- Live C4D (SHOT_18): status de los 5 bloques correcto; cambiar preset (resolución cambia); aplicar Production AOVs (con confirm) → N AOVs sube; toggle Multi-Part/Watch; Add frame tag → status pasa a "en <cámara>"; Save Still; Validate abre Reports; sin popups; un Cmd+Z revierte una mutación de preset/AOV.
