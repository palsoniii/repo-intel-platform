import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { api, useSystem, type Analysis, type Stage } from "../lib/product";
import { ApiError } from "../lib/api";
import { Button, Chip, ErrorBox, Icon, Loading, Spinner, frameworkLabel, languageLabel, type IconName } from "./ui";

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

// Seven destinations, ordered by what a newcomer asks first: what is it, can I ask
// it something, how is it built, then the details.
const TABS: { path: string; label: string; icon: IconName; also?: string[] }[] = [
  { path: "overview", label: "Overview", icon: "overview" },
  { path: "ask", label: "Ask", icon: "ask" },
  { path: "architecture", label: "Architecture", icon: "layers" },
  { path: "graph", label: "Knowledge graph", icon: "graph" },
  { path: "api", label: "API", icon: "api" },
  { path: "models", label: "Data models", icon: "database" },
  { path: "files", label: "Code", icon: "code", also: ["dependencies"] },
];

const STEPS: { stage: Stage; label: string; detail: string; timing: string }[] = [
  { stage: "cloning", label: "Downloading the repository", detail: "Shallow clone from GitHub", timing: "clone" },
  { stage: "parsing", label: "Reading the code", detail: "Static analysis with tree-sitter", timing: "parse" },
  { stage: "indexing", label: "Mapping the structure", detail: "Layers, data models and request flows", timing: "index" },
];
const ORDER: Stage[] = ["queued", "cloning", "parsing", "indexing", "graph", "summarizing", "done"];

export default function RepoLayout() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  // The public deployment always serves the stored analysis, so re-analysing is off.
  const system = useSystem();
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

  const inFlight =
    analysis &&
    (analysis.status === "queued" ||
      analysis.status === "running" ||
      analysis.summary_status === "pending" ||
      analysis.summary_status === "running" ||
      analysis.stage === "graph");
  useEffect(() => {
    if (!inFlight) return;
    const t = setTimeout(() => void refresh(), analysis?.status === "ready" ? 2500 : 800);
    return () => clearTimeout(t);
  }, [analysis, inFlight, refresh]);

  if (error && !analysis) return <ErrorBox>{error}</ErrorBox>;
  if (!analysis) return <Loading />;

  async function reanalyze() {
    if (!analysis) return;
    const fresh = await api.createAnalysis(analysis.url, true);
    navigate(`/repo/${fresh.id}/overview`);
  }

  const section = location.pathname.split("/")[3] ?? "overview";
  const summaryBusy = analysis.summary_status === "running" || analysis.summary_status === "pending";

  return (
    <RepoContext.Provider value={{ analysis, refresh }}>
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm text-muted">{analysis.owner}</p>
          <h1 className="truncate text-[28px] font-semibold leading-tight tracking-[-0.02em] text-ink">{analysis.repo_name}</h1>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {analysis.framework && <Chip tone="accent">{frameworkLabel(analysis.framework)}</Chip>}
            {analysis.metadata?.detected_language && <Chip>{languageLabel(analysis.metadata.detected_language)}</Chip>}
            {analysis.commit_sha && (
              <Chip>
                <span className="font-mono" title={analysis.commit_sha}>
                  {analysis.commit_sha.slice(0, 7)}
                </span>
              </Chip>
            )}
            {analysis.graph_status === "stored" && <Chip tone="success">Saved to Neo4j</Chip>}
            {analysis.status === "ready" && summaryBusy && (
              <Chip>
                <Spinner className="h-3 w-3" /> Writing summary
              </Chip>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          <a href={analysis.url} target="_blank" rel="noreferrer">
            <Button variant="secondary">
              <Icon name="external" className="h-3.5 w-3.5" /> GitHub
            </Button>
          </a>
          {system && !system.public && (analysis.status === "ready" || analysis.status === "failed") && (
            <Button variant="secondary" onClick={reanalyze} title="Clone and analyse the latest commit again">
              <Icon name="refresh" className="h-3.5 w-3.5" /> Re-analyze
            </Button>
          )}
        </div>
      </header>

      {analysis.status === "failed" ? (
        <ErrorBox>
          <p className="font-medium">This analysis failed</p>
          <p className="mt-1 opacity-90">{analysis.error}</p>
        </ErrorBox>
      ) : analysis.status !== "ready" ? (
        <Progress stage={analysis.stage} timings={analysis.timings} />
      ) : (
        <>
          <nav className="scroll-quiet -mx-1 mb-8 flex gap-1 overflow-x-auto border-b border-line px-1">
            {TABS.map((t) => {
              const active = section === t.path || (t.also ?? []).includes(section);
              return (
                <NavLink
                  key={t.path}
                  to={t.path}
                  className={`relative flex items-center gap-2 whitespace-nowrap px-3 pb-3 pt-1 text-sm font-medium transition-colors ${
                    active ? "text-ink" : "text-muted hover:text-ink"
                  }`}
                >
                  <Icon name={t.icon} className="h-4 w-4" />
                  {t.label}
                  {active && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-ink" />}
                </NavLink>
              );
            })}
          </nav>
          <div key={section} className="animate-in">
            <Outlet />
          </div>
        </>
      )}
    </RepoContext.Provider>
  );
}

function Progress({ stage, timings }: { stage: Stage; timings: Record<string, number> }) {
  const current = ORDER.indexOf(stage);
  return (
    <div className="mx-auto max-w-md py-12">
      <div className="rounded-2xl border border-line bg-surface p-6 shadow-pop">
        <p className="font-semibold text-ink">Analyzing the repository</p>
        <p className="mt-1 text-sm text-ink-2">Usually a few seconds. The dashboard opens as soon as the structure is mapped.</p>
        <ol className="mt-6 space-y-4">
          {STEPS.map((s) => {
            const idx = ORDER.indexOf(s.stage);
            const state = idx < current ? "done" : idx === current ? "active" : "todo";
            const t = timings[s.timing];
            return (
              <li key={s.stage} className="flex items-center gap-3">
                <span
                  className={`flex h-7 w-7 items-center justify-center rounded-full border text-xs ${
                    state === "done"
                      ? "border-transparent bg-ink text-page"
                      : state === "active"
                        ? "border-line-strong text-ink"
                        : "border-line text-muted"
                  }`}
                >
                  {state === "done" ? <Icon name="check" className="h-3.5 w-3.5" /> : state === "active" ? <Spinner className="h-3.5 w-3.5" /> : null}
                </span>
                <div className="flex-1">
                  <p className={`text-sm font-medium ${state === "todo" ? "text-muted" : "text-ink"}`}>{s.label}</p>
                  <p className="text-xs text-muted">{s.detail}</p>
                </div>
                {t !== undefined && <span className="text-xs tabular-nums text-muted">{t.toFixed(1)}s</span>}
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}
