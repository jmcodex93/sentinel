# Propagación del pulido a Reports/Hub/forms — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un único lenguaje de estado de salud en todo el SPA (icono + texto/solo-icono), de-slop del único punto de monotonía de cajas (`HubDeliverSection`), y alineación del motion del Hub a los tokens — cerrando la coherencia visual que el Panel Polish (v1.26.0) dejó como "pasada posterior".

**Architecture:** Un primitivo compartido `StatusMark` (icono coloreado + label opcional) colapsa `StatusDot` (punto pelado) y `StatusBadge`/`HubStatusBadge` (pill relleno). Dos helpers puros mapean los dos enums de asset status a los cuatro tonos de salud. `SectionGroup`/`ConfirmBar` suben de `components/panel/` a `components/` para que el Hub los reuse. Todo presentacional; cero cambio de comportamiento/ops/contrato.

**Tech Stack:** React + TS + Tailwind v4; iconos `lucide-react` (ya en deps); vitest.

## Global Constraints

- Puramente presentacional: cero cambio de comportamiento/ops/contrato/datos. Los vitest existentes siguen verdes (no dependen de clases de estilo).
- Los **cuatro colores de estado** (pass/fail/warn/neutral) son exclusivos de estado; el acento `--color-primary` NUNCA marca estado.
- El eje **workflow de versión** (WIP/TR/CR/FINAL, `panelDeliver.statusMarker`/`statusBadgeTone`) es SEPARADO del eje **salud** — NO se toca en esta fase.
- `@media (prefers-reduced-motion: reduce)` (global, `index.css`) ya desactiva todo transform/animation — no se re-implementa.
- Sin dependencias nuevas. Motion vía tokens existentes: `--motion-fast` (120ms), `--motion-glide` (300ms), `--ease-glide`, `--ease-spring`, `--shadow-float`.
- Borrar `StatusDot.tsx`/`StatusBadge.tsx` solo tras migrar TODOS sus call sites; `grep -rn "StatusDot\|StatusBadge" web/src` debe quedar vacío (salvo el wrapper local que se reescriba) como invariante verificable.
- Versión objetivo: **v1.27.0**.
- Comandos desde `web/`: `npx tsc -b --noEmit`, `npx vitest run`, `npm run build`. El bundle se reconstruye en `plugin/web/` en la tarea final.

## File Structure

- **Nuevo** `web/src/components/StatusMark.tsx` — primitivo de estado de salud + `StatusTone` type + `TONE_COLOR`.
- **Nuevo** `web/src/lib/status.ts` — `assetStatusTone` (Delivery), `hubAssetStatusTone` (Hub), puros.
- **Nuevo** `web/src/lib/status.test.ts` — vitest de ambos mapeos.
- **Movidos** `components/panel/SectionGroup.tsx` → `components/SectionGroup.tsx`; `components/panel/ConfirmBar.tsx` → `components/ConfirmBar.tsx`.
- **Borrados** `components/StatusDot.tsx`, `components/StatusBadge.tsx`.
- **Modificados**: `CheckRow.tsx`, `GateChecks.tsx`, `AssetsTable.tsx`, `pages/DoctorPage.tsx`, `pages/RenderValidationPage.tsx`, `pages/QcReportPage.tsx`, `components/hub/HubAssetsTable.tsx`, `components/hub/HubDeliverSection.tsx`, `components/hub/HubFacets.tsx`, `components/panel/{DeliverSection,RenderSection,ToolsSection,FrameSubview}.tsx`, `pages/PanelPage.tsx`, `components/hub/HubShrinkDialog.tsx`, `components/hub/HubSwitchResDialog.tsx`, y (barrido de motion, Task 7) `components/form/{TextInput,TextArea,Select,SegmentedControl}.tsx`, `components/{AssetsTable,Sidebar,SupervisorShotsTable,PageStates,Toast}.tsx`, `pages/{PalettePage,NotesPage,HubPage,SupervisorPage}.tsx`, `plugin/sentinel/__init__.py`, `CLAUDE.md`.

---

### Task 1: `StatusMark` primitivo + mapeos de tono (puros) + vitest

**Files:**
- Create: `web/src/components/StatusMark.tsx`
- Create: `web/src/lib/status.ts`
- Test: `web/src/lib/status.test.ts`

