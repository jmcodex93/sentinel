import { useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { ToastProvider } from "./components/ToastProvider";
import { DeliverySummaryPage } from "./pages/DeliverySummaryPage";
import { DoctorPage } from "./pages/DoctorPage";
import { GateTriagePage } from "./pages/GateTriagePage";
import { HubPage } from "./pages/HubPage";
import { NotesPage } from "./pages/NotesPage";
import { PalettePage } from "./pages/PalettePage";
import { PanelPage } from "./pages/PanelPage";
import { QcReportPage } from "./pages/QcReportPage";
import { RenderValidationPage } from "./pages/RenderValidationPage";
import { SaveVersionPage } from "./pages/SaveVersionPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SupervisorPage } from "./pages/SupervisorPage";

export type ReportPage = "delivery" | "qc" | "doctor" | "supervisor" | "render";
export type FormPage = "form/save_version" | "form/notes" | "form/settings" | "form/gate";
// Not a form/* op page (no state/submit — see web_ops.py palette/actions +
// palette/run), but hosted the same way: its own FormDialog window, no
// Sidebar. Kept as a distinct union member (not folded into FormPage) so
// FormApp's per-page switch stays exhaustive and self-documenting.
export type PalettePageId = "palette";
// Asset Hub (Phase 5) — its own full-bleed window, same as the form/palette
// pages (no Sidebar entry, not a ReportPage). Kept as a distinct union
// member for the same reason PalettePageId is: it has no `form/` op prefix
// and no state/submit shape, just its own page component.
export type HubPageId = "hub";
// The Fase 6.0 dockable Panel SPA — its own full-bleed window, same
// non-Sidebar/non-ReportPage treatment as HubPageId/PalettePageId above (no
// `form/` op prefix, no state/submit shape, just its own page component).
export type PanelPageId = "panel";
export type Page = ReportPage | FormPage | PalettePageId | HubPageId | PanelPageId;

const REPORT_PAGES: ReportPage[] = ["delivery", "qc", "doctor", "supervisor", "render"];
const FORM_PAGES: FormPage[] = ["form/save_version", "form/notes", "form/settings", "form/gate"];
const PALETTE_PAGES: PalettePageId[] = ["palette"];
const HUB_PAGES: HubPageId[] = ["hub"];
const PANEL_PAGES: PanelPageId[] = ["panel"];
const PAGES: Page[] = [...REPORT_PAGES, ...FORM_PAGES, ...PALETTE_PAGES, ...HUB_PAGES, ...PANEL_PAGES];

// Smallest possible deep-link: the C4D host opens the SPA with a
// `?page=<name>` query param (see reports_dialog.py ReportsDialog, and
// Phase 4 Task 4's FormDialog for the form/* pages) so a native button can
// land the artist directly on e.g. the Doctor page or the Save Version form
// instead of always defaulting to Delivery. Read once at mount — the SPA
// still has no router/history, so navigating in-app just calls setPage as
// before and does not update the URL.
function initialPage(): Page {
  try {
    const requested = new URLSearchParams(window.location.search).get("page");
    if (requested && (PAGES as string[]).includes(requested)) {
      return requested as Page;
    }
  } catch {
    // window/URLSearchParams unavailable in this host — fall through
  }
  return "delivery";
}

function isFormPage(page: Page): page is FormPage {
  return (FORM_PAGES as string[]).includes(page);
}

function isPalettePage(page: Page): page is PalettePageId {
  return (PALETTE_PAGES as string[]).includes(page);
}

function isHubPage(page: Page): page is HubPageId {
  return (HUB_PAGES as string[]).includes(page);
}

function isPanelPage(page: Page): page is PanelPageId {
  return (PANEL_PAGES as string[]).includes(page);
}

/** Sentinel form pages (Save Version, Notes, Settings, Gate Triage) and the
 * Command Palette are each hosted one-per-window by a small native
 * `FormDialog` (Phase 4 Task 4) — no Sidebar, full-bleed canvas, each form
 * page owns its own header/footer via `FormPageShell` (the Palette is its
 * own compact layout, see PalettePage.tsx). `onNavigate` lets a palette
 * `kind: "navigate"` result (e.g. picking "Save Version…") switch THIS SAME
 * window to the target form page client-side, no second native dialog. */
function FormApp({
  page,
  onNavigate,
}: {
  page: FormPage | PalettePageId | HubPageId | PanelPageId;
  onNavigate: (page: Page) => void;
}) {
  return (
    <div className="h-screen" style={{ backgroundColor: "var(--color-canvas)" }}>
      {page === "form/save_version" && <SaveVersionPage />}
      {page === "form/notes" && <NotesPage />}
      {page === "form/settings" && <SettingsPage />}
      {page === "form/gate" && <GateTriagePage />}
      {page === "palette" && <PalettePage onNavigate={onNavigate} />}
      {page === "hub" && <HubPage />}
      {page === "panel" && <PanelPage />}
    </div>
  );
}

function ReportsApp({ page, onNavigate }: { page: ReportPage; onNavigate: (page: ReportPage) => void }) {
  return (
    <div className="flex h-screen" style={{ backgroundColor: "var(--color-canvas)" }}>
      <Sidebar active={page} onNavigate={onNavigate} />
      <main className="flex flex-1 flex-col overflow-hidden">
        {page === "delivery" && <DeliverySummaryPage />}
        {page === "qc" && <QcReportPage />}
        {page === "doctor" && <DoctorPage />}
        {page === "supervisor" && <SupervisorPage />}
        {page === "render" && <RenderValidationPage />}
      </main>
    </div>
  );
}

function App() {
  const [page, setPage] = useState<Page>(initialPage);

  return (
    <ToastProvider>
      {isFormPage(page) || isPalettePage(page) || isHubPage(page) || isPanelPage(page) ? (
        <FormApp page={page} onNavigate={setPage} />
      ) : (
        <ReportsApp page={page} onNavigate={setPage} />
      )}
    </ToastProvider>
  );
}

export default App;
