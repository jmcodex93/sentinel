# Panel Polish (motion + de-slop) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Polish the SPA panel to read as careful, coherent Linear (not "AI slop"): de-box the stacked-config sections, switch version status to a dot+text marker, and add a disciplined, `prefers-reduced-motion`-aware motion layer.

**Architecture:** New motion/elevation tokens in `tokens.css`/`DESIGN.md` (adopted values, no library). A shared `SectionGroup` (borderless group + hairline divider) replaces the repeated bordered-card shell in the stacked sections; a pure `statusMarker` helper drives the dot+text status. Motion applied via CSS transforms only (GPU, CSP-safe). Overview KPIs + QC FAIL/WARN keep their cards.

**Tech Stack:** React + TS + Tailwind v4 (vitest). No Python change.

## Global Constraints

- Motion is presentational ONLY: zero behavior/op/contract change; existing section vitest stays green (tests don't depend on style classes).
- All motion via CSS transforms (translate/scale/opacity) — no reflow, no JS animation loops (the panel shares C4D's process). No new dependencies (adopt Kinetics *values*, don't import it).
- `@media (prefers-reduced-motion: reduce)` global kill-switch — mandatory.
- Accent (`#5e6ad2`) never marks state; status chroma stays exclusive to state. Dot+text status uses the existing per-status color mapping (`statusBadgeTone`).
- De-box only the stacked-config sections (Render/Deliver/Frame/Tools). KEEP the card on Overview KPI grid + QC FAIL/WARN cards (status-tint = meaning).
- Version bump `1.26.0` (visual feature). Baselines: pytest 848, vitest 130.

## Tokens summary (used across tasks)

- `--ease-glide: cubic-bezier(0.16, 1, 0.3, 1)`; `--ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1)`
- `--motion-press: 80ms`; `--motion-fast: 120ms`; `--motion-base: 180ms`; `--motion-glide: 300ms`
- `--shadow-float: 0 8px 24px rgba(0,0,0,.5), 0 2px 6px rgba(0,0,0,.4)`

---

### Task 1: Motion/elevation tokens + reduced-motion kill-switch

**Files:**
- Modify: `web/src/tokens.css` (add easing/duration/shadow tokens)
- Modify: `web/src/index.css` (reduced-motion block)
- Modify: `docs/design/DESIGN.md` (motion block + Motion section)

- [ ] **Step 1: Add tokens to `tokens.css`**

In the `:root` block, near the existing `--motion-*`:
```css
  --ease-glide: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  --motion-press: 80ms;
  --motion-glide: 300ms;
  --shadow-float: 0 8px 24px rgba(0, 0, 0, 0.5), 0 2px 6px rgba(0, 0, 0, 0.4);
```
Change `--motion-fast: 100ms;` → `--motion-fast: 120ms;` and keep `--motion-base` but set it to `180ms` (was 150ms). Leave `--motion-easing: ease` as-is (legacy; migrated per-component in later tasks).

- [ ] **Step 2: Add the reduced-motion kill-switch to `index.css`**

Append (after the `@theme inline {...}` block, at top level):
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

- [ ] **Step 3: Verify build still compiles**

Run: `cd "/Users/javiermelgar/Library/CloudStorage/SynologyDrive-01_WORK/99 - CODEX/10 YS Guardian/web" && npx vitest run && npx tsc -b --noEmit`
Expected: vitest 130 pass, tsc clean (no consumer yet — this is foundation).

- [ ] **Step 4: Update `DESIGN.md`**

Replace the `motion:` block with the new easings + durations + `shadow-float`, and expand the `### Motion` section: document the two easings (glide for enter/exit + size changes; spring for press/pop only), the duration scale, `--shadow-float` (only for floating surfaces: toast/popover/confirm), and the `prefers-reduced-motion` kill-switch. Keep the DESIGN.md rule "accent never marks state".

- [ ] **Step 5: Commit**

```bash
git add web/src/tokens.css web/src/index.css docs/design/DESIGN.md
git commit -m "feat(design): motion/elevation tokens + prefers-reduced-motion kill-switch (panel polish)"
```

---

### Task 2: Button + Toast motion

**Files:**
- Modify: `web/src/components/form/Button.tsx`
- Modify: `web/src/components/Toast.tsx`

**Interfaces:** `Button` keeps its `variant` API; hover/active/focus move from JS to CSS. `Toast` keeps its props.

- [ ] **Step 1: Rewrite `Button` hover→CSS + press feedback + focus ring**

Replace the JS `onMouseEnter/onMouseLeave` bg-swap with Tailwind state utilities and add press + focus-visible. New className (keep the base layout classes) + inline base colors:
```tsx
className={`text-label inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 transition-[background-color,transform] duration-[var(--motion-fast)] ease-[var(--ease-glide)] active:scale-[0.97] active:duration-[var(--motion-press)] active:ease-[var(--ease-spring)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-canvas)] disabled:cursor-not-allowed disabled:opacity-50 ${
  isPrimary
    ? "bg-[var(--color-primary)] hover:bg-[var(--color-primary-hover)] text-[var(--color-on-primary)]"
    : "bg-[var(--color-surface-2)] hover:bg-[var(--color-surface-1)] text-[var(--color-ink)]"
} ${className ?? ""}`}
```
Set the border + inset highlight via `style` (primary gets the inset):
```tsx
style={{
  border: isPrimary ? "1px solid transparent" : "1px solid var(--color-hairline)",
  boxShadow: isPrimary ? "inset 0 1px 0 rgba(255,255,255,.08)" : undefined,
  ...style,
}}
```
Delete the `onMouseEnter`/`onMouseLeave` handlers entirely. (The `transition-[transform]` + `active:scale` gives the spring press; reduced-motion neutralizes it via the global kill-switch.)

