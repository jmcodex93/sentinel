---
version: 1.0.0
name: Sentinel-design-system
description: "A Linear-adapted dark system for a Cinema 4D plugin, evolved rather than invented — Sentinel already runs inside a #2b2b2b host chrome, so the canvas lifts to #101113 (Linear's near-black, warmed just enough to read as a distinct surface against C4D's neutral gray rather than punching a hole in it). Two more surface steps (#17181b, #1c1d20) carry panels, cards, and hover states, with hairline borders at 6% and 8% white opacity doing the separating work instead of shadows. Light ink (#f7f8f8) carries headlines and body; a secondary and a muted step step text down for meta and disabled content. The system has exactly one chromatic accent — Linear lavender #5e6ad2 (hover #828fff) — reserved for CTAs, focus rings, and active/selected state, and it never marks pass/fail/warning. All other chroma in the system is reserved for status: fail, warn, pass, and neutral each own one color, used nowhere else. Inter carries HTML surfaces (Sentinel Reports, served locally, woff2 packaged the way Overseer packages its fonts); native GeDialog surfaces keep the OS/C4D system font, because embedding Inter into a native widget isn't worth the SDK fight — the two flavors of the same system converge on tokens, not on font rendering."

colors:
  canvas: "#101113"
  surface-1: "#17181b"
  surface-2: "#1c1d20"
  ink: "#f7f8f8"
  ink-secondary: "#b6b9be"
  muted: "#6b6f76"
  hairline: "rgba(255,255,255,.06)"
  hairline-strong: "rgba(255,255,255,.08)"
  primary: "#5e6ad2"
  primary-hover: "#828fff"
  on-primary: "#ffffff"
  status-fail: "#e0655f"
  status-warn: "#ffb74d"
  status-pass: "#68b06a"
  status-neutral: "#8a8a8a"

typography:
  title:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: -0.01em
  subhead:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: 500
    lineHeight: 1.5
    letterSpacing: 0
  body:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 0
  label:
    fontFamily: Inter
    fontSize: 12.5px
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: 0
  caption:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: 0

rounded:
  sm: 4px
  md: 6px
  lg: 8px
  xl: 10px

spacing:
  unit: 8px
  xxs: 4px
  xs: 8px
  sm: 16px
  md: 16px
  lg: 24px
  xl: 32px
  section: 16px
  section-lg: 18px
  table-row: 32px

motion:
  fast: 100ms
  base: 150ms
  easing: ease

components:
  report-page:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    padding: "{spacing.section}"
    rounded: "{rounded.xl}"
  report-page-header:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    typography: "{typography.title}"
    padding: "{spacing.section-lg}"
    borderBottom: "1px {colors.hairline-strong}"
  kpi-card:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    typography: "{typography.body-lg}"
    rounded: "{rounded.lg}"
    padding: "{spacing.md}"
    border: "1px {colors.hairline}"
  table-row:
    height: "{spacing.table-row}"
    backgroundColor: "{colors.canvas}"
    backgroundColorHover: "{colors.surface-2}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    borderBottom: "1px {colors.hairline}"
    transition: "{motion.fast} {motion.easing}"
  badge:
    backgroundColor: "status-tint-10pct"
    textColor: "status-color"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "2px 6px"
  status-strip:
    height: 22px
    backgroundColorPass: "status-pass-tint-15pct"
    backgroundColorFail: "status-fail-tint-15pct"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    padding: "0 {spacing.xxs}"
  toast:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: "{spacing.sm} {spacing.md}"
    border: "1px {colors.hairline-strong}"
    duration: 4000ms
    actionColor: "{colors.primary}"
  segmented-control:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink-secondary}"
    textColorActive: "{colors.ink}"
    activeFill: "{colors.surface-2}"
    activeAccent: "{colors.primary}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "4px"
    transition: "{motion.base} {motion.easing}"
  button-primary:
    backgroundColor: "{colors.primary}"
    backgroundColorHover: "{colors.primary-hover}"
    textColor: "{colors.on-primary}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "6px 12px"
    transition: "{motion.fast} {motion.easing}"
  button-secondary:
    backgroundColor: "{colors.surface-2}"
    backgroundColorHover: "{colors.surface-1}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "6px 12px"
    border: "1px {colors.hairline}"
    transition: "{motion.fast} {motion.easing}"
