import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import AnalyzePage from "./pages/AnalyzePage";
import SummaryPage from "./pages/SummaryPage";
import DiagramPage from "./pages/DiagramPage";
import ComparisonPage from "./pages/ComparisonPage";

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
    isActive
      ? "bg-indigo-600 text-white"
      : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
  }`;

const disabledClass =
  "rounded-md px-3 py-1.5 text-sm font-medium text-slate-400 cursor-not-allowed " +
  "dark:text-slate-600";

// The per-repo tabs previously pointed at a hardcoded placeholder repo
// (heroku/node-js-getting-started), which is not in the evaluation set -- so every tab
// advertised a repository nobody had analysed. Instead, remember whichever repo the
// current session is actually looking at, taken from the /repo/:name/... route, and
// disable the tabs until there is one.
function useCurrentRepo(): string | null {
  const location = useLocation();
  const [repo, setRepo] = useState<string | null>(null);

  useEffect(() => {
    const m = location.pathname.match(/^\/repo\/([^/]+)\//);
    if (m) setRepo(m[1]);
  }, [location.pathname]);

  return repo;
}

export default function App() {
  const repoSlug = useCurrentRepo();

  const perRepoTabs: Array<{ label: string; path: string }> = [
    { label: "Summary", path: "summary" },
    { label: "Diagram", path: "diagram" },
    { label: "Comparison", path: "comparison" },
  ];

  return (
    <div className="mx-auto flex min-h-svh max-w-5xl flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 px-6 py-4 dark:border-slate-800">
        <div>
          <h1 className="text-lg font-semibold">Repository Intelligence Platform</h1>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Clone -&gt; tree-sitter parse -&gt; Neo4j -&gt; context -&gt; local LLM. All
            figures shown are measured; this dashboard displays no sample data.
          </p>
        </div>
        <nav className="flex gap-2">
          <NavLink to="/" end className={navLinkClass}>
            Analyze
          </NavLink>
          {perRepoTabs.map(({ label, path }) =>
            repoSlug ? (
              <NavLink key={path} to={`/repo/${repoSlug}/${path}`} className={navLinkClass}>
                {label}
              </NavLink>
            ) : (
              <span
                key={path}
                className={disabledClass}
                title="Analyze a repository first -- these views are per-repository."
                aria-disabled="true"
              >
                {label}
              </span>
            ),
          )}
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
