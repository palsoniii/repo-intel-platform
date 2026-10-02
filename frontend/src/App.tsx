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
import { Icon, type IconName } from "./product/ui";
import { useTheme, type ThemeChoice } from "./lib/theme";

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
    isActive ? "bg-sunken text-ink" : "text-ink-2 hover:text-ink"
  }`;

export default function App() {
  return (
    <div className="flex min-h-svh flex-col">
      <header className="sticky top-0 z-30 border-b border-line bg-page/80 backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-[1280px] items-center justify-between gap-2 px-4 sm:gap-4 sm:px-6">
          <Link to="/" className="flex items-center gap-2.5">
            <Logo />
            <span className="hidden text-[15px] font-semibold tracking-tight min-[400px]:inline">RepoIntel</span>
          </Link>
          <div className="flex items-center gap-2 sm:gap-3">
            <nav className="flex gap-1">
              <NavLink to="/" end className={navLinkClass}>
                Analyze
              </NavLink>
              <NavLink to="/research" className={navLinkClass}>
                Research
              </NavLink>
            </nav>
            <span className="hidden h-5 w-px bg-line sm:block" />
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1280px] flex-1 px-4 py-8 sm:px-6">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/repo/:id" element={<RepoLayout />}>
            <Route index element={<Navigate to="overview" replace />} />
            <Route path="overview" element={<OverviewTab />} />
            <Route path="ask" element={<AskTab />} />
            <Route path="architecture" element={<ArchitectureTab />} />
            <Route path="graph" element={<GraphTab />} />
            <Route path="api" element={<ApiTab />} />
            <Route path="models" element={<ModelsTab />} />
            <Route path="files" element={<FilesTab />} />
            <Route path="dependencies" element={<DependenciesTab />} />
          </Route>
          <Route path="/research" element={<ResearchPage />} />
          <Route path="/research/live" element={<ComparisonPage />} />
          <Route path="/research/live/:repoName" element={<ComparisonPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-[1280px] flex-wrap items-center justify-between gap-2 px-4 py-5 text-xs text-muted sm:px-6">
          <span>Static analysis with tree-sitter · knowledge graph in Neo4j · local models via Ollama</span>
          <span>Supports Express.js and NestJS</span>
        </div>
      </footer>
    </div>
  );
}

function ThemeToggle() {
  const [choice, setChoice] = useTheme();
  const options: { id: ThemeChoice; icon: IconName; label: string }[] = [
    { id: "light", icon: "sun", label: "Light" },
    { id: "dark", icon: "moon", label: "Dark" },
    { id: "system", icon: "monitor", label: "Match system" },
  ];
  return (
    <div className="flex rounded-lg border border-line bg-surface p-0.5" role="radiogroup" aria-label="Theme">
      {options.map((o) => (
        <button
          key={o.id}
          role="radio"
          aria-checked={choice === o.id}
          title={o.label}
          aria-label={o.label}
          onClick={() => setChoice(o.id)}
          className={`flex h-7 w-7 items-center justify-center rounded-md transition ${
            choice === o.id ? "bg-sunken text-ink" : "text-muted hover:text-ink"
          }`}
        >
          <Icon name={o.icon} className="h-3.5 w-3.5" />
        </button>
      ))}
    </div>
  );
}

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="var(--ink)" />
      <g stroke="var(--page)" strokeWidth="2" strokeLinecap="round">
        <line x1="10" y1="11" x2="21" y2="9" />
        <line x1="10" y1="11" x2="13" y2="22" />
        <line x1="21" y1="9" x2="22" y2="21" />
        <line x1="13" y1="22" x2="22" y2="21" />
      </g>
      <g fill="var(--page)">
        <circle cx="10" cy="11" r="2.6" />
        <circle cx="21" cy="9" r="2.6" />
        <circle cx="13" cy="22" r="2.6" />
      </g>
      <circle cx="22" cy="21" r="3" fill="var(--accent)" />
    </svg>
  );
}