---

## For agents — read this before ANY UI work

This file is the source of truth for every value used in Sentinel's UI. Before
touching any dialog, `GeUserArea`, or HTML report surface, read this document
top to bottom — do not invent a color, size, or radius that isn't a token
here. If a value you need doesn't exist yet, add it to this file first (as
its own small change), then use it — don't hardcode a one-off.

Two flavors of one system live side by side:

- **Native** (`GeDialog`, `gui.GeUserArea`, `QuickTab`) — scene interaction.
  Colors are `c4d.Vector(r, g, b)` with each channel `0.0–1.0`, computed as
  `hex_channel / 255`. Font is the OS/C4D system font, not Inter — embedding
  a custom font family into native C4D widgets isn't supported without a
  fight, so native surfaces converge with HTML on color/spacing/radius
  tokens only, never on font rendering.
- **HTML** (Sentinel Reports, served by the local stdlib server, Phase 1+) —
  read-only report surfaces and, from Phase 4, interactive forms. Inter is
  packaged locally as woff2 (Overseer pattern — no CDN, no network fetch).

### Native ↔ HTML equivalence table

| Native (exists today) | HTML equivalent (new) | Shared tokens |
|---|---|---|
| `AssetHubHeaderArea` | `report-page-header` | `colors.surface-1`, `typography.title` |
| `PreflightStripArea` | `status-strip` | `colors.status-pass`, `colors.status-fail` |
| `QuickTab` | `segmented-control` | `colors.primary` (active), `colors.surface-1` |
| `AssetListArea` | table (`table-row` × N) | `spacing.table-row` (32px), `colors.hairline` |
| result caption (`GeDialog` static text) | `toast` | `colors.surface-2`, `typography.body`, 4s duration |
| native `GeDialog` button (`BFH_SCALEFIT` etc.) | `button-primary` / `button-secondary` | none yet — native buttons keep OS chrome; no token bridge exists for them |

### Native token reference (`c4d.Vector`)

Computed as `c4d.Vector(hex.r/255, hex.g/255, hex.b/255)`. C4D has no native
alpha channel for `DrawSetPen` fills, so `hairline`/`hairline-strong` (HTML
alphas over `canvas`) resolve to flat native equivalents instead — the
closest opaque color a hairline reads as when composited over `{colors.canvas}`.

| Token | Hex | `c4d.Vector` |
|---|---|---|
| `colors.canvas` | `#101113` | `c4d.Vector(0.063, 0.067, 0.075)` |
| `colors.surface-1` | `#17181b` | `c4d.Vector(0.090, 0.094, 0.106)` |
| `colors.surface-2` | `#1c1d20` | `c4d.Vector(0.110, 0.114, 0.125)` |
| `colors.ink` | `#f7f8f8` | `c4d.Vector(0.969, 0.973, 0.973)` |
| `colors.ink-secondary` | `#b6b9be` | `c4d.Vector(0.714, 0.725, 0.745)` |
| `colors.muted` | `#6b6f76` | `c4d.Vector(0.420, 0.435, 0.463)` |
| `colors.primary` | `#5e6ad2` | `c4d.Vector(0.369, 0.416, 0.824)` |
| `colors.primary-hover` | `#828fff` | `c4d.Vector(0.510, 0.561, 1.000)` |
| `colors.on-primary` | `#ffffff` | `c4d.Vector(1.000, 1.000, 1.000)` |
| `colors.status-fail` | `#e0655f` | `c4d.Vector(0.878, 0.396, 0.373)` |
| `colors.status-warn` | `#ffb74d` | `c4d.Vector(1.000, 0.718, 0.302)` |
| `colors.status-pass` | `#68b06a` | `c4d.Vector(0.408, 0.690, 0.416)` |
| `colors.status-neutral` | `#8a8a8a` | `c4d.Vector(0.541, 0.541, 0.541)` |
| `colors.hairline` (flat) | `#1e1f21` | `c4d.Vector(0.118, 0.122, 0.129)` |
| `colors.hairline-strong` (flat) | `#232426` | `c4d.Vector(0.137, 0.141, 0.149)` |

