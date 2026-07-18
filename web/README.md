# Sentinel Reports — web source

Vite + React 18 + TypeScript + Tailwind SPA for Sentinel Reports (dockable
HTML report surfaces hosted inside Cinema 4D, starting with Delivery
Summary). This is the **source**; the committed build lives in
`../plugin/web/` — Sentinel artists don't have Node installed, so the
built assets ship in the repo, not the source.

Read `docs/design/DESIGN.md` before touching any visual value — every
color/spacing/radius here comes from that file's tokens (see
`src/tokens.css`), not from invention.

## Dev workflow

```bash
cd web
npm ci               # or npm install on first setup
npm run dev           # Vite dev server with HMR
```

Open `http://localhost:5173/?mock=1` — `?mock=1` serves the bundled fixture
(`src/mock/delivery-summary.json`) instead of calling
`/api/report/delivery`, so the page is fully workable without a running
Cinema 4D / Sentinel Reports server behind it. Drop the `?mock=1` once the
C4D-hosted server (Task 4, `plugin/sentinel/ui/reports_dialog.py`) is
running on `127.0.0.1:834x` and proxy or point the dev server at it if you
need to iterate against a live manifest.

Before syncing the plugin to Cinema 4D (or committing), rebuild:

```bash
npm run build          # tsc -b && vite build -> ../plugin/web/ (emptied + rewritten)
```

`npm run build` **must** be run and its output committed alongside any
source change — `plugin/web/` is what actually ships; nothing rebuilds it
at plugin-load time.

## Mock data — no client names

`src/mock/delivery-summary.json` is the only fixture committed to a public
repo. It is **fully anonymized**: generic `robot_010`-style scene/asset
names, no real client, product, or shot identifiers. When updating this
fixture from a real delivery manifest for shape reference, anonymize
before committing — never paste real production paths, client names, or
shot IDs into anything under `web/`.

## Fonts

Inter ships locally as variable woff2 (`public/fonts/InterVariable.woff2`,
`InterVariable-Italic.woff2`) — no CDN, no network fetch at runtime, same
pattern the design system calls for. `public/fonts/LICENSE.txt` is Inter's
OFL 1.1 license; keep it alongside the font files if you ever update them.

## Payload contract

`GET /api/report/delivery` (plus `?manifest=<path>` / any other query
params, forwarded as-is) is expected to return the `DeliveryReport` shape
defined in `src/types.ts`, or `{"error": "no_manifest"}` /
`{"error": <message>}` for the empty/error states. See
`docs/superpowers/plans/2026-07-18-ui-foundation.md` (Task 3 Interfaces)
for the canonical contract and `plugin/sentinel/manifest.py` for the real
manifest fields it's built from.
