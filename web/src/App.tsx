import { useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { DeliverySummaryPage } from "./pages/DeliverySummaryPage";
import { DoctorPage } from "./pages/DoctorPage";
import { QcReportPage } from "./pages/QcReportPage";
import { RenderValidationPage } from "./pages/RenderValidationPage";
import { SupervisorPage } from "./pages/SupervisorPage";

export type Page = "delivery" | "qc" | "doctor" | "supervisor" | "render";

const PAGES: Page[] = ["delivery", "qc", "doctor", "supervisor", "render"];

// Smallest possible deep-link: the C4D host opens the SPA with a
// `?page=<name>` query param (see reports_dialog.py ReportsDialog) so a
// native button can land the artist directly on e.g. the Doctor or QC page
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

function App() {
  const [page, setPage] = useState<Page>(initialPage);

  return (
    <div className="flex h-screen" style={{ backgroundColor: "var(--color-canvas)" }}>
      <Sidebar active={page} onNavigate={setPage} />
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

export default App;