The two hairline rows are not literal token values — `hairline`/`hairline-strong`
are alpha overlays (6%/8% white) in HTML, and `DrawSetPen` has no alpha
channel natively. Each flat hex is `{colors.canvas}` composited with white at
that alpha (`result = alpha*255 + (1-alpha)*canvas_channel` per channel) —
the opaque color a hairline reads as once it's actually drawn over the
canvas, since in practice every hairline in this system sits on `canvas`.

**Known drift (not fixed by this task — docs only):** the existing Asset Hub
constants in `plugin/sentinel/ui/user_areas.py` predate this system and are
close but not identical: `_COL_HUB_HEADER_ORANGE = c4d.Vector(1.00, 0.718,
0.302)` is an exact match for `colors.status-warn`; `_COL_HUB_HEADER_RED =
c4d.Vector(0.898, 0.451, 0.451)` (`#e57373`) is close but not identical to
`colors.status-fail` (`#e0655f`). Reconcile these when a UI task next touches
that file — don't rewrite it as a side effect of this doc.

## Overview

Sentinel's chrome lives inside Cinema 4D's neutral `#2b2b2b` host — a plain
port of Linear's `#010102` canvas would read as a black hole punched through
the C4D gray, so `{colors.canvas}` lifts to `#101113`, still near-black but
legible as a deliberate surface next to the host. A three-step ladder
(`canvas` → `{colors.surface-1}` → `{colors.surface-2}`) carries panels,
cards, and hover states, separated by hairline borders (`{colors.hairline}`
at 6% white, `{colors.hairline-strong}` at 8%) instead of shadows — shadows
don't read against a host window that already has its own drop shadow.

`{colors.ink}` (`#f7f8f8`) carries headlines and body text, stepping down
through `{colors.ink-secondary}` for meta/caption text and `{colors.muted}`
for disabled or de-emphasized content.

The system has **exactly one chromatic accent**: Linear lavender
`{colors.primary}` (`#5e6ad2`, hover `{colors.primary-hover}` `#828fff`),
used only for CTAs, focus rings, links, and active/selected state — **never**
to mark pass/fail/warn. State has its own exclusive palette (see Colors
below); the two never overlap, so a lavender highlight is always
"this is interactive/selected," never "this passed" or "this failed."

**Key characteristics:**
- Canvas lifted from Linear's near-black to `#101113` — legible against a
  `#2b2b2b` C4D host instead of punching a hole in it.
- One accent (`{colors.primary}`), reserved for interaction, never state.
- Four status colors, each exclusive to one meaning: fail, warn, pass,
  neutral — never reused decoratively.
- Hairlines over shadows — flat surfaces separated by 1px borders.
- Two flavors, one token set: native `GeDialog`/`GeUserArea` (system font,
  `c4d.Vector` colors) and HTML Sentinel Reports (Inter, CSS tokens) share
  every color, spacing, and radius value — they diverge only on font family.
- Modal is reserved for blocking decisions; everything else (results,
  summaries, confirmations) surfaces as toast, caption, or a Sentinel
  Reports page — see Rules.

## Colors

### Surface
- **Canvas** (`{colors.canvas}`): Default background for HTML report pages
  and native dialog body — `#101113`.
