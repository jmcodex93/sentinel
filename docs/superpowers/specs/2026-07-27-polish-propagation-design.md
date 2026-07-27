# Propagación del pulido a Reports/Hub/forms — un solo lenguaje de estado

**Fecha**: 2026-07-27
**Estado**: aprobado en brainstorm (companion visual — mockup en `.superpowers/brainstorm/83537-1785167414/content/status-treatment.html`, opción C elegida)
**Contexto**: cierra la "pasada posterior" que dejó pendiente el Panel Polish (v1.26.0): propagar los tokens de motion + el de-slop visual a las superficies del SPA fuera del panel (Reports, Hub, forms). Design system en `docs/design/DESIGN.md`; fase madre `2026-07-27-panel-polish-design.md`.

## Hallazgo que redimensiona el alcance

El motion **ya se propagó casi solo**: Reports/Hub/forms usan el mismo `components/form/Button.tsx` (press feedback + focus ring), el mismo `Toast`, y el kill-switch `@media (prefers-reduced-motion: reduce)` es global (`index.css`). Reports tampoco tiene "AI slop": su primitiva `Section.tsx` ya es limpia (subhead sobre contenido, sin borde, sin eyebrow). Por tanto esta fase es **quirúrgica**, no un restyle uniforme:

1. Un **único lenguaje de estado de salud** en toda la app (la decisión de producto central).
2. De-slop del único punto de monotonía de cajas real: `HubDeliverSection`.
3. Alinear motion hardcodeado a los tokens + hover.
4. Diálogos flotantes del Hub que se lean flotando.

## Decisiones cerradas (brainstorm)

1. **Alcance**: quirúrgico + pulido del Hub (la superficie más densa). Reports y forms solo reciben alineación de tokens + verificación; sin cambio estructural.
2. **Tratamiento de estado = icono + texto de color, sin fondo** (opción C del mockup). Retira el pill relleno.
3. **Un solo lenguaje de estado de salud** aplicado a la densidad de cada sitio: icono+texto en listas/tablas; punto-solo donde no cabe texto. El argumento de daltonismo (icono = forma, no solo color) aplica a TODAS las filas de estado, no solo a assets.
4. **De-slop = misma regla que el panel**: grupos sin borde donde el bloque es un wrapper apilado; card donde *es* card (KPIs de Delivery, tabla de datos del Hub).

## Diseño

### 1. `StatusMark` — el primitivo de estado de salud unificado (nuevo, `components/StatusMark.tsx`)

Colapsa `StatusDot` + `StatusBadge` en un solo componente. Eje semántico = **salud** (pass/fail/warn/neutral). No toca `statusMarker`/`statusBadgeTone` de `panelDeliver.ts`, que es el eje **workflow de versión** (WIP/TR/CR/FINAL, con CR=azul/info que no mapea a los 4 tonos de salud ni tiene icono natural) — se deja intacto.

```ts
export type StatusTone = "pass" | "fail" | "warn" | "neutral";
// icono por tono (lucide, ya en deps): pass=CheckCircle2, fail=XCircle,
// warn=AlertTriangle, neutral=Minus.
export function StatusMark(props: {
  tone: StatusTone;
  label?: string;          // presente → icono + texto de color; ausente → solo icono/punto
  compact?: boolean;       // true → punto de color sin icono ni texto (rail, indicadores mínimos)
}): JSX.Element
```

- **Modo etiquetado** (`label` presente, `compact` falso): `‹icon› label`, ambos en `TONE_COLOR[tone]`, sin fondo. Tamaño de icono 13px, `strokeWidth` 2.
- **Modo compacto** (`compact`): el punto de color actual (`h-2 w-2 rounded-full`), sin icono ni texto — para badges del rail donde no cabe.
- Colores desde el `TONE_COLOR` existente (los cuatro colores de estado exclusivos; el acento nunca marca estado). Reutiliza el mapeo, no lo redefine.
- `aria-label` = `label ?? tone` para accesibilidad cuando es compacto.

**Mapeo de asset status → tono** (para Delivery/Hub, hoy en `StatusBadge.STATUS_META`): `collected → pass`, `missing → fail`, `external → warn`. Se extrae a un helper puro `assetStatusTone(status): StatusTone` (vitest) para que ni la SPA ni el servidor re-deriven el mapeo.

### 2. Migración de los call sites