- [ ] **Step 2: Refine `Toast` motion + elevation**

In `Toast.tsx` `ToastRow`, change the transition to glide easing and add the float shadow. Update the className `ease-[var(--motion-easing)]` → `ease-[var(--ease-glide)]`, `transitionDuration: "var(--motion-base)"` stays, and add `boxShadow: "var(--shadow-float)"` to the row `style`. Enter offset stays `translateY(8px)` (glide slide-up). No JS change — the existing `entered`/`leaving` state already drives it.

- [ ] **Step 3: Verify**

Run: `cd web && npx vitest run && npx tsc -b --noEmit`
Expected: 130 pass, tsc clean. (No test asserts Button hover internals; if one does, update it to the CSS-class contract.)

- [ ] **Step 4: Commit**

```bash
git add web/src/components/form/Button.tsx web/src/components/Toast.tsx
git commit -m "feat(ui): button press feedback + focus ring (CSS), toast glide+elevation (panel polish)"
```

---

### Task 3: `SectionGroup` + `statusMarker` primitives

**Files:**
- Create: `web/src/components/panel/SectionGroup.tsx`
- Modify: `web/src/lib/panelDeliver.ts` (add `statusMarker`)
- Test: `web/src/lib/panelDeliver.test.ts`

**Interfaces:**
- `SectionGroup({ title?, meta?, action?, children, first? })` — a borderless group; a hairline top border separates consecutive groups (skipped when `first`). `title` renders in `text-body` weight 600 ink (NOT an uppercase gray eyebrow); `meta` (muted, right) and `action` (a right-aligned node, e.g. an "Edit" link) are optional.
- `statusMarker(status: string): { label: string; color: string }` — pure; `color` is the status var, `label` is the display token (WIP/TR/CR/FINAL/custom uppercased). Reuses `statusBadgeTone` for the tone→var mapping.

- [ ] **Step 1: Write failing test**