- **Surface 1** (`{colors.surface-1}`): First lift — headers, KPI cards,
  panel backgrounds, `AssetHubHeaderArea` equivalent.
- **Surface 2** (`{colors.surface-2}`): Second lift — hovered rows, toast
  background, active segmented-control fill.
- **Hairline** (`{colors.hairline}`): 1px dividers, default card/row
  borders — 6% white over the surface beneath it.
- **Hairline Strong** (`{colors.hairline-strong}`): Emphasized borders —
  report page header rule, toast border, input focus outline.

### Text
- **Ink** (`{colors.ink}`): Headlines, primary body, table cell values —
  `#f7f8f8`.
- **Ink Secondary** (`{colors.ink-secondary}`): Meta text, secondary column
  values, unselected segmented-control labels — `#b6b9be`.
- **Muted** (`{colors.muted}`): Disabled state, placeholder text, the
  quietest tier — `#6b6f76`.

### Accent (interaction only)
- **Primary** (`{colors.primary}`): The single chromatic accent —
  `button-primary`, focus rings, links, active tab/segment. `#5e6ad2`.
- **Primary Hover** (`{colors.primary-hover}`): Hover state of the accent —
  `#828fff`.
- **On Primary** (`{colors.on-primary}`): Text/icon color on top of a
  primary-filled surface — `#ffffff`.
- **Primary Tint Ramp** (`{colors.primary-tint-32/26/20/14/08/04}`): a 6-step,
  single-hue ramp of `--color-primary` at 32%/26%/20%/14%/8%/4% alpha —
  accent-scale chip backgrounds for a PROPERTY, not a state, where intensity
  communicates magnitude (the Asset Hub's 16K/8K/4K/2K/1K/sm resolution
  chips, darkest→lightest); never a substitute for a status tint.

### Status (exclusive to state — the accent never marks state)

These four colors are **intocables**: each means exactly one thing, is used
nowhere else in the system, and never trades places with `{colors.primary}`.
A badge, strip, or table cell is either accent-colored (interactive) or
status-colored (informational about pass/fail/warn) — never both at once.

- **Fail** (`{colors.status-fail}`, `#e0655f`): Missing assets, failing QC
  checks, blocking gate rows.
- **Warn** (`{colors.status-warn}`, `#ffb74d`): Absolute paths, WARN-severity
  QC checks, size-outlier flags.
- **Pass** (`{colors.status-pass}`, `#68b06a`): Collected/OK assets, passing
  QC checks, clean preflight strips.
- **Neutral** (`{colors.status-neutral}`, `#8a8a8a`): Read-only/disabled
  checks, informational rows with no pass/fail verdict (e.g. "1 disabled").

## Typography

Inter carries HTML report surfaces (packaged locally as woff2, no network
fetch — same pattern Overseer uses to avoid a CDN dependency). Native
`GeDialog`/`GeUserArea` surfaces use the OS/C4D system font; the two flavors
share color/spacing/radius tokens but never font rendering.

| Token | Size | Weight | Line Height | Tracking | Use |
|---|---|---|---|---|---|
| `{typography.title}` | 20px | 600 | 1.25 | -0.01em | Report page title (e.g. "Delivery Summary") |
| `{typography.subhead}` | 18px | 600 | 1.30 | -0.01em | Section headers within a report |
| `{typography.body-lg}` | 15px | 500 | 1.50 | 0 | KPI card values, emphasized inline text |
| `{typography.body}` | 13px | 400 | 1.50 | 0 | Default body — table cells, paragraphs |
| `{typography.label}` | 12.5px | 500 | 1.40 | 0 | Buttons, badges, segmented-control labels, table headers |
| `{typography.caption}` | 11px | 400 | 1.40 | 0 | Meta text, timestamps, toast secondary line |

**Principles:**
- Negative tracking (-0.01em) is reserved for titles/subheads — body,
  labels, and captions carry 0 tracking (dense UI text doesn't benefit from
  the display-style tightening Linear applies at 40–80px).
