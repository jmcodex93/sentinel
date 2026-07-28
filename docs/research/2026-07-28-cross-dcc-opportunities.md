# Cross-DCC pipeline opportunities research (2026-07-28)

Investigación: qué tools de otros DCC (Maya/Houdini/Nuke/Blender/Unreal/review) faltan en C4D y son construibles en el pipeline de Sentinel (Python + SPA webview + motores puros existentes).

## Hallazgo central

Cada DCC tiene una categoría madura que C4D visiblemente no tiene: burn-ins/playblast (Maya), wedge renders (Houdini), comp-handoff scripting (Nuke), review A/B (RV). Los motores existentes de Sentinel (snapshot pipeline, imagemeta, Take system, SPA webview) hacen varios construibles sin acceso a engine.

## Shortlist rankeada "build this in C4D"

1. **Burn-ins de review sellados en píxeles** (patrón Maya Zurbrigg/Shot Mask): estampar artista/shot/take/QC-score/frame sobre los Save Stills y PNGs del watchfolder (stdlib/PIL text overlay). Sentinel ya posee el pipeline de snapshots Y toda la metadata. **Feasibility 5**. Riesgo: font/render de texto cross-platform (Inter ya empaquetada). C4D solo tiene shot-masks de viewport (Super Mask), no burn-ins sellados con metadata de pipeline — gap confirmado.
2. **Review viewer local — A/B wipe + contact sheet en el SPA** (patrón RV/OpenRV, Apache-2.0 desde 2023): RV-lite sobre stills/snapshots por versión, en el webview existente. **Feasibility 5**. Riesgo: scope creep hacia un player completo. El patrón portable es wipe+contact-sheet, no el tool.
3. **Generador de handoff Nuke .nk / AE .jsx**: pre-cablear Read nodes por AOV RS (paths ya conocidos por `aovs.py`) + cámara bakeada → comp abre lista para trabajar en vez de cablear 15 capas a mano. **Feasibility 4**. Riesgo: sintaxis exacta de nodos por versión; es "buen punto de partida", no garantía. Refs: gist "bake camera with Redshift metadata" (Nuke), CG Record multipass workflow.
4. **Cryptomatte manifest QC**: extender el parsing stdlib de EXR (estilo `imagemeta.py`) para leer el manifest Cryptomatte + reportar capas/counts en Post-Render Validation. **Feasibility 3-4**. Riesgo: parsing de atributos/multipart EXR sin librería completa no es trivial. No existe tool standalone que haga esto — gap genuino.
5. **Wedge / lookdev batch renders** (patrón Houdini Wedge TOP): barrer un parámetro (material/luz) por una lista de valores → stills batch → grid contact-sheet (casa con #2). El sistema de Takes hijos parametrizados de multi-format es el mismo mecanismo apuntado a lookdev. **Feasibility 4**. Riesgo: la UI genérica "qué parámetro, qué valores" es más diseño de producto que ingeniería.
6. **Batch shot setup desde CSV** (patrón Maya shot-list): CSV de shot IDs → cámaras/Takes/output paths en bulk. **Feasibility 4**. Riesgo: validar la demanda real (¿llegan shot lists como spreadsheet?).

## Descartados

- Node Wrangler-style para el editor de nodos RS (feasibility 1-2 — el Python de C4D no tiene hook en la capa de interacción del node editor).
- Farm submission tipo Movie Render Queue/Deadline (infra fuera del alcance).
- Filecache version-pinning de Houdini (mismatch con workflow mograph sin sims pesadas).

## Fuentes clave

Zurbrigg Advanced Playblast · DuBlast-Maya · SideFX Wedge TOP docs · CG Record RS→Nuke multipass · gist bake-camera-RS-metadata · Foundry Cryptomatte docs · OpenRV manual (ASWF) · Epic Movie Render Queue docs · Lesterbanks Super Mask (confirma el gap de burn-in en C4D).
