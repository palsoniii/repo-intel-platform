import { Link } from "react-router-dom";
import { api } from "../../lib/product";
import { useRepo } from "../RepoLayout";
import {
  Button,
  Card,
  CardTitle,
  Icon,
  LAYER_GROUPS,
  LayerDot,
  Spinner,
  Stat,
  groupColor,
  layerGroup,
  type IconName,
  type LayerGroup,
} from "../ui";

export default function OverviewTab() {
  const { analysis, refresh } = useRepo();
  const s = analysis.stats;
  const summary = analysis.summary?.summary ?? null;

  const groupCounts = new Map<LayerGroup, number>();
  for (const l of analysis.layers ?? []) {
    const g = layerGroup(l.layer);
    if (g === "test") continue;
    groupCounts.set(g, (groupCounts.get(g) ?? 0) + l.files);
  }
  const groups = LAYER_GROUPS.filter((g) => groupCounts.get(g.id));
  const total = groups.reduce((n, g) => n + (groupCounts.get(g.id) ?? 0), 0) || 1;
  const structuralSeconds = ["clone", "parse", "index"].reduce((n, k) => n + (analysis.timings[k] ?? 0), 0);

  async function regenerate() {
    await api.regenerateSummary(analysis.id);
    await refresh();
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
      <div className="space-y-6">
        <Card className="relative overflow-hidden">
          <div className="mb-4 flex items-center justify-between gap-4">
            <div className="flex items-center gap-2 text-sm font-medium text-ink-2">
              <Icon name="sparkles" className="h-4 w-4 text-accent" />
              What this repository does
            </div>
            {analysis.summary_status === "done" && analysis.summary && (
              <span className="text-xs text-muted">
                {analysis.summary.model} · {(analysis.summary.latency_ms / 1000).toFixed(0)}s
              </span>
            )}
          </div>

          {analysis.summary_status === "done" && summary ? (
            <>
              <p className="text-[17px] leading-[1.65] tracking-[-0.005em] text-ink">{summary.overview}</p>
              {summary.tech_stack && summary.tech_stack.length > 0 && (
                <div className="mt-5 flex flex-wrap gap-1.5">
                  {summary.tech_stack.map((t) => (
                    <span key={t} className="rounded-md border border-line bg-sunken px-2 py-0.5 text-xs font-medium text-ink-2">
                      {t}
                    </span>
                  ))}
                </div>
              )}
              <p className="mt-5 border-t border-line pt-4 text-xs leading-relaxed text-muted">
                Written by a local model from the repository's knowledge graph. Everything else on
                this dashboard comes straight from the code, with no model involved.
              </p>
            </>
          ) : analysis.summary_status === "failed" ? (
            <div>
              <p className="text-sm text-ink-2">{analysis.summary_error ?? "The summary couldn't be generated."}</p>
              <Button variant="primary" className="mt-4" onClick={regenerate}>
                <Icon name="refresh" className="h-3.5 w-3.5" /> Try again
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm text-ink-2">
                <Spinner />
                {analysis.summary_status === "running" ? "The local model is reading the knowledge graph…" : "Waiting for the local model…"}
              </div>
              <div className="skeleton h-4 w-full" />
              <div className="skeleton h-4 w-11/12" />
              <div className="skeleton h-4 w-4/5" />
              <p className="pt-1 text-xs text-muted">Usually 20–60 seconds. Every other tab is ready now.</p>
            </div>
          )}
        </Card>

        {s && (
          <div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label="Source files" value={s.files} />
              <Stat label="Lines of code" value={s.lines_of_code.toLocaleString()} />
              <Stat label="API endpoints" value={s.endpoints} />
              <Stat label="Data models" value={s.entities} />
            </div>
            <p className="mt-2.5 px-1 text-xs text-muted">
              {s.classes} classes · {s.functions} functions and methods · {s.internal_imports} internal imports ·{" "}
              {s.external_dependencies} npm packages
            </p>
          </div>
        )}

        {groups.length > 0 && (
          <Card>
            <CardTitle aside={`${total} files, tests excluded`}>How the code is organised</CardTitle>
            <div className="flex h-2.5 gap-[2px] overflow-hidden rounded-full">
              {groups.map((g) => (
                <div
                  key={g.id}
                  className="first:rounded-l-full last:rounded-r-full"
                  style={{ width: `${((groupCounts.get(g.id) ?? 0) / total) * 100}%`, background: groupColor(g.id) }}
                  title={`${g.label}: ${groupCounts.get(g.id)}`}
                />
              ))}
            </div>
            <div className="mt-5 grid gap-x-8 gap-y-3 sm:grid-cols-2">
              {groups.map((g) => (
                <div key={g.id} className="flex items-start gap-3">
                  <LayerDot group={g.id} className="mt-1.5 h-2.5 w-2.5" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-sm font-medium text-ink">{g.label}</span>
                      <span className="text-sm tabular-nums text-ink-2">{groupCounts.get(g.id)}</span>
                    </div>
                    <p className="text-xs text-muted">{g.hint}</p>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>

      <aside className="space-y-6">
        <Card>
          <CardTitle>Explore</CardTitle>
          <div className="-mx-2 space-y-0.5">
            <QuickLink to="../ask" icon="ask" title="Ask a question" body="Get answers grounded in the source" />
            <QuickLink to="../architecture" icon="layers" title="See the architecture" body="Every file, by role" />
            <QuickLink to="../api" icon="api" title="Trace a request" body={`${s?.endpoints ?? 0} endpoints, end to end`} />
            {(s?.entities ?? 0) > 0 && <QuickLink to="../models" icon="database" title="Data models" body={`${s?.entities} models and their relations`} />}
          </div>
        </Card>

        {analysis.hotspots && analysis.hotspots.length > 0 && (
          <Card>
            <CardTitle aside="most imported">Start reading here</CardTitle>
            <ol className="space-y-2.5">
              {analysis.hotspots.slice(0, 6).map((h) => (
                <li key={h.id}>
                  <Link
                    to={`../files?path=${encodeURIComponent(h.path)}`}
                    className="group flex items-center justify-between gap-3"
                    title={h.path}
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-mono text-[13px] text-ink group-hover:underline">
                        {h.path.split("/").pop()}
                      </span>
                      <span className="block truncate text-[11px] text-muted">{h.path.split("/").slice(0, -1).join("/") || "/"}</span>
                    </span>
                    <span className="shrink-0 text-xs tabular-nums text-muted">used by {h.imported_by}</span>
                  </Link>
                </li>
              ))}
            </ol>
          </Card>
        )}

        <details className="group rounded-2xl border border-line bg-surface px-5 py-4 shadow-card">
          <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium text-ink-2">
            Analysis details
            <Icon name="chevron" className="h-4 w-4 transition group-open:rotate-90" />
          </summary>
          <dl className="mt-4 space-y-2 text-sm">
            <Row label="Structure mapped in" value={`${structuralSeconds.toFixed(1)} s`} />
            {analysis.timings.graph !== undefined && <Row label="Knowledge graph saved in" value={`${analysis.timings.graph.toFixed(1)} s`} />}
            {analysis.timings.summary !== undefined && <Row label="Summary written in" value={`${analysis.timings.summary.toFixed(0)} s`} />}
            {analysis.metadata?.framework_version && <Row label="Framework version" value={analysis.metadata.framework_version} />}
            {analysis.summary && <Row label="Model input" value={`${analysis.summary.input_tokens.toLocaleString()} tokens`} />}
          </dl>
          {analysis.summary_status === "done" && (
            <Button variant="ghost" size="sm" className="-ml-3 mt-3" onClick={regenerate}>
              <Icon name="refresh" className="h-3.5 w-3.5" /> Regenerate summary
            </Button>
          )}
        </details>
      </aside>
    </div>
  );
}

function QuickLink({ to, icon, title, body }: { to: string; icon: IconName; title: string; body: string }) {
  return (
    <Link to={to} className="group flex items-center gap-3 rounded-xl px-2 py-2 transition hover:bg-hover">
      <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-line bg-sunken text-ink">
        <Icon name={icon} className="h-4 w-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-ink">{title}</span>
        <span className="block truncate text-xs text-muted">{body}</span>
      </span>
      <Icon name="arrow" className="h-4 w-4 text-muted transition group-hover:translate-x-0.5 group-hover:text-ink" />
    </Link>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted">{label}</dt>
      <dd className="tabular-nums text-ink">{value}</dd>
    </div>
  );
}