**Interfaces:**
- Produces: `StatusTone` (`"pass"|"fail"|"warn"|"neutral"`) y `StatusMark({tone, label?})` desde `StatusMark.tsx`; `assetStatusTone(AssetStatus): StatusTone`, `hubAssetStatusTone(HubAssetStatus): StatusTone` desde `lib/status.ts`.
- Consumes: `AssetStatus`/`HubAssetStatus` de `web/src/types.ts` (ya existen: `AssetStatus = "collected"|"missing"|"external"`; `HubAssetStatus = "missing"|"absolute"|"empty"|"asset_uri"|"ok"`).

- [ ] **Step 1: Escribe el test de los mapeos (falla)**

`web/src/lib/status.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { assetStatusTone, hubAssetStatusTone } from "./status";

describe("assetStatusTone", () => {
  it("maps Delivery asset statuses to health tones", () => {
    expect(assetStatusTone("collected")).toBe("pass");
    expect(assetStatusTone("missing")).toBe("fail");
    expect(assetStatusTone("external")).toBe("warn");
  });
});

describe("hubAssetStatusTone", () => {
  it("maps Hub asset statuses to health tones (mirrors HubAssetsTable STATUS_META chroma)", () => {
    expect(hubAssetStatusTone("ok")).toBe("pass");
    expect(hubAssetStatusTone("missing")).toBe("fail");
    expect(hubAssetStatusTone("absolute")).toBe("warn");
    expect(hubAssetStatusTone("empty")).toBe("warn");
    expect(hubAssetStatusTone("asset_uri")).toBe("neutral");
  });
});
```

- [ ] **Step 2: Corre el test (falla por módulo inexistente)**

Run: `cd web && npx vitest run src/lib/status.test.ts`
Expected: FAIL ("Failed to resolve import ./status").

- [ ] **Step 3: Escribe `lib/status.ts`**

```ts
import type { StatusTone } from "../components/StatusMark";
import type { AssetStatus, HubAssetStatus } from "../types";

/** Delivery Summary asset status → health tone. */
export function assetStatusTone(status: AssetStatus): StatusTone {
  switch (status) {
    case "collected": return "pass";
    case "missing": return "fail";
    case "external": return "warn";
  }
}

/** Hub asset status → health tone. Mirrors the chroma HubAssetsTable's
 * STATUS_META already used (missing→fail, absolute/empty→warn,
 * asset_uri→neutral, ok→pass). */
export function hubAssetStatusTone(status: HubAssetStatus): StatusTone {
  switch (status) {
    case "ok": return "pass";
    case "missing": return "fail";
    case "absolute": return "warn";
    case "empty": return "warn";
    case "asset_uri": return "neutral";
  }
}
```

- [ ] **Step 4: Escribe `components/StatusMark.tsx`**

```tsx
import { CheckCircle2, XCircle, AlertTriangle, Minus } from "lucide-react";
import type { LucideIcon } from "lucide-react";

/** The single health-status vocabulary across the SPA. Distinct from the
 * version-workflow badge (WIP/TR/CR/FINAL) in panelDeliver.statusMarker —
 * that is a different axis and is NOT this. */
export type StatusTone = "pass" | "fail" | "warn" | "neutral";

const TONE_COLOR: Record<StatusTone, string> = {
  pass: "var(--color-status-pass)",
  fail: "var(--color-status-fail)",
  warn: "var(--color-status-warn)",
  neutral: "var(--color-status-neutral)",
};

const TONE_ICON: Record<StatusTone, LucideIcon> = {
  pass: CheckCircle2,
  fail: XCircle,
  warn: AlertTriangle,
  neutral: Minus,
};

/** A colored status icon (shape = color-blind-safe) plus an optional colored
 * label. Replaces StatusDot (bare dot) and StatusBadge/HubStatusBadge (filled
 * tint pill). `label` present → icon + text (status IS the data: asset
 * collected/missing/external, hub ok/absolute/…); absent → icon only (the row
 * already names itself: QC checks, Doctor items). */
export function StatusMark({ tone, label }: { tone: StatusTone; label?: string }) {
  const Icon = TONE_ICON[tone];
  return (
    <span className="text-label inline-flex items-center gap-1.5" style={{ color: TONE_COLOR[tone] }}>
      <Icon size={13} strokeWidth={2.25} aria-hidden={label ? true : undefined} aria-label={label ? undefined : tone} />
      {label}
    </span>
  );
}
```

