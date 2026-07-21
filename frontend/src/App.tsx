import { NavLink, Route, Routes } from "react-router-dom";
import AnalyzePage from "./pages/AnalyzePage";
import SummaryPage from "./pages/SummaryPage";
import DiagramPage from "./pages/DiagramPage";
import ComparisonPage from "./pages/ComparisonPage";
import { mockAnalysis } from "./lib/mockData";

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
    isActive
      ? "bg-indigo-600 text-white"
      : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
  }`;

export default function App() {
  const repoSlug = encodeURIComponent(mockAnalysis.repoName);

  return (
    <div className="mx-auto flex min-h-svh max-w-5xl flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 px-6 py-4 dark:border-slate-800">
        <div>
          <h1 className="text-lg font-semibold">Repository Intelligence Platform</h1>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Dashboard shell -- fake data, wired to a real backend in Week 2
          </p>
        </div>
        <nav className="flex gap-2">
          <NavLink to="/" end className={navLinkClass}>
            Analyze
          </NavLink>
          <NavLink to={`/repo/${repoSlug}/summary`} className={navLinkClass}>
            Summary
          </NavLink>
          <NavLink to={`/repo/${repoSlug}/diagram`} className={navLinkClass}>
            Diagram
          </NavLink>
          <NavLink to={`/repo/${repoSlug}/comparison`} className={navLinkClass}>
            Comparison
          </NavLink>
        </nav>
      </header>

      <main className="flex-1 px-6 py-8">
        <Routes>
          <Route path="/" element={<AnalyzePage />} />
          <Route path="/repo/:repoName/summary" element={<SummaryPage />} />
          <Route path="/repo/:repoName/diagram" element={<DiagramPage />} />
          <Route path="/repo/:repoName/comparison" element={<ComparisonPage />} />
        </Routes>
      </main>
    </div>
  );
}
