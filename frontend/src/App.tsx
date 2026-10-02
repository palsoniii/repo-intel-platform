import { Link, NavLink, Navigate, Route, Routes } from "react-router-dom";
import HomePage from "./product/HomePage";
import RepoLayout from "./product/RepoLayout";
import ResearchPage from "./product/ResearchPage";
import OverviewTab from "./product/tabs/OverviewTab";
import GraphTab from "./product/tabs/GraphTab";
import ArchitectureTab from "./product/tabs/ArchitectureTab";
import ApiTab from "./product/tabs/ApiTab";
import ModelsTab from "./product/tabs/ModelsTab";
import DependenciesTab from "./product/tabs/DependenciesTab";
import FilesTab from "./product/tabs/FilesTab";
import AskTab from "./product/tabs/AskTab";
import ComparisonPage from "./pages/ComparisonPage";

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
    isActive
      ? "bg-slate-900 text-white dark:bg-white dark:text-slate-900"
      : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
  }`;

export default function App() {
  return (
    <div className="flex min-h-svh flex-col">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/85 backdrop-blur dark:border-slate-800 dark:bg-slate-950/85">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-6 py-3">
          <Link to="/" className="flex items-center gap-2.5">
            <Logo />
            <span className="font-semibold tracking-tight">RepoIntel</span>
          </Link>
          <nav className="flex gap-1">
            <NavLink to="/" end className={navLinkClass}>
              Analyze
            </NavLink>
            <NavLink to="/research" className={navLinkClass}>
              Research
            </NavLink>
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-8">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/repo/:id" element={<RepoLayout />}>
            <Route index element={<Navigate to="overview" replace />} />
            <Route path="overview" element={<OverviewTab />} />
            <Route path="graph" element={<GraphTab />} />
            <Route path="architecture" element={<ArchitectureTab />} />
            <Route path="api" element={<ApiTab />} />
            <Route path="models" element={<ModelsTab />} />
            <Route path="dependencies" element={<DependenciesTab />} />
            <Route path="files" element={<FilesTab />} />
            <Route path="ask" element={<AskTab />} />
          </Route>
          <Route path="/research" element={<ResearchPage />} />
          <Route path="/research/live" element={<ComparisonPage />} />
          <Route path="/research/live/:repoName" element={<ComparisonPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      <footer className="border-t border-slate-200 py-4 text-center text-xs text-slate-400 dark:border-slate-800">
        Static analysis with tree-sitter · knowledge graph in Neo4j · local LLMs via Ollama · Express.js &amp; NestJS
      </footer>
    </div>
  );
}

function Logo() {
  return (
    <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" className="fill-indigo-600" />
      <g stroke="white" strokeWidth="2" strokeLinecap="round" fill="white">
        <line x1="10" y1="11" x2="21" y2="9" />
        <line x1="10" y1="11" x2="13" y2="22" />
        <line x1="21" y1="9" x2="22" y2="21" />
        <line x1="13" y1="22" x2="22" y2="21" />
        <circle cx="10" cy="11" r="2.6" stroke="none" />
        <circle cx="21" cy="9" r="2.6" stroke="none" />
        <circle cx="13" cy="22" r="2.6" stroke="none" />
        <circle cx="22" cy="21" r="2.6" stroke="none" />
      </g>
    </svg>
  );
}
