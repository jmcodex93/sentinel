import { useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { DeliverySummaryPage } from "./pages/DeliverySummaryPage";
import { DoctorPage } from "./pages/DoctorPage";
import { QcReportPage } from "./pages/QcReportPage";
import { RenderValidationPage } from "./pages/RenderValidationPage";
import { SupervisorPage } from "./pages/SupervisorPage";

export type Page = "delivery" | "qc" | "doctor" | "supervisor" | "render";

function App() {
  const [page, setPage] = useState<Page>("delivery");

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
