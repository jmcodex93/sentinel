import { useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { ToastProvider } from "./components/ToastProvider";
import { DeliverySummaryPage } from "./pages/DeliverySummaryPage";
import { DoctorPage } from "./pages/DoctorPage";
import { GateTriagePage } from "./pages/GateTriagePage";
import { NotesPage } from "./pages/NotesPage";
import { QcReportPage } from "./pages/QcReportPage";
import { RenderValidationPage } from "./pages/RenderValidationPage";
import { SaveVersionPage } from "./pages/SaveVersionPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SupervisorPage } from "./pages/SupervisorPage";

export type ReportPage = "delivery" | "qc" | "doctor" | "supervisor" | "render";
export type FormPage = "form/save-version" | "form/notes" | "form/settings" | "form/gate";
export type Page = ReportPage | FormPage;

const REPORT_PAGES: ReportPage[] = ["delivery", "qc", "doctor", "supervisor", "render"];
const FORM_PAGES: FormPage[] = ["form/save-version", "form/notes", "form/settings", "form/gate"];
const PAGES: Page[] = [...REPORT_PAGES, ...FORM_PAGES];

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

/** Sentinel form pages (Save Version, Notes, Settings, Gate Triage) are
 * hosted one-per-window by a small native `FormDialog` (Phase 4 Task 4) —
 * no Sidebar, full-bleed canvas, each page owns its own header/footer via
 * `FormPageShell`. */
function FormApp({ page }: { page: FormPage }) {
  return (
    <div className="h-screen" style={{ backgroundColor: "var(--color-canvas)" }}>
      {page === "form/save-version" && <SaveVersionPage />}
      {page === "form/notes" && <NotesPage />}
      {page === "form/settings" && <SettingsPage />}
      {page === "form/gate" && <GateTriagePage />}
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
      {isFormPage(page) ? <FormApp page={page} /> : <ReportsApp page={page} onNavigate={setPage} />}
    </ToastProvider>
  );
}

export default App;
