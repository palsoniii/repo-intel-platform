import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, useSystem, type AnalysisBrief, type SystemStatus } from "../lib/product";
import { ApiError } from "../lib/api";
import { ErrorBox, Icon, Spinner, frameworkLabel, timeAgo, type IconName } from "./ui";

const EXAMPLES = [
  { url: "https://github.com/lujakob/nestjs-realworld-example-app", label: "NestJS RealWorld" },
  { url: "https://github.com/hagopj13/node-express-boilerplate", label: "Express boilerplate" },
  { url: "https://github.com/notiz-dev/nestjs-prisma-starter", label: "NestJS + Prisma" },
];

const STEPS: { icon: IconName; title: string; body: string }[] = [
  { icon: "code", title: "Parse", body: "tree-sitter reads every file: routes, classes, imports, data models." },
  { icon: "graph", title: "Connect", body: "A knowledge graph links them: imports, routes, services and models." },
  { icon: "sparkles", title: "Explain", body: "A language model summarises it and answers questions, grounded in that graph." },
];

export default function HomePage() {
  const navigate = useNavigate();
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recent, setRecent] = useState<AnalysisBrief[] | null>(null);
  const system = useSystem();

  useEffect(() => {
    api.listAnalyses().then(setRecent).catch(() => setRecent([]));
  }, []);

  async function analyze(target: string) {
    setError(null);
    setSubmitting(true);
    try {
      const a = await api.createAnalysis(target.trim());
      navigate(`/repo/${a.id}/overview`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
      setSubmitting(false);
    }
  }

  const seen = new Set<string>();
  const latest = (recent ?? []).filter((a) => {
    const key = a.url.toLowerCase();
    if (seen.has(key) || a.status === "failed") return false;
    seen.add(key);
    return true;
  });

  return (
    <div className="animate-in">
      <section className="relative mx-auto max-w-3xl pb-14 pt-10 text-center">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 -top-8 -z-10 mx-auto h-72 max-w-2xl opacity-60 blur-3xl"
          style={{ background: "radial-gradient(closest-side, var(--accent-soft), transparent)" }}
        />
        <p className="mb-5 inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-xs font-medium text-ink-2 shadow-card">
          <Icon name="sparkles" className="h-3.5 w-3.5 text-accent" />
          {system?.provider === "groq" ? "Static analysis, a knowledge graph, and AI" : "Runs entirely on this machine"}
        </p>
        <h1 className="text-[34px] font-semibold leading-[1.08] tracking-[-0.03em] text-ink sm:text-[56px]">
          Understand any backend
          <br />
          <span className="text-muted">in minutes, not days.</span>
        </h1>
        <p className="mx-auto mt-5 max-w-xl text-[17px] leading-relaxed text-ink-2">
          Paste a GitHub link to an Express.js or NestJS repository. Get its architecture,
          API, data models and a plain-English explanation.
        </p>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void analyze(url);
          }}
          className="mx-auto mt-9 flex max-w-2xl items-center gap-2 rounded-2xl border border-line bg-surface p-2 shadow-pop focus-within:border-line-strong"
        >
          <span className="pl-3 text-muted">
            <Icon name="search" className="h-5 w-5" />
          </span>
          <input
            type="url"
            required
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://github.com/owner/repository"
            disabled={submitting}
            className="h-11 min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-muted disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={submitting}
            className="flex h-11 items-center gap-2 rounded-xl bg-ink px-5 text-[15px] font-medium text-page transition hover:opacity-90 disabled:opacity-60"
          >
            {submitting ? <Spinner /> : null} Analyze
          </button>
        </form>

        <div className="mt-4 flex flex-wrap items-center justify-center gap-2 text-sm">
          <span className="text-muted">Try</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex.url}
              onClick={() => {
                setUrl(ex.url);
                void analyze(ex.url);
              }}
              disabled={submitting}
              className="rounded-full border border-line bg-surface px-3 py-1 text-ink-2 transition hover:border-line-strong hover:text-ink"
            >
              {ex.label}
            </button>
          ))}
        </div>

        {error && (
          <div className="mx-auto mt-6 max-w-2xl text-left">
            <ErrorBox>{error}</ErrorBox>
          </div>
        )}
        {system && <SystemLine system={system} />}
      </section>

      <section className="mb-16 grid gap-4 md:grid-cols-3">
        {STEPS.map((s, i) => (
          <div key={s.title} className="rounded-2xl border border-line bg-surface p-5 shadow-card">
            <div className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-sunken text-ink">
                <Icon name={s.icon} className="h-[18px] w-[18px]" />
              </span>
              <span className="text-xs font-medium text-muted">Step {i + 1}</span>
            </div>
            <p className="mt-4 font-semibold text-ink">{s.title}</p>
            <p className="mt-1 text-sm leading-relaxed text-ink-2">{s.body}</p>
          </div>
        ))}
      </section>

      {latest.length > 0 && (
        <section>
          <div className="mb-4 flex items-baseline justify-between">
            <h2 className="text-[15px] font-semibold tracking-tight">Analyzed repositories</h2>
            <span className="text-xs text-muted">Open instantly, no re-analysis</span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {latest.map((a) => (
              <Link
                key={a.id}
                to={`/repo/${a.id}/overview`}
                className="group min-w-0 rounded-2xl border border-line bg-surface p-5 shadow-card transition hover:-translate-y-0.5 hover:border-line-strong hover:shadow-pop"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-xs text-muted">{a.owner}</p>
                    <p className="mt-0.5 truncate font-semibold tracking-tight text-ink">{a.repo_name}</p>
                  </div>
                  <span className="rounded-md border border-line px-2 py-0.5 text-[11px] font-medium text-ink-2">
                    {a.status === "ready" ? frameworkLabel(a.framework) : "Analyzing…"}
                  </span>
                </div>
                {a.stats && (
                  <div className="mt-5 grid grid-cols-3 gap-2 border-t border-line pt-4">
                    <MiniStat value={a.stats.files} label="files" />
                    <MiniStat value={a.stats.endpoints} label="endpoints" />
                    <MiniStat value={a.stats.entities} label="models" />
                  </div>
                )}
                <div className="mt-4 flex items-center justify-between text-xs text-muted">
                  <span>{timeAgo(a.created_at)}</span>
                  <span className="flex items-center gap-1 opacity-0 transition group-hover:opacity-100">
                    Open <Icon name="arrow" className="h-3.5 w-3.5" />
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function MiniStat({ value, label }: { value: number; label: string }) {
  return (
    <div>
      <p className="text-lg font-semibold tracking-tight text-ink">{value}</p>
      <p className="text-[11px] text-muted">{label}</p>
    </div>
  );
}

function SystemLine({ system }: { system: SystemStatus }) {
  const items = [
    { ok: system.llm.reachable, label: system.provider === "groq" ? "Groq" : "Ollama" },
    { ok: !!system.llm.model_available, label: system.model },
    ...(system.neo4j.enabled ? [{ ok: !!system.neo4j.reachable, label: "Neo4j" }] : []),
  ];
  const allOk = items.every((i) => i.ok);
  return (
    <div className="mt-8 flex flex-wrap justify-center gap-x-5 gap-y-1 text-xs text-muted" title={allOk ? "Everything is running" : "Something isn't running"}>
      {items.map((i) => (
        <span key={i.label} className="flex items-center gap-1.5">
          <span className={`h-1.5 w-1.5 rounded-full ${i.ok ? "bg-success" : "bg-danger"}`} />
          {i.label}
          {!i.ok && <span className="text-danger">offline</span>}
        </span>
      ))}
    </div>
  );
}
