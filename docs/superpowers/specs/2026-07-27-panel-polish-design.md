# Panel Polish — Motion pass + de-slop visual (careful Linear)

**Fecha**: 2026-07-27
**Estado**: aprobado en brainstorm (companion visual — mockups en `.superpowers/brainstorm/29526-1785161718/content/{deliver-before-after,badge-vs-dot}.html`)
**Contexto**: pulido del panel SPA tras cerrar el arco del rediseño. El design system (Linear-adaptado) está bien; el problema es **cómo se aplica** — monotonía de cajas idénticas con eyebrows-mayúsculas, sin profundidad considerada, jerarquía débil, motion mínimo de solo-color sin `prefers-reduced-motion`. Inspiración de motion: `kinetics.colorion.co` (spring-physics, valores atenuados a nuestra contención). Spec madre `2026-07-21-panel-spa-design.md`; design system `docs/design/DESIGN.md`.

## Decisiones cerradas (brainstorm)

1. **Alcance**: **solo el panel** (Overview/QC/Render/Deliver/Tools/Frame) esta fase. Los tokens (motion/elevación/espaciado) se definen una vez y benefician a todo el SPA; el restyling de-box se aplica al panel ahora, propagación a Reports/Hub/forms = pasada posterior.
2. **Motion + visual en UNA fase** (comparten tokens; se evalúan mejor juntos en vivo).
3. **Marcador de status = punto + texto** en el color del estado (sin pill relleno) — validado contra 4 variantes: escaneable por color + auto-identificable por texto + color-blind-safe + ligero en lista densa. (El pill relleno actual pesa; el punto puro falla en daltonismo.)
4. **De-slop = regla coherente, no "quitar todas las cards"**: grupos sin borde donde el bloque es solo un wrapper (secciones de config apiladas); card donde *es* una card (KPIs de Overview, tarjetas FAIL/WARN de QC con tinte de estado).

## Diseño

### 1. Tokens nuevos (`docs/design/DESIGN.md` + `web/src/tokens.css`)

- **Easings** (Kinetics atenuados):
  - `--ease-glide: cubic-bezier(0.16, 1, 0.3, 1)` (decel suave, para enter/exit y height/width).
  - `--ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1)` (settle con leve overshoot, solo para press/pop — nunca en transiciones grandes).
- **Durations**: `--motion-press: 80ms`, `--motion-fast: 120ms` (revisa el actual 100ms → 120ms), `--motion-base: 180ms`, `--motion-glide: 300ms`. Mantener `--motion-easing: ease` como legacy hasta migrar, luego retirar.
- **Elevación**: un único `--shadow-float` (p.ej. `0 8px 24px rgba(0,0,0,.5), 0 2px 6px rgba(0,0,0,.4)`) para toast/popover/confirm bar. La estructura sigue separando con hairlines; solo lo que *flota* lleva sombra.
- **Reduced motion**: en `index.css`, `@media (prefers-reduced-motion: reduce) { *,*::before,*::after { animation-duration:0.01ms !important; transition-duration:0.01ms !important; } }` (kill-switch global; obligatorio en herramienta pro).
- Actualizar el bloque `motion:` de `DESIGN.md` con easings/durations/elevación + una sección "Motion" ampliada (cuándo animar, con qué, valores) — misma disciplina que los tokens de color.

### 2. Aplicaciones de motion (CSS puro, transforms GPU, CSP-safe — cero JS de animación)

- **Press feedback** (`Button`): sustituir el hover por JS (`onMouseEnter/Leave`) por CSS `:hover`/`:active`; `:active { transform: scale(0.97) }` con `transition: transform var(--motion-press) var(--ease-spring)`; inset highlight en el primary (`box-shadow: inset 0 1px 0 rgba(255,255,255,.08)`); `:focus-visible` ring con el acento (accesibilidad).
- **Toast** (`Toast.tsx`): enter = slide-up + fade (`translateY` + opacity, `--ease-glide`); exit = fade-down. Elevación `--shadow-float`. Respeta reduced-motion (aparece sin transform).
- **Confirm bar / expand inline** (confirm de QC/Render/Deliver/Frame, Info expandible de QC): glide de altura+opacidad al aparecer/desaparecer (`--ease-glide`), no aparición instantánea.
- **Pop de estado**: un keyframe sutil (`scale 1→1.08→1`, `--motion-base`) aplicado SOLO en cambio real de un valor de estado (score QC en la barra del header, badge que cambia) — gateado por comparación de valor previo, nunca en cada tick de polling. Si añade complejidad desproporcionada en algún punto, se omite ahí (nunca un pop en cada refresh).
- **Row hover**: transición de fondo con `--motion-fast`.

