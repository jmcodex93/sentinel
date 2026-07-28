# C4D community tools research (2026-07-28)

Investigación para la expansión de la sección Tools de Sentinel: qué scripts/plugins usa la comunidad C4D a diario (2023-2026) y cuáles merecen absorberse. Nota del researcher: reddit/core4d bloqueados en sandbox — evidencia por convergencia de fuentes (roundups, Gumroad, foros adyacentes), no citas literales de hilos.

## Señales transversales

- **Ecosistema de scripts fragmentado**: el hub más citado es `aturtur/cinema4d-scripts` (GitHub, ~430 stars, MIT, activo en 2024) y Boghma community hub (30+ plugins free). No hay "awesome-list" dominante.
- **Rename/cleanup = la categoría más reinventada** (4+ renamers independientes, 3+ cleanup scripts casi idénticos) → dolor persistente real, no resuelto.
- **Keyframe stagger/offset y project-setup templating = los nichos menos servidos comercialmente** → máxima diferenciación, mínimo riesgo de reinventar una rueda madura.
- **Sentinel ya supera al mercado** en safe-frame/HUD (mc_Camera, SafeFrame de N. Rosenstein son point-solutions más simples que el Sentinel Frame) y en unused-materials/empty-null hygiene (KTools, Remove Unused Material Tags).

## Top candidatos por categoría (resumen)

- **Selection/Solo**: Magic Solo (Nitro4D, ~duplicado de nuestro Solo Layers); Rocket Lasso **Recall** (checkpoint restaurable por tag antes de bakes destructivos, 4.9/5) — https://rocketlasso.com/recallinfo
- **Naming**: Plus Renamer (GSG Plus $399/yr), Nick Namer (Gumroad), Renamer-Pack (Lasse Lauch), Naming Tool nativo como baseline.
- **Keyframes**: Signal (GSG, procedural, producto entero — contexto no target); **Offset Animation Tracks** (Orestis K., Gumroad) — batch-shift de keyframes por N frames, patrón pequeño y absorbible — https://orestiskon.gumroad.com/l/c4doffset
- **Cleanup**: KTools (selection tags vacíos, broken material tags); **Remove Unused Material Tags** (antronero, verificado C4D 2025); **Delete Empty Nulls** (múltiples variantes free — señal de demanda recurrente); Clean Material (Boghma, free).
- **Render/output**: **Render Beep** (notificación al terminar render — trivial, alto valor diario); PV RenderQueue (superseded por el Render Queue nativo).
- **RS-específico**: **Node Ninja** (School of Motion, FREE) — auto-cablea un material Redshift desde una carpeta de texturas — muy citado, sin equivalente en Sentinel, casa con el Asset Hub.

## Shortlist de absorción (ranking del researcher)

1. **Keyframe offset/stagger** — batch-shift de keyframes PSR de la selección por N frames (puro `c4d.CTrack`/`CCurve`, complementa Vibrate Null; nicho menos servido).
2. **Delete Empty Nulls** — scan recursivo + delete de nulls sin hijos (un undo); candidato incluso a QC check #13.
3. **Remove unused/broken material tags** — extiende el QC #7 (Unused Materials) un nivel más (el tag), reusa la maquinaria fix/undo.
4. **Batch rename con tokens** — find/replace + secuencia numerada sobre selección (la categoría más reinventada del mercado; versión undo-safe).
5. **Render-complete notification** — notificación macOS al acabar render/Team Render; pairing natural con Post-Render Validation ("render done → validate now?").
6. **RS material auto-wire (Node Ninja-style)** — material Redshift desde carpeta de texturas; casa con Texture Repathing/Asset Hub.
7. **Checkpoint restaurable (Recall-style)** — snapshot de estado restaurable antes de fixes/bakes destructivos; generaliza la disciplina de undo de Sentinel en primitivo de artista.
8. **Project/scene-setup template** — "new shot" con carpeta+Take base+preset+ruleset seeded desde `sentinel_rules.json` (nicho sin dueño; Sentinel ya tiene los primitivos).

Descartados como absorción (producto entero o ya superado por Sentinel): Signal, GorillaCam, Magic Solo, HB ModellingBundle, CC4D Tools, mc_Camera, SafeFrame.