- [ ] **Step 5: Corre el test (pasa)**

Run: `cd web && npx vitest run src/lib/status.test.ts`
Expected: PASS (2 archivos de describe, 2 tests).

- [ ] **Step 6: tsc + commit**

Run: `cd web && npx tsc -b --noEmit`
Expected: sin errores.
```bash
git add web/src/components/StatusMark.tsx web/src/lib/status.ts web/src/lib/status.test.ts
git commit -m "feat(ui): StatusMark — unified health-status primitive + tone maps"
```

---

### Task 2: Migrar filas de report/gate/doctor a `StatusMark` (icono-solo) + borrar `StatusDot`

**Files:**
- Modify: `web/src/components/CheckRow.tsx`, `web/src/components/GateChecks.tsx:3`, `web/src/pages/DoctorPage.tsx`, `web/src/pages/RenderValidationPage.tsx:7`, `web/src/pages/QcReportPage.tsx:6`
- Delete: `web/src/components/StatusDot.tsx`

**Interfaces:**
- Consumes: `StatusMark`, `StatusTone` de Task 1.

Contexto: `StatusDot` (el valor) se usa SOLO en `CheckRow` y `DoctorPage`; el resto (`GateChecks`, `RenderValidationPage`, `QcReportPage`) importa solo el `type StatusTone`. `GateChecks` renderiza vía `CheckRow` (pasa `tone`), así que migrar `CheckRow` cubre su render. En estas filas el nombre del ítem es el texto principal → `StatusMark` va **sin label** (icono coloreado en lugar del punto).

- [ ] **Step 1: `CheckRow.tsx` — StatusDot → StatusMark, tipo re-apuntado, motion a tokens**

Reemplaza las importaciones:
```tsx
import type { StatusTone } from "./StatusMark";
import { StatusMark } from "./StatusMark";
```
(borra las dos líneas `import ... "./StatusDot"`.)

Reemplaza `<StatusDot tone={tone} />` por `<StatusMark tone={tone} />`.

En el `className` del `<button>`, cambia `transition-colors duration-100 ease-out` por `transition-colors duration-[var(--motion-fast)] ease-[var(--ease-glide)]`.

- [ ] **Step 2: `DoctorPage.tsx` — StatusDot → StatusMark (icono-solo), alineación**

Reemplaza el import `{ StatusDot }`/`type StatusTone` de `../components/StatusDot` por:
```tsx
import { StatusMark } from "../components/StatusMark";
import type { StatusTone } from "../components/StatusMark";
```
Reemplaza `<StatusDot tone={TONE_FOR_STATUS[item.status]} />` por `<StatusMark tone={TONE_FOR_STATUS[item.status]} />`. El icono mide 13px (el punto medía 8px); ajusta el wrapper `className="mt-1.5 shrink-0"` a `className="mt-0.5 shrink-0"` para alinear con la primera línea del label.

- [ ] **Step 3: Re-apuntar los imports de tipo restantes**

En `GateChecks.tsx:3`, `RenderValidationPage.tsx:7`, `QcReportPage.tsx:6`: cambia `from "./StatusDot"` / `from "../components/StatusDot"` por `.../StatusMark` (solo el path del `import type { StatusTone }`).

- [ ] **Step 4: Borrar StatusDot y verificar grep limpio**

```bash
rm web/src/components/StatusDot.tsx
grep -rn "StatusDot" web/src && echo "QUEDAN USOS — arreglar" || echo "grep StatusDot limpio"
```
Expected: "grep StatusDot limpio".

- [ ] **Step 5: tsc + build vitest + commit**

Run: `cd web && npx tsc -b --noEmit && npx vitest run`
Expected: sin errores; vitest verde (mismo conteo previo + los 2 de Task 1).
```bash
git add -A web/src
git commit -m "refactor(ui): report/gate/doctor rows use StatusMark (icon-only); delete StatusDot"
```

---

### Task 3: Migrar asset status (Delivery + Hub) a `StatusMark` icono+texto + borrar `StatusBadge`

**Files:**
- Modify: `web/src/components/AssetsTable.tsx:4,79`, `web/src/components/hub/HubAssetsTable.tsx:100-124,512`
- Delete: `web/src/components/StatusBadge.tsx`