- Only three weights exist: 400 (body/caption), 500 (labels/emphasis), 600
  (titles/subheads). No 700 — Sentinel Reports are dense information
  surfaces, not marketing pages.

## Layout

### Spacing — 8px grid

- **Base unit**: `{spacing.unit}` = 8px. Every spacing value is a multiple
  of 8px, with a 4px half-step (`{spacing.xxs}`) allowed only for icon-tight
  gaps (badge padding, icon-to-label spacing).
- **Table rows**: `{spacing.table-row}` = 32px — the fixed row height for
  every table in Sentinel Reports and the native `AssetListArea` equivalent.
- **Section padding**: `{spacing.section}` 16px is the default; dense report
  headers (`report-page-header`) may use `{spacing.section-lg}` 18px when
  the header carries a title + meta line and needs the extra breathing room.
- **Card padding**: `{spacing.md}` 16px inside `kpi-card`.
- **Toast padding**: `{spacing.sm}` 16px vertical / `{spacing.md}` 16px
  horizontal (see `toast` component — uses the shorthand `16px 16px`,
  written as `{spacing.sm} {spacing.md}`).

### Motion

- **Fast** (`{motion.fast}`, 100ms): Row hover, button hover — anything that
  tracks the cursor directly.
  <br>
- **Base** (`{motion.base}`, 150ms): Segmented-control active-state
  transition, toast enter/exit.
- **Easing**: `ease` throughout — no spring/bounce curves. Sentinel is a
  production tool; motion should confirm state changed, not entertain.

## Shapes

| Token | Value | Use |
|---|---|---|
| `{rounded.sm}` | 4px | Badges, status chips |
| `{rounded.md}` | 6px | Buttons, inputs, segmented-control track |
| `{rounded.lg}` | 8px | Cards — `kpi-card`, `toast` |
| `{rounded.xl}` | 10px | `report-page` container, native dialog-hosted surfaces |

