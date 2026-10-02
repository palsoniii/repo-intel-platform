import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type AnalysisBrief, type SystemStatus } from "../lib/product";
import { ApiError } from "../lib/api";
import { ErrorBox, Pill, Spinner, frameworkLabel, timeAgo } from "./ui";

const EXAMPLES = [
  { url: "https://github.com/lujakob/nestjs-realworld-example-app", label: "NestJS RealWorld" },
  { url: "https://github.com/hagopj13/node-express-boilerplate", label: "Express boilerplate" },
  { url: "https://github.com/notiz-dev/nestjs-prisma-starter", label: "NestJS + Prisma" },
  { url: "https://github.com/bradtraversy/node_passport_login", label: "Express + Passport" },
];

const FEATURES = [
  ["Knowledge graph", "Every file, class, endpoint and data model, and how they connect."],
  ["Architecture", "Layered diagram of the codebase, generated without an LLM."],
  ["API & request flow", "Each endpoint traced through middleware, services and models."],
  ["Ask the repo", "Questions answered by a local model, grounded in the actual source."],
];

export default function HomePage() {
  const navigate = useNavigate();
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recent, setRecent] = useState<AnalysisBrief[] | null>(null);
  const [system, setSystem] = useState<SystemStatus | null>(null);

  useEffect(() => {
    api.listAnalyses().then(setRecent).catch(() => setRecent([]));
    api.system().then(setSystem).catch(() => setSystem(null));
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
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  return (
    <div>
      <section className="mx-auto max-w-3xl pb-10 pt-6 text-center">
        <h2 className="text-4xl font-semibold tracking-tight sm:text-5xl">
          Understand any backend <span className="text-indigo-600 dark:text-indigo-400">in minutes</span>
        </h2>
        <p className="mx-auto mt-4 max-w-2xl text-slate-600 dark:text-slate-400">
          Paste a GitHub link to an Express.js or NestJS repository. We parse it statically, build a
          knowledge graph, and explain it with a local LLM: no code leaves this machine.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void analyze(url);
          }}
          className="mx-auto mt-8 flex max-w-2xl gap-2"
        >
          <input
            type="url"
            required
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://github.com/owner/repo"
            disabled={submitting}
            className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-4 py-3 text-base shadow-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900"
          />
          <button
            type="submit"
            disabled={submitting}
            className="flex items-center gap-2 whitespace-nowrap rounded-lg bg-indigo-600 px-5 py-3 font-medium text-white shadow-sm hover:bg-indigo-500 disabled:opacity-60"
          >
            {submitting && <Spinner />} Analyze
          </button>
        </form>
        <div className="mt-4 flex flex-wrap justify-center gap-2 text-sm">
          <span className="text-slate-500 dark:text-slate-400">Try:</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex.url}
              onClick={() => {
                setUrl(ex.url);
                void analyze(ex.url);
              }}
              disabled={submitting}
              className="rounded-full border border-slate-300 px-3 py-0.5 text-slate-700 hover:border-indigo-400 hover:text-indigo-700 dark:border-slate-700 dark:text-slate-300"
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

      <section className="mb-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {FEATURES.map(([title, body]) => (
          <div key={title} className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
            <p className="font-medium">{title}</p>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{body}</p>
          </div>
        ))}
      </section>

      {latest.length > 0 && (
        <section>
          <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Analyzed repositories
          </h3>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {latest.map((a) => (
              <Link
                key={a.id}
                to={`/repo/${a.id}/overview`}
                className="group rounded-xl border border-slate-200 p-4 transition hover:border-indigo-400 hover:shadow-sm dark:border-slate-800 dark:hover:border-indigo-500"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-xs text-slate-500 dark:text-slate-400">{a.owner}</p>
                    <p className="truncate font-medium group-hover:text-indigo-700 dark:group-hover:text-indigo-300">
                      {a.repo_name}
                    </p>
                  </div>
                  {a.status === "failed" ? (
                    <Pill tone="rose">Failed</Pill>
                  ) : a.status !== "ready" ? (
                    <Pill tone="amber">Running</Pill>
                  ) : (
                    a.framework && <Pill tone="indigo">{frameworkLabel(a.framework)}</Pill>
                  )}
                </div>
                {a.stats && (
                  <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
                    {a.stats.files} files · {a.stats.endpoints} endpoints · {a.stats.entities} models
                  </p>
                )}
                <p className="mt-1 text-xs text-slate-400">{timeAgo(a.created_at)}</p>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function SystemLine({ system }: { system: SystemStatus }) {
  const items = [
    { ok: system.ollama.reachable, label: "Ollama" },
    { ok: system.summary_model_installed, label: system.summary_model },
    { ok: system.neo4j.reachable, label: "Neo4j" },
  ];
  return (
    <div className="mt-6 flex justify-center gap-4 text-xs text-slate-500 dark:text-slate-400">
      {items.map((i) => (
        <span key={i.label} className="flex items-center gap-1.5" title={i.ok ? "Available" : "Not available"}>
          <span className={`h-2 w-2 rounded-full ${i.ok ? "bg-emerald-500" : "bg-rose-500"}`} />
          {i.label}
        </span>
      ))}
    </div>
  );
}
