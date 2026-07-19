import { Sidebar } from "./components/Sidebar";
import { DeliverySummaryPage } from "./pages/DeliverySummaryPage";

function App() {
  return (
    <div className="flex h-screen" style={{ backgroundColor: "var(--color-canvas)" }}>
      <Sidebar />
      <main className="flex flex-1 flex-col overflow-hidden">
        <DeliverySummaryPage />
      </main>
    </div>
  );
}

export default App;