### 3. De-slop visual (restyle de las secciones del panel)

- **Componente `SectionGroup`** compartido (nuevo, `components/panel/SectionGroup.tsx`): un grupo sin borde con cabecera opcional (`title` en `text-body`/peso 600, no eyebrow-mayúsculas; `meta`/acción a la derecha) y separación por hairline top entre grupos consecutivos. Reemplaza el patrón `rounded-lg border p-3 surface-1` + eyebrow en las secciones de config apiladas.
- **Aplicar a**: `RenderSection` (Preset/Frame/AOVs/Snapshots/Post-Render), `DeliverSection` (Version/Recent/Notes/Deliver), `FrameSubview` (hint/Frame/Subjects/QC#12), `ToolsSection` (Layout/Animation/QC Marking). El "hint" del Frame y el confirm bar mantienen su tratamiento (el hint puede llevar tinte warn; el confirm flota con `--shadow-float`).
- **Conservar card** (NO de-box): la rejilla de KPIs de `OverviewCards` y las tarjetas FAIL/WARN de `QcSection`/`QcCard` (el tinte de estado es semántico). Estas se benefician del motion/press/hover pero mantienen su borde/tinte.
- **Marcador de status = punto + texto**: helper puro `statusMarker(status)` (o extender `statusBadgeTone`) → `{ dotColor, label, textColor }` con el color del estado; render `● LABEL` (punto + texto coloreado, sin fondo pill). Aplicar en Recent versions (`DeliverSection`) y donde se muestre status de versión. `panelDeliver.statusBadgeTone` ya existe — se reutiliza para el color; el cambio es de *render* (pill → dot+text). vitest de paridad.
- **Ritmo de espaciado**: unificar a `--space-sm`(16)/`--space-lg`(24) en las secciones (retirar la mezcla gap-2/gap-3/p-3 arbitraria); iconos a tamaño/alineación consistentes.

### 4. Componentes tocados

- Nuevo: `components/panel/SectionGroup.tsx` (+ un helper `statusMarker` en `lib/panelDeliver.ts` o `lib/status.ts`).
- Modificados: `tokens.css`, `index.css`, `Button.tsx`, `Toast.tsx`, `RenderSection.tsx`, `DeliverSection.tsx`, `FrameSubview.tsx`, `ToolsSection.tsx`, y los confirm bars/expand de `QcSection.tsx`/`PanelPage.tsx` (glide). `OverviewCards.tsx`/`QcCard.tsx` = motion/hover/press pero conservan card.
- `DESIGN.md`: tokens + sección Motion.

## Manejo de errores / no-regresión

- Motion es puramente presentacional: cero cambio de comportamiento/ops/contrato. `prefers-reduced-motion` desactiva todo transform/animation.
- El de-box es CSS/estructura JSX: mismo contenido, mismos handlers; los tests de lógica (vitest de las secciones) siguen verdes (no dependen de las clases de estilo).
- Sin dependencias nuevas (no se importa Kinetics; se adoptan los *valores*). Todo transforms GPU (translate/scale/opacity) — sin reflow, sin jank en el panel dockeado que comparte proceso con C4D.

## Fuera de alcance

- Reports / Hub / forms (propagación posterior con los mismos tokens).
- Rediseñar la IA o los flujos (esto es pulido visual + motion, no reestructuración).
- Bounces consumer (magnetic buttons, drag-to-dismiss, ripple, rubber-band, stagger en cada re-render) — descartados por brainstorm (chocan con Linear-calm en un tool que el artista mira todo el día).
- El hueco vertical del panel dockeado (limitación de C4D, no accionable).

## Verificación

- **vitest**: `statusMarker`/marcador de status puro (color + label por estado, WIP/TR/CR/FINAL/custom); cualquier helper puro nuevo. Los vitest existentes de las secciones siguen verdes.
- **tsc/build**: limpio; bundle reconstruido.
- **Live C4D** (usuario, escena real): las secciones de-slopped se leen como diseño cuidado (grupos con aire, no cajas); status = punto+texto legible; press feedback en botones; toasts entran con slide+fade; confirm/expand con glide; `prefers-reduced-motion` (activable en macOS: Ajustes → Accesibilidad → Movimiento) desactiva las animaciones; sin jank/parpadeo en el panel dockeado; Overview KPIs y QC FAIL/WARN conservan card; el resto de secciones sin borde.