Add to `web/src/lib/panelDeliver.test.ts`:
```ts
import { statusMarker } from "./panelDeliver";

describe("statusMarker", () => {
  it("maps each review status to its color var + label", () => {
    expect(statusMarker("")).toEqual({ label: "WIP", color: "var(--color-status-neutral)" });
    expect(statusMarker("TR")).toEqual({ label: "TR", color: "var(--color-status-warn)" });
    expect(statusMarker("CR")).toEqual({ label: "CR", color: "var(--color-status-info)" });
    expect(statusMarker("FINAL")).toEqual({ label: "FINAL", color: "var(--color-status-pass)" });
  });
  it("custom status keeps its label at the neutral (wip) tone", () => {
    expect(statusMarker("REV02")).toEqual({ label: "REV02", color: "var(--color-status-neutral)" });
  });
});
```

- [ ] **Step 2: Run → fail**

Run: `cd web && npx vitest run src/lib/panelDeliver.test.ts` → FAIL (statusMarker missing).

- [ ] **Step 3: Implement `statusMarker` in `panelDeliver.ts`**

```ts
const TONE_VAR: Record<ReturnType<typeof statusBadgeTone>, string> = {
  wip: "var(--color-status-neutral)",
  tr: "var(--color-status-warn)",
  cr: "var(--color-status-info)",
  final: "var(--color-status-pass)",
};

/** Version status → a dot+text marker: the status color var + the display
 * label (blank status = WIP). One source of truth for how a version's
 * review state renders across the panel (Recent list, etc.) — dot+text, not
 * a filled pill (lighter in a dense list, and color-blind-safe because the
 * text carries the meaning). */
export function statusMarker(status: string): { label: string; color: string } {
  return { label: status || "WIP", color: TONE_VAR[statusBadgeTone(status)] };
}
```

- [ ] **Step 4: Create `SectionGroup.tsx`**

```tsx
import type { ReactNode } from "react";

/** A borderless section group (panel polish / de-slop): replaces the
 * repeated `rounded-lg border p-3 surface-1` card shell in the stacked-config
 * sections. Consecutive groups separate with a hairline top border (skipped
 * for `first`); the title is a normal-weight-600 ink heading, NOT an
 * uppercase gray eyebrow. `meta` (muted, right of title) and `action` (a
 * right-aligned node) are optional. Cards are kept only where a block is a
 * real card (Overview KPIs, QC FAIL/WARN) — not here. */
export function SectionGroup({
  title,
  meta,
  action,
  children,
  first = false,
}: {
  title?: string;
  meta?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  first?: boolean;
}) {
  return (
    <section
      className={first ? "pb-4" : "border-t pt-4 pb-4"}
      style={{ borderColor: "var(--color-hairline)" }}
    >
      {(title || action) && (
        <div className="mb-2 flex items-baseline justify-between gap-3">
          <div className="flex items-baseline gap-2">
            {title && (
              <h3 className="text-body font-semibold" style={{ color: "var(--color-ink)" }}>
                {title}
              </h3>
            )}
            {meta && (
              <span className="text-caption" style={{ color: "var(--color-muted)" }}>
                {meta}
              </span>
            )}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
```

- [ ] **Step 5: Verify**