**Interfaces:**
- Consumes: `StatusMark` (Task 1), `assetStatusTone`, `hubAssetStatusTone` (Task 1).

Aquí el status ES el dato → `StatusMark` **con label** (icono + texto de color).

- [ ] **Step 1: `AssetsTable.tsx` (Delivery) — StatusBadge → StatusMark labeled**

Borra `import { StatusBadge } from "./StatusBadge";`. Añade:
```tsx
import { StatusMark } from "./StatusMark";
import { assetStatusTone } from "../lib/status";
```
Reemplaza `<StatusBadge status={asset.status} />` por:
```tsx
<StatusMark tone={assetStatusTone(asset.status)} label={asset.status} />
```

- [ ] **Step 2: `HubAssetsTable.tsx` — reescribe `HubStatusBadge` sobre StatusMark**

Añade imports (arriba del fichero):
```tsx
import { StatusMark } from "../StatusMark";
import { hubAssetStatusTone } from "../../lib/status";
```
Reduce el `STATUS_META` local a solo labels (quita `color`/`background`):
```tsx
const STATUS_LABEL: Record<HubAssetStatus, string> = {
  missing: "missing", absolute: "absolute", empty: "empty",
  asset_uri: "asset uri", ok: "ok",
};
```
Reescribe el componente local:
```tsx
function HubStatusBadge({ status }: { status: HubAssetStatus }) {
  return <StatusMark tone={hubAssetStatusTone(status)} label={STATUS_LABEL[status]} />;
}
```
(El call site `<HubStatusBadge status={a.status} />` en la línea ~512 no cambia.)

- [ ] **Step 3: Borrar StatusBadge y verificar grep limpio**

```bash
rm web/src/components/StatusBadge.tsx
grep -rn "StatusBadge" web/src | grep -v "HubStatusBadge" && echo "QUEDAN USOS" || echo "grep StatusBadge limpio"
```
Expected: "grep StatusBadge limpio" (el `HubStatusBadge` local es un nombre distinto y permanece).

- [ ] **Step 4: tsc + vitest + commit**

Run: `cd web && npx tsc -b --noEmit && npx vitest run`
Expected: sin errores; vitest verde.
```bash
git add -A web/src
git commit -m "refactor(ui): Delivery+Hub asset status use StatusMark (icon+text); delete StatusBadge"
```

---

### Task 4: Subir `SectionGroup` + `ConfirmBar` a `components/` compartidos

**Files:**
- Move: `components/panel/SectionGroup.tsx` → `components/SectionGroup.tsx`; `components/panel/ConfirmBar.tsx` → `components/ConfirmBar.tsx`
- Modify imports: `components/panel/DeliverSection.tsx:14`, `components/panel/RenderSection.tsx:20,22`, `components/panel/ToolsSection.tsx:3`, `components/panel/FrameSubview.tsx:4`, `pages/PanelPage.tsx:2`

Sin cambio de API ni comportamiento — solo ubicación, para que el Hub (Task 5) los reuse.

- [ ] **Step 1: Mover los ficheros**

```bash
cd web/src
git mv components/panel/SectionGroup.tsx components/SectionGroup.tsx
git mv components/panel/ConfirmBar.tsx components/ConfirmBar.tsx
```

- [ ] **Step 2: Re-apuntar imports del panel**

- `components/panel/DeliverSection.tsx`, `RenderSection.tsx`, `ToolsSection.tsx`, `FrameSubview.tsx`: `from "./SectionGroup"` → `from "../SectionGroup"`.
- `components/panel/RenderSection.tsx`: `from "./ConfirmBar"` → `from "../ConfirmBar"`.
- `pages/PanelPage.tsx:2`: `from "../components/panel/ConfirmBar"` → `from "../components/ConfirmBar"`.

Verificación:
```bash
grep -rn "panel/SectionGroup\|panel/ConfirmBar\|\"./SectionGroup\"\|\"./ConfirmBar\"" web/src && echo "IMPORTS SIN ACTUALIZAR" || echo "imports OK"
```
Expected: "imports OK".

- [ ] **Step 3: tsc + vitest + commit**

Run: `cd web && npx tsc -b --noEmit && npx vitest run`
Expected: sin errores; vitest verde.
```bash
git add -A web/src
git commit -m "refactor(ui): move SectionGroup + ConfirmBar to shared components/ (Hub reuse)"
```

---

