import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate, useParams } from "react-router-dom";
import { api, type Analysis, type Stage } from "../lib/product";
import { ApiError } from "../lib/api";
import { ErrorBox, Loading, Pill, Spinner, frameworkLabel } from "./ui";

interface RepoContextValue {
  analysis: Analysis;
  refresh: () => Promise<void>;
}

const RepoContext = createContext<RepoContextValue | null>(null);

export function useRepo(): RepoContextValue {
  const ctx = useContext(RepoContext);
  if (!ctx) throw new Error("useRepo must be used inside RepoLayout");
  return ctx;
}

const TABS = [
  { path: "overview", label: "Overview" },
  { path: "graph", label: "Knowledge graph" },
  { path: "architecture", label: "Architecture" },
  { path: "api", label: "API" },
  { path: "models", label: "Data models" },
  { path: "dependencies", label: "Dependencies" },
  { path: "files", label: "Files" },
  { path: "ask", label: "Ask" },
];

const STEPS: { stage: Stage; label: string; detail: string }[] = [
  { stage: "cloning", label: "Clone", detail: "Shallow clone from GitHub" },
  { stage: "parsing", label: "Parse", detail: "tree-sitter static analysis" },
  { stage: "indexing", label: "Index", detail: "Layers, data models, request flows" },
  { stage: "graph", label: "Knowledge graph", detail: "Write to Neo4j" },
  { stage: "summarizing", label: "Summary", detail: "Local LLM writes the overview" },
];
const ORDER: Stage[] = ["queued", "cloning", "parsing", "indexing", "graph", "summarizing", "done"];

export default function RepoLayout() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setAnalysis(await api.analysis(id));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't load this analysis.");
    }
  }, [id]);

  useEffect(() => {
    setAnalysis(null);
    void refresh();
  }, [refresh]);

  // Poll while anything is still in flight: fast during the structural stages (a few
  // seconds in total), slower while the model writes the summary (~30s+).
  const inFlight =
    analysis &&
    (analysis.status === "queued" ||
      analysis.status === "running" ||
      analysis.summary_status === "pending" ||
      analysis.summary_status === "running" ||
      analysis.stage === "graph");
  useEffect(() => {
    if (!inFlight) return;
    const ready = analysis?.status === "ready";
    const t = setTimeout(() => void refresh(), ready ? 2500 : 900);
    return () => clearTimeout(t);
  }, [analysis, inFlight, refresh]);

  if (error && !analysis) return <ErrorBox>{error}</ErrorBox>;
  if (!analysis) return <Loading />;

  async function reanalyze() {
    if (!analysis) return;
    const fresh = await api.createAnalysis(analysis.url, true);
    navigate(`/repo/${fresh.id}/overview`);
  }

  return (
    <RepoContext.Provider value={{ analysis, refresh }}>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <a
            href={analysis.url}
            target="_blank"
            rel="noreferrer"
            className="text-sm text-slate-500 hover:text-indigo-600 dark:text-slate-400"
          >
            {analysis.owner} /
          </a>
          <h2 className="truncate text-2xl font-semibold tracking-tight">{analysis.repo_name}</h2>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {analysis.framework && <Pill tone="indigo">{frameworkLabel(analysis.framework)}</Pill>}
            {analysis.metadata?.detected_language && <Pill>{analysis.metadata.detected_language}</Pill>}
            {analysis.commit_sha && (
              <span className="font-mono text-xs text-slate-500 dark:text-slate-400" title={analysis.commit_sha}>
                @{analysis.commit_sha.slice(0, 7)}
              </span>
            )}
            {analysis.graph_status === "stored" && (
              <Pill tone="emerald">
                <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-emerald-500" /> Stored in Neo4j
              </Pill>
            )}
            {analysis.status === "ready" && analysis.summary_status === "running" && (
              <Pill tone="amber">
                <Spinner className="mr-1 h-3 w-3" /> Writing summary
              </Pill>
            )}
          </div>
        </div>
        {(analysis.status === "ready" || analysis.status === "failed") && (
          <button
            onClick={reanalyze}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
            title="Clone and analyse the latest commit again"
          >
            Re-analyze
          </button>
        )}
      </header>

      {analysis.status === "failed" ? (
        <ErrorBox>
          <p className="font-medium">This analysis failed.</p>
          <p className="mt-1">{analysis.error}</p>
        </ErrorBox>
      ) : analysis.status !== "ready" ? (
        <Progress stage={analysis.stage} timings={analysis.timings} />
      ) : (
        <>
          <nav className="-mx-1 mb-6 flex gap-1 overflow-x-auto border-b border-slate-200 pb-px dark:border-slate-800">
            {TABS.map((t) => (
              <NavLink
                key={t.path}
                to={t.path}
                className={({ isActive }) =>
                  `whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                    isActive
                      ? "border-indigo-600 text-indigo-700 dark:border-indigo-400 dark:text-indigo-300"
                      : "border-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
                  }`
                }
              >
                {t.label}
              </NavLink>
            ))}
          </nav>
          <Outlet />
        </>
      )}
    </RepoContext.Provider>
  );
}

function Progress({ stage, timings }: { stage: Stage; timings: Record<string, number> }) {
  const current = ORDER.indexOf(stage);
  const keys: Record<string, string> = { cloning: "clone", parsing: "parse", indexing: "index", graph: "graph" };
  return (
    <div className="mx-auto max-w-xl py-8">
      <ol className="space-y-3">
        {STEPS.slice(0, 3).map((s) => {
          const idx = ORDER.indexOf(s.stage);
          const state = idx < current ? "done" : idx === current ? "active" : "todo";
          const t = timings[keys[s.stage]];
          return (
            <li key={s.stage} className="flex items-center gap-3">
              <span
                className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold ${
                  state === "done"
                    ? "bg-emerald-500 text-white"
                    : state === "active"
                      ? "bg-indigo-600 text-white"
                      : "bg-slate-200 text-slate-500 dark:bg-slate-800"
                }`}
              >
                {state === "done" ? "✓" : state === "active" ? <Spinner className="h-3.5 w-3.5" /> : ""}
              </span>
              <div className="flex-1">
                <p className={`text-sm font-medium ${state === "todo" ? "text-slate-400" : ""}`}>{s.label}</p>
                <p className="text-xs text-slate-500 dark:text-slate-400">{s.detail}</p>
              </div>
              {t !== undefined && <span className="text-xs tabular-nums text-slate-400">{t.toFixed(1)}s</span>}
            </li>
          );
        })}
      </ol>
      <p className="mt-6 text-center text-xs text-slate-500 dark:text-slate-400">
        The dashboard opens as soon as parsing finishes. The knowledge graph and the AI summary
        keep building in the background.
      </p>
    </div>
  );
}