**Reconciliation note:** the controlling spec says "radius 8-10px" (a
surface-level range); the task brief's control scale said `sm 4 / md 6-8 /
lg 10`. This 4-step scale resolves both: `sm`/`md` stay tight for
interactive chrome (4-6px, unchanged from the brief), while `lg`/`xl` land
inside the spec's 8-10px surface range — cards at 8px, page-level containers
at 10px — instead of collapsing every non-interactive surface onto a single
10px value.

Sentinel never uses pill radius — badges and buttons stay rectangular with
`{rounded.sm}`/`{rounded.md}` corners, matching the native `GeUserArea` rows
they sit next to (native C4D widgets don't have soft corners; HTML corners
stay modest so the two flavors don't visually clash when a report is opened
next to the panel).

## Components

### `report-page` / `report-page-header`

The container for every Sentinel Reports page (Delivery Summary, QC Report,
Doctor, Supervisor). `report-page` is the scroll container — `{colors.canvas}`
background, `{spacing.section}` outer padding, `{rounded.xl}` corners on the
outer frame (relevant when hosted inside a dockable/floating window; a
full-bleed page has no visible corner). `report-page-header` is a
`{colors.surface-1}` band pinned at the top — scene/delivery identity in
`{typography.title}`, a `{colors.hairline-strong}` bottom rule separating it
from the content below. Native equivalent: `AssetHubHeaderArea`.

### `kpi-card`

A single stat tile (e.g. "12 assets · 2 missing"). `{colors.surface-1}`
background, `{rounded.lg}` corners, `{spacing.md}` padding, 1px
`{colors.hairline}` border. Value text is `{typography.body-lg}`; label
underneath is `{typography.caption}` in `{colors.ink-secondary}`. The value
itself is only status-colored when it represents a count of that status
(e.g. a "2 missing" card's number sits in `{colors.status-fail}`) — never
accent-colored.

### `table-row`

One row in a Sentinel Reports table or the native `AssetListArea`.
Fixed `{spacing.table-row}` (32px) height, `{typography.body}` text,
`{colors.canvas}` background with `{colors.surface-2}` on hover
(`{motion.fast}` transition), 1px `{colors.hairline}` bottom border. Native
equivalent: `AssetListArea` row.

### `badge`

A small status chip inside a table cell or KPI card (e.g. "missing",
"absolute", "OK"). Background is a ~10% tint of the relevant status color
over the row's surface, text is the full-strength status color,
`{typography.label}`, `{rounded.sm}` corners, `2px 6px` padding. Badge color
is **always** one of the four status colors — never the accent.

### `status-strip`

A full-width bar summarizing pass/fail state for a report or section (e.g.
QC preflight). 22px height, `{typography.label}` text, background is a ~15%
tint of `{colors.status-pass}` when clear or `{colors.status-fail}` when not
— darker tints than the badge because the strip covers more area. Native
equivalent: `PreflightStripArea` (which today uses a warn-tinted amber for
"failing," not fail-red — Reconcile note above).

### `toast`

The default surface for **results**, per the anti-popup rule: `{colors.surface-2}`
background, `{rounded.lg}` corners, `1px {colors.hairline-strong}` border,
`{typography.body}` text. Auto-dismisses after 4000ms; clickable through to
the relevant Sentinel Reports page via an `actionColor` link in
`{colors.primary}` — the one place a toast may show the accent, because the
link itself is an interactive affordance, not a status indicator. Native
equivalent: the existing `GeDialog` result caption.

### `segmented-control`

Tab-style switcher (e.g. report type, QC filter). `{colors.surface-1}` track,
`{rounded.md}` corners, `4px` inner padding. Inactive segments show
`{colors.ink-secondary}` text; the active segment lifts to `{colors.surface-2}`
fill with `{colors.ink}` text, and its underline/indicator is the one
non-interactive-adjacent use of `{colors.primary}` (marking "selected," not
"passed"). `{motion.base}` transition on the active-state move. Native
equivalent: `QuickTab`.

### `button-primary` / `button-secondary`

`button-primary` — the accent CTA: `{colors.primary}` background (hover
`{colors.primary-hover}`), `{colors.on-primary}` text, `{typography.label}`,
`{rounded.md}` corners, `6px 12px` padding, `{motion.fast}` hover transition.
Reserved for the single primary action on a surface (e.g. "Verify" on a
Delivery Summary).

`button-secondary` — `{colors.surface-2}` background (hover `{colors.surface-1}`),
`{colors.ink}` text, same type/radius/padding as primary, plus a 1px
`{colors.hairline}` border. Used for every non-primary action.

## Rules

1. **Modal is reserved for blocking decisions only.** If the user must
   choose before Sentinel can proceed (Gate Triage, an overwrite
   confirmation, a required comment), it's a modal. Everything else —
   a completed action, a summary, a validation result — is a `toast`, an
   inline caption, or a page in Sentinel Reports. This is the anti-popup
   rule driving the ~112-popup triage; when in doubt, it is not a modal.
2. **Color carries semantics only.** `{colors.status-fail}`,
   `{colors.status-warn}`, `{colors.status-pass}`, and `{colors.status-neutral}`
   are the only colors allowed to mean something about state. `{colors.primary}`
   never appears on a pass/fail/warn indicator, and no other hue is
   introduced for decoration.
3. **Hover and focus states are mandatory, not optional**, on every
   interactive component (`table-row`, `button-*`, `segmented-control`,
   toast action link). Transition duration is `{motion.fast}` (100ms) for
   direct cursor-tracking, `{motion.base}` (150ms) for state changes —
   never longer, never a spring curve.
4. **Everything sits on the 8px grid.** Padding, gaps, and row heights are
   multiples of `{spacing.unit}` (8px), with `{spacing.xxs}` (4px) as the
   only permitted half-step, reserved for icon-tight spacing.