### Task 5: De-slop de `HubDeliverSection` + alineación de motion del Hub

**Files:**
- Modify: `web/src/components/hub/HubDeliverSection.tsx`, `web/src/components/hub/HubFacets.tsx:32`

**Interfaces:**
- Consumes: `SectionGroup` de `components/SectionGroup` (Task 4).

Referencia del patrón: `components/panel/DeliverSection.tsx` (mismo de-box ya aprobado). `SectionGroup` API: `{ title?, meta?, action?, first?, children }` — grupo sin borde, hairline top entre grupos consecutivos (omitido con `first`), título peso 600 (no eyebrow-mayúsculas).

- [ ] **Step 1: Leer `HubDeliverSection.tsx` entero** y localizar los ~8 wrappers `rounded-lg border ...` que envuelven bloques apilados (Version/target/zip/gate/progress/summary).

- [ ] **Step 2: Reemplazar cada wrapper-caja por `SectionGroup`**

Regla (idéntica al panel): un bloque que es solo un wrapper apilado con cabecera → `<SectionGroup title="..." first={esPrimero}>...</SectionGroup>`, quitando `rounded-lg border p-3`/`surface` y el eyebrow si lo hubiera. Ejemplo de transformación:
```tsx
// antes
<div className="rounded-lg border p-3" style={{ borderColor: "var(--color-hairline)" }}>
  <h4 className="...">Delivery</h4>
  {/* target input, zip checkbox, collect button */}
</div>
// después
<SectionGroup title="Delivery">
  {/* target input, zip checkbox, collect button */}
</SectionGroup>
```
CONSERVAR sin de-box: las filas del gate inline (por bucket), la barra/estado de progreso del job, y el `DeliverySummaryView`. Importa `SectionGroup` con `import { SectionGroup } from "../SectionGroup";`.

- [ ] **Step 3: Alinear el motion del Hub a tokens**

- `HubDeliverSection.tsx` barra de progreso: `transition-all duration-150 ease-out` → `transition-all duration-[var(--motion-base)] ease-[var(--ease-glide)]`.
- `HubFacets.tsx:32` (Chip): `transition-colors duration-100 ease-out` → `transition-colors duration-[var(--motion-fast)] ease-[var(--ease-glide)]`.

- [ ] **Step 4: tsc + vitest + commit**

Run: `cd web && npx tsc -b --noEmit && npx vitest run`
Expected: sin errores; los vitest de Hub siguen verdes (no dependen de clases de estilo).
```bash
git add -A web/src
git commit -m "feat(hub): de-slop HubDeliverSection (SectionGroup) + align motion to tokens"
```

---

### Task 6: Tratamiento flotante de los diálogos del Hub

**Files:**
- Modify: `web/src/components/hub/HubShrinkDialog.tsx`, `web/src/components/hub/HubSwitchResDialog.tsx`

**Interfaces:**
- Idiom de referencia: `components/ConfirmBar.tsx` (glide de montaje + `--shadow-float`).

- [ ] **Step 1: Leer ambos diálogos** y localizar el contenedor raíz que flota sobre la tabla (el `rounded-lg border` de nivel superior).

- [ ] **Step 2: Aplicar el tratamiento flotante**

Al contenedor raíz de cada diálogo: añadir `boxShadow: "var(--shadow-float)"` (style) y, si el diálogo aparece/desaparece, un glide de montaje (opacidad + `translateY(-4px)→0`, `transition-[opacity,transform] duration-[var(--motion-glide)] ease-[var(--ease-glide)]`, con el idiom `entered`-un-frame-después-de-montar de `ConfirmBar`). Los bloques internos apilados (si los hay) → `SectionGroup`. Respeta `prefers-reduced-motion` automáticamente (kill-switch global).

- [ ] **Step 3: tsc + vitest + commit**

Run: `cd web && npx tsc -b --noEmit && npx vitest run`
Expected: sin errores; vitest verde.
```bash
git add -A web/src
git commit -m "feat(hub): float Shrink/SwitchRes dialogs (shadow-float + glide)"
```

---

### Task 7: Barrido de motion a tokens (superficies restantes)

**Files:**
- Modify: `components/form/{TextInput,TextArea,Select,SegmentedControl}.tsx`, `components/{AssetsTable,Sidebar,SupervisorShotsTable,PageStates,Toast}.tsx`, `pages/{PalettePage,NotesPage,HubPage,SupervisorPage}.tsx`