Run: `cd web && npx vitest run src/lib/panelDeliver.test.ts` → PASS. `npx vitest run` → all pass. `npx tsc -b --noEmit` → clean.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/panel/SectionGroup.tsx web/src/lib/panelDeliver.ts web/src/lib/panelDeliver.test.ts
git commit -m "feat(panel): SectionGroup + statusMarker primitives (de-slop) (panel polish)"
```

---

### Task 4: Apply de-slop to the stacked sections

**Files:**
- Modify: `web/src/components/panel/DeliverSection.tsx`, `RenderSection.tsx`, `FrameSubview.tsx`, `ToolsSection.tsx`

**Transformation (apply to each stacked block in these 4 sections):**
- Replace the bordered-card shell `<div className="... rounded-lg border p-3" style={{surface-1 + hairline}}>` + its uppercase `text-label` eyebrow (`<p className="text-label" style={{ink-secondary}}>TITLE</p>`) with `<SectionGroup title="Title" first={isFirst}>...children...</SectionGroup>` (title in normal case, e.g. "Recent versions" not "RECENT VERSIONS"). The FIRST group in a section gets `first`.
- Keep the block's status line + actions as the group's children (unchanged handlers).
- Unify spacing: the section wrapper stays `flex flex-col p-3` but drop the inter-card `gap-3` (SectionGroup owns its own `pt-4 pb-4`); actions rows use `gap-3`.

- [ ] **Step 1: DeliverSection**

- The 4 blocks (Version / Recent Versions / Notes / Deliver) → 4 `SectionGroup`s (Version `first`). Titles: "Version" (or fold the last-version line as the group body with no title), "Recent versions", "Notes" (action = the Edit link), "Deliver".
- In the Recent list, replace the `VersionBadge` (filled pill) render with the dot+text marker: `const m = statusMarker(entry.status);` then `<span className="inline-flex items-center gap-1.5"><span className="h-[7px] w-[7px] shrink-0 rounded-full" style={{ backgroundColor: m.color }} /><span className="text-caption font-semibold" style={{ color: m.color }}>{m.label}</span></span>`. (The `VersionBadge` component + `BADGE_TONE_VARS` can be removed if now unused — verify no other consumer.)
- The `Save Version` button stays `variant="primary"`. The filter chips → keep as-is or a segmented look (out of strict scope; leave the chips, just ensure spacing rhythm).

- [ ] **Step 2: RenderSection**

- The 5 blocks (Preset / Sentinel Frame / AOVs / Snapshots / Post-Render), currently `RenderBlock`-shelled → route each through `SectionGroup` (title = the block name in normal case; the per-block status line becomes the group body). If `RenderBlock` is a shared shell used only here, refactor it to render a `SectionGroup` internally (single edit, all 5 benefit) rather than editing 5 call sites. Keep the confirm bar + AOV expand behavior; the confirm bar keeps `--shadow-float` (Task 5).

- [ ] **Step 3: FrameSubview**

- The blocks (hint / Sentinel Frame / Subjects / QC #12) → the hint line stays as-is (warn-tinted panel), the other three → `SectionGroup` (titles "Sentinel Frame", "Subjects", "QC #12 · Cross-Aspect Safe Area" in normal case). Keep the `← Render` back button.

- [ ] **Step 4: ToolsSection**

- The groups (Layout & Hierarchy / Animation / QC Marking) → `SectionGroup` (first = Layout). Titles in normal case ("Layout & hierarchy", "Animation", "QC marking"). Button grid unchanged.

- [ ] **Step 5: Verify**

Run: `cd web && npx vitest run` → all pass (section vitest don't assert style classes; if a test asserts an eyebrow's uppercase text, update it). `npx tsc -b --noEmit` → clean. Remove any now-unused imports (`VersionBadge`/`BADGE_TONE_VARS` if orphaned).

- [ ] **Step 6: Commit**

```bash
git add web/src/components/panel/DeliverSection.tsx web/src/components/panel/RenderSection.tsx web/src/components/panel/FrameSubview.tsx web/src/components/panel/ToolsSection.tsx
git commit -m "feat(panel): de-slop stacked sections (SectionGroup + dot+text status) (panel polish)"
```

---

### Task 5: Confirm-bar/expand glide + state-change pop; card sections get hover/press

**Files:**
- Modify: `web/src/index.css` (a `@keyframes pop` + a `.pop` utility, and a reusable expand/collapse pattern if needed)
- Modify: the confirm bars + expandable regions (`QcSection.tsx` Info expand, the confirm bars wherever they render — `DeliverSection`/`RenderSection`/`FrameSubview`/`PanelPage`), and `OverviewCards.tsx`/`QcCard.tsx` (keep cards, add press/hover)
- Modify: `PanelHeader.tsx` (QC score pop on change)

- [ ] **Step 1: Add a `pop` keyframe to `index.css`**

```css
@keyframes sentinel-pop {
  0% { transform: scale(1); }
  45% { transform: scale(1.08); }
  100% { transform: scale(1); }
}
.animate-pop { animation: sentinel-pop var(--motion-base) var(--ease-spring); }
```

- [ ] **Step 2: Confirm bar + inline expand → glide**

For the confirm bars (open-version confirm, QC/Render destructive confirm) and the QC Info expand: ensure they mount with a glide fade+translate (e.g. a small `translateY(-4px)`→`0` + opacity via a mount flag like Toast's `entered`, using `--ease-glide`). If a shared confirm-bar element exists, edit it once; else apply the same tiny mount-transition pattern. Add `boxShadow: var(--shadow-float)` to the confirm bar (it floats over content). Keep behavior identical.

- [ ] **Step 3: QC score pop on change (`PanelHeader`)**

When the QC score value changes between renders (compare previous via a ref), apply `.animate-pop` to the score number for one cycle. Gate strictly on a real value change — NEVER on every 2s poll (if the value is unchanged, no pop). Reduced-motion neutralizes it via the global kill-switch.

- [ ] **Step 4: Card sections keep cards but gain hover/press**

`OverviewCards`/`QcCard`: the cards stay (border + tint), but their action buttons already use `Button` (now with press/focus from Task 2). Ensure any bespoke clickable rows in these cards use a `--motion-fast` background transition on hover. No de-box here.

- [ ] **Step 5: Verify**

Run: `cd web && npx vitest run && npx tsc -b --noEmit` → all pass, clean.

- [ ] **Step 6: Commit**

```bash
git add web/src/index.css web/src/components/panel/QcSection.tsx web/src/components/panel/PanelHeader.tsx web/src/components/panel/DeliverSection.tsx web/src/pages/PanelPage.tsx web/src/components/panel/OverviewCards.tsx web/src/components/panel/QcCard.tsx
git commit -m "feat(panel): confirm/expand glide + QC-score pop; card sections hover/press (panel polish)"
```

---

### Task 6: Build, version bump, docs

**Files:**
- Modify: `plugin/sentinel/__init__.py` (`PLUGIN_VERSION` → `1.26.0`)
- Rebuild: `plugin/web/`
- Modify: `CLAUDE.md`, `.superpowers/sdd/progress.md`, memory

- [ ] **Step 1: Bump version** — `1.25.1` → `1.26.0`.
- [ ] **Step 2: Build** — `cd web && npm run build`.
- [ ] **Step 3: Suites** — `python3 -m pytest -q` (0 failures) + `cd web && npx vitest run` (0 failures).
- [ ] **Step 4: Docs** — `CLAUDE.md` header v1.26.0 + a v1.26.0 Version History entry (motion tokens + de-slop; panel only; Reports/Hub/forms propagation deferred); `.superpowers/sdd/progress.md` ledger; memory `project_overview.md` note the panel got a motion+de-slop polish, propagation pending.
- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/__init__.py plugin/web CLAUDE.md .superpowers/sdd/progress.md
git commit -m "chore: build + v1.26.0 — panel polish (motion + de-slop)"
```

---

## Self-Review

**Spec coverage:** tokens+reduced-motion (T1) ✓; press feedback/focus + toast (T2) ✓; SectionGroup + statusMarker (T3) ✓; de-slop the 4 stacked sections + dot+text status (T4) ✓; confirm/expand glide + state pop + cards keep card w/ hover-press (T5) ✓; build/version/docs (T6) ✓. Out-of-scope (Reports/Hub/forms, consumer bounces, IA) not touched.

**Placeholder scan:** T1-T3 carry full code. T4-T5 describe the transformation precisely (SectionGroup swap, statusMarker render snippet, confirm-bar mount pattern) rather than transcribing 4 full sections — the primitive (T3) + the exact replacement pattern is the spec; each section's content is unchanged. No "add appropriate X".

**Consistency:** `statusMarker` (T3) returns `{label,color}` consumed by the DeliverSection Recent render (T4). Tokens (T1: `--ease-glide`/`--ease-spring`/`--motion-*`/`--shadow-float`) are consumed by Button/Toast (T2), SectionGroup (T3), confirm/pop (T5). `statusBadgeTone` already exists (v1.24) and is reused, not reinvented.
