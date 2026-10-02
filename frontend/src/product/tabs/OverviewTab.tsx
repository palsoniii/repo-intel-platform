import { Link } from "react-router-dom";
import { api } from "../../lib/product";
import { useRepo } from "../RepoLayout";
import { Card, LAYER_COLORS, Pill, SectionTitle, Spinner, Stat } from "../ui";

export default function OverviewTab() {
  const { analysis, refresh } = useRepo();
  const s = analysis.stats;
  const summary = analysis.summary?.summary ?? null;
  const layers = (analysis.layers ?? []).filter((l) => l.layer !== "test");
  const totalFiles = layers.reduce((n, l) => n + l.files, 0) || 1;
  const structuralSeconds = ["clone", "parse", "index"].reduce((n, k) => n + (analysis.timings[k] ?? 0), 0);

  async function regenerate() {
    await api.regenerateSummary(analysis.id);
    await refresh();
  }

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-6 lg:col-span-2">
        <Card>
          <SectionTitle
            hint={
              analysis.summary && analysis.summary_status === "done"
                ? `${analysis.summary.model} · ${(analysis.summary.latency_ms / 1000).toFixed(1)}s · ${analysis.summary.input_tokens} tokens in`
                : undefined
            }
          >
            AI summary
          </SectionTitle>
          {analysis.summary_status === "done" && summary ? (
            <>
              <p className="leading-relaxed text-slate-700 dark:text-slate-300">{summary.overview}</p>
              {summary.tech_stack && summary.tech_stack.length > 0 && (
                <div className="mt-4 flex flex-wrap gap-1.5">
                  {summary.tech_stack.map((t) => (
                    <Pill key={t} tone="indigo">
                      {t}
                    </Pill>
                  ))}
                </div>
              )}
              {summary.services && summary.services.length > 0 && (
                <div className="mt-4">
                  <p className="mb-1 text-xs font-medium text-slate-500 dark:text-slate-400">Services</p>
                  <ul className="list-inside list-disc text-sm text-slate-700 dark:text-slate-300">
                    {summary.services.map((x) => (
                      <li key={x}>{x}</li>
                    ))}
                  </ul>
                </div>
              )}
              <p className="mt-4 text-xs text-slate-400">
                Written from the repository's knowledge graph by a local model. Structural facts on
                every other tab come straight from the parser, not the model.
              </p>
            </>
          ) : analysis.summary_status === "failed" ? (
            <div className="text-sm">
              <p className="text-rose-700 dark:text-rose-300">{analysis.summary_error ?? "The summary couldn't be generated."}</p>
              <button onClick={regenerate} className="mt-3 rounded-md bg-indigo-600 px-3 py-1.5 text-white hover:bg-indigo-500">
                Try again
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-3 text-sm text-slate-500 dark:text-slate-400">
              <Spinner />
              <div>
                <p>
                  {analysis.summary_status === "running"
                    ? `${analysis.summary_model ?? "The local model"} is reading the knowledge graph…`
                    : "Queued for the local model…"}
                </p>
                <p className="text-xs">Usually 20–60 seconds. Every other tab is ready now.</p>
              </div>
            </div>
          )}
        </Card>

        {s && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Source files" value={s.files} />
            <Stat label="Lines of code" value={s.lines_of_code.toLocaleString()} />
            <Stat label="API endpoints" value={s.endpoints} />
            <Stat label="Data models" value={s.entities} />
            <Stat label="Classes" value={s.classes} />
            <Stat label="Functions & methods" value={s.functions} />
            <Stat label="Internal imports" value={s.internal_imports} />
            <Stat label="npm packages" value={s.external_dependencies} />
          </div>
        )}

        {layers.length > 0 && (
          <Card>
            <SectionTitle hint={`${totalFiles} files, tests excluded`}>How the code is organised</SectionTitle>
            <div className="flex h-3 overflow-hidden rounded-full">
              {layers.map((l) => (
                <div
                  key={l.layer}
                  style={{ width: `${(l.files / totalFiles) * 100}%`, background: LAYER_COLORS[l.layer] }}
                  title={`${l.label}: ${l.files}`}
                />
              ))}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-3">
              {layers.map((l) => (
                <div key={l.layer} className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ background: LAYER_COLORS[l.layer] }} />
                  <span className="text-slate-600 dark:text-slate-400">{l.label}</span>
                  <span className="ml-auto tabular-nums text-slate-400">{l.files}</span>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>

      <div className="space-y-6">
        {analysis.hotspots && analysis.hotspots.length > 0 && (
          <Card>
            <SectionTitle hint="most imported">Start reading here</SectionTitle>
            <ol className="space-y-2">
              {analysis.hotspots.map((h) => (
                <li key={h.id} className="flex items-baseline justify-between gap-3 text-sm">
                  <Link
                    to={`../files?path=${encodeURIComponent(h.path)}`}
                    className="truncate font-mono text-xs text-indigo-700 hover:underline dark:text-indigo-300"
                    title={h.path}
                  >
                    {h.path}
                  </Link>
                  <span className="shrink-0 text-xs tabular-nums text-slate-400">{h.imported_by}×</span>
                </li>
              ))}
            </ol>
          </Card>
        )}

        {summary?.components && summary.components.length > 0 && (
          <Card>
            <SectionTitle>Key components</SectionTitle>
            <div className="flex flex-wrap gap-1.5">
              {summary.components.slice(0, 18).map((c) => (
                <span key={c} className="rounded bg-slate-100 px-2 py-0.5 font-mono text-xs dark:bg-slate-800">
                  {c}
                </span>
              ))}
            </div>
          </Card>
        )}

        <Card>
          <SectionTitle>Analysis</SectionTitle>
          <dl className="space-y-1.5 text-sm">
            <Row label="Structural analysis" value={`${structuralSeconds.toFixed(1)} s`} />
            {analysis.timings.graph !== undefined && <Row label="Knowledge graph write" value={`${analysis.timings.graph.toFixed(1)} s`} />}
            {analysis.timings.summary !== undefined && <Row label="AI summary" value={`${analysis.timings.summary.toFixed(1)} s`} />}
            <Row
              label="Neo4j"
              value={analysis.graph_status === "stored" ? "Stored" : analysis.graph_status === "unavailable" ? "Not running" : "Writing…"}
            />
            {analysis.metadata?.framework_version && <Row label="Framework version" value={analysis.metadata.framework_version} />}
          </dl>
          {analysis.metadata && analysis.metadata.parse_warnings.length > 0 && (
            <details className="mt-3 text-xs text-slate-500">
              <summary className="cursor-pointer">{analysis.metadata.parse_warnings.length} parser notes</summary>
              <ul className="mt-2 list-inside list-disc space-y-1">
                {analysis.metadata.parse_warnings.slice(0, 20).map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </details>
          )}
        </Card>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="tabular-nums">{value}</dd>
    </div>
  );
}