Cierra el requisito del spec ("alinear cualquier transición suelta a tokens") en las superficies que las tareas 2/5 no tocan. Mecánico, bajo riesgo, sin cambio de comportamiento. El panel ya está en tokens (v1.26.0) — NO se toca.

Regla de mapeo (aplicar en cada `className` afectado):
- `duration-100` → `duration-[var(--motion-fast)]`
- `duration-150` → `duration-[var(--motion-base)]`
- `ease-out` → `ease-[var(--ease-glide)]`
- `transition-colors`/`transition-all` se conservan (solo cambia duración+easing).

- [ ] **Step 1: Aplicar el mapeo en cada fichero de la lista**

Para cada uno, localiza los `className` con `duration-100`/`duration-150` + `ease-out` y sustituye según la regla. Ejemplo (`TextInput.tsx`):
```tsx
// antes: ... transition-colors duration-100 ease-out focus:border-[var(--color-primary)] ...
// después: ... transition-colors duration-[var(--motion-fast)] ease-[var(--ease-glide)] focus:border-[var(--color-primary)] ...
```

- [ ] **Step 2: Verificar que no quedan literales hardcodeados**

```bash
cd web && grep -rn "duration-100\|duration-150\|ease-out" src/components src/pages | grep -v "panel/" || echo "barrido limpio (fuera de panel)"
```
Expected: "barrido limpio (fuera de panel)" (el panel se dejó intacto a propósito; si algún `ease-out` sobrevive dentro de un contexto no-transición, evaluarlo — pero los flagueados son todos de transición).

- [ ] **Step 3: tsc + vitest + commit**

Run: `cd web && npx tsc -b --noEmit && npx vitest run`
Expected: sin errores; vitest verde.
```bash
git add -A web/src
git commit -m "style(ui): align remaining hardcoded transitions to motion tokens"
```

---

### Task 8: Build + v1.27.0 + docs

**Files:**
- Modify: `plugin/sentinel/__init__.py:4`, `CLAUDE.md`

- [ ] **Step 1: Reconstruir el bundle**

Run: `cd web && npm run build`
Expected: build OK; genera `plugin/web/`.

- [ ] **Step 2: Verificación integral**

Run: `cd web && npx tsc -b --noEmit && npx vitest run`
Expected: tsc limpio; vitest verde.
```bash
grep -rn "StatusDot\|from \"./StatusBadge\"\|from \"../StatusBadge\"" web/src && echo "RESIDUOS" || echo "grep limpio"
```
Expected: "grep limpio".
Run (desde la raíz): `python3 -m pytest -q`
Expected: 848 passed (Python intacto).

- [ ] **Step 3: Version bump + docs**

- `plugin/sentinel/__init__.py`: `PLUGIN_VERSION = "1.27.0"`.
- `CLAUDE.md`: nueva viñeta en "What Works" + entrada en Version History resumiendo: un lenguaje de estado (`StatusMark` icono+texto/solo-icono, colapsa StatusDot+StatusBadge), de-slop de HubDeliverSection, motion del Hub a tokens, diálogos del Hub flotando, `SectionGroup`/`ConfirmBar` compartidos; badges de versión intactos; **Pendiente de verificación live**.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: build + v1.27.0 — polish propagation (one status language + Hub de-slop)"
```

## Verificación final (tras todas las tareas)

- `npx vitest run` verde (incluye los 2 nuevos de `status.test.ts`); `npx tsc -b --noEmit` limpio; `npm run build` OK; `python3 -m pytest -q` = 848.
- `grep -rn "StatusDot\|StatusBadge" web/src` solo devuelve el `HubStatusBadge` local (wrapper sobre StatusMark) — cero `StatusDot`, cero `StatusBadge` importado.
- `grep -rn "duration-100\|duration-150" web/src/components web/src/pages | grep -v "panel/"` vacío (motion en tokens fuera del panel).
- **Live C4D** (usuario): status = icono+texto coherente en Delivery/Hub, icono-solo en QC report/Doctor/Render Validation (un solo lenguaje); `HubDeliverSection` se lee como grupos con aire; motion del Hub consistente (hover/press/glide); `prefers-reduced-motion` desactiva todo; Reports/forms sin regresión; badges de versión (WIP/TR/CR/FINAL) intactos.