- **`components/StatusDot.tsx`** → borrado; sus usos pasan a `<StatusMark tone={...} label={...} />` (modo etiquetado) salvo `PanelRail` (badges) que usa `compact`. Usos actuales: `CheckRow` (QC report), `DoctorPage`, `RenderValidationPage`, `GateChecks`, `AssetsTable`, `HubAssetsTable`, `PanelRail`.
- **`components/StatusBadge.tsx`** → borrado; sus usos (Delivery `AssetsTable`, Hub) pasan a `<StatusMark tone={assetStatusTone(status)} label={status} />`.
- El texto de estado que hoy vive suelto en la fila (p.ej. una celda de label separada del punto) se absorbe en el `label` del `StatusMark` para no duplicarlo.

### 3. De-slop de `HubDeliverSection`

Los ~8 bloques `rounded-lg border` apilados (Version/target/zip/gate/progress/summary) → `SectionGroup` (sin borde, hairline top entre grupos consecutivos, cabecera peso 600), espejo del de-box del Deliver del panel. Conservan su tratamiento: el gate inline (filas de check por bucket), el progreso del job (barra/estado), y el `DeliverySummaryView`. Lo que **flota** (si algún estado se superpone) usa `--shadow-float`.

### 4. `SectionGroup` y `ConfirmBar` → compartidos

Ambos viven hoy en `components/panel/`. Al usarlos el Hub, se mueven a `components/` (raíz de componentes compartidos) y se actualizan los imports del panel. Sin cambio de API ni de comportamiento — solo ubicación.

### 5. Alineación de motion + hover (Hub)

- `HubFacets.Chip`: `transition-colors duration-100 ease-out` → `transition-colors duration-[var(--motion-fast)] ease-[var(--ease-glide)]`.
- Cualquier `transition-colors duration-100`/`duration-150` hardcodeado en `HubToolbar`, `HubAssetsTable`, `HubPreflightStrip` → tokens (`--motion-fast`/`--ease-glide`).
- Hover de fila de la tabla del Hub y de los chips de facets con `--motion-fast` (fondo `--color-surface-2`), como las cards del panel.
- La tabla densa de assets **se conserva** estructuralmente (es tabla de datos, no monotonía de cajas).

### 6. Diálogos del Hub

`HubShrinkDialog` / `HubSwitchResDialog`: si se montan flotando sobre la tabla, aplicar `--shadow-float` (lectura "flota", consistente con Toast/ConfirmBar) y montaje con glide (`--motion-glide`/`--ease-glide`), reutilizando el idiom del `ConfirmBar` cuando encaje. Sus bloques internos apilados, si los hay, usan `SectionGroup`.

### 7. Reports y forms

- **Reports**: `Section.tsx` ya limpio; solo migrar sus filas de estado a `StatusMark` (paso 2) y alinear cualquier transición suelta a tokens. `KpiCard` = card real, se conserva. `DeliverySummaryView`/`AssetsTable` reciben el `StatusMark`.
- **Forms**: ya heredan `Button` + `FormPageShell`; solo alinear transiciones sueltas si las hay. Sin cambio estructural.

## Manejo de errores / no-regresión

- Puramente presentacional + una consolidación de componentes: cero cambio de comportamiento/ops/contrato/datos. `prefers-reduced-motion` sigue desactivando todo transform/animation (global, ya existe).
- El mapeo asset→tono y `StatusMark` son puros/presentacionales; los vitest existentes de secciones siguen verdes (no dependen de clases de estilo).
- Sin dependencias nuevas (los iconos son `lucide-react`, ya en deps). Todo transforms/color (GPU), sin reflow.
- Borrar `StatusDot`/`StatusBadge` es seguro solo tras migrar todos los call sites (grep debe quedar limpio) — invariante verificable.

## Fuera de alcance

- `statusMarker`/badges de versión (WIP/TR/CR/FINAL) — eje distinto (workflow, no salud), se deja como está.
- Rediseño de la tabla densa del Hub, de las páginas de Reports, o de los flujos.
- Nuevas features. Floritura de motion (bounces consumer, ya descartados en la fase madre).
- Windows / verificación de hardware.

## Verificación

- **vitest**: `assetStatusTone` (mapeo collected/missing/external → pass/fail/warn); `StatusMark` no necesita test de render (presentacional) salvo un smoke de que `compact` no rinde label. Los vitest existentes de Hub/secciones siguen verdes.
- **tsc/build**: limpio; bundle reconstruido; grep de `StatusDot`/`StatusBadge` vacío tras la migración.
- **Live C4D** (usuario, escena real): status = icono+texto legible y coherente en Delivery, Hub, QC report, Doctor, Render Validation (un solo lenguaje); rail badges siguen como punto compacto; `HubDeliverSection` se lee como grupos con aire (no cajas); motion consistente (hover/press/glide) en el Hub; `prefers-reduced-motion` (macOS Accesibilidad → Movimiento) desactiva todo; Reports/forms sin regresión; badges de versión intactos.
