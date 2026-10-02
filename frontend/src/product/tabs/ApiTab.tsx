import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Endpoint, type TraceStep } from "../../lib/product";
import { useRepo } from "../RepoLayout";
import CodeView from "../CodeView";
import { Empty, ErrorBox, Icon, Loading, MethodBadge, PageHeader, SearchInput, groupColor, type LayerGroup } from "../ui";

const STEP_META: Record<TraceStep["kind"], { label: string; group: LayerGroup }> = {
  endpoint: { label: "Request", group: "route" },
  middleware: { label: "Middleware", group: "middleware" },
  handler: { label: "Handler", group: "route" },
  service: { label: "Service", group: "service" },
  data: { label: "Data access", group: "data" },
  entity: { label: "Model", group: "data" },
};

export default function ApiTab() {
  const { analysis } = useRepo();
  const [endpoints, setEndpoints] = useState<Endpoint[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    api.endpoints(analysis.id).then(setEndpoints).catch((e) => setError(String(e.message ?? e)));
  }, [analysis.id]);

  const groups = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const shown = (endpoints ?? []).filter(
      (e) =>
        !q ||
        e.path.toLowerCase().includes(q) ||
        e.method.toLowerCase() === q ||
        (e.handler ?? "").toLowerCase().includes(q) ||
        (e.file ?? "").toLowerCase().includes(q),
    );
    const map = new Map<string, Endpoint[]>();
    for (const e of shown) {
      const key = e.controller ?? e.file ?? "Unknown file";
      map.set(key, [...(map.get(key) ?? []), e]);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [endpoints, filter]);

  if (error) return <ErrorBox>{error}</ErrorBox>;
  if (!endpoints) return <Loading />;
  if (endpoints.length === 0)
    return (
      <Empty icon="api" title="No HTTP endpoints found">
        The parser looks for Express <code className="font-mono">router.get(…)</code> calls and NestJS route
        decorators. GraphQL resolvers aren't counted.
      </Empty>
    );

  return (
    <div>
      <PageHeader
        title="API"
        description={`${endpoints.length} endpoints. Open one to follow the request through the code: middleware, the handler, the services it calls, and the data models it touches.`}
        actions={<SearchInput value={filter} onChange={setFilter} placeholder="Filter by path, method or handler" className="w-72" />}
      />
      <div className="space-y-6">
        {groups.map(([group, eps]) => (
          <section key={group}>
            <h3 className="mb-2 px-1 font-mono text-xs text-muted">{group}</h3>
            <div className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
              {eps.map((e) => {
                const isOpen = open === e.id;
                const handler = e.handler ? `${e.handler}()` : e.trace.find((s) => s.kind === "handler")?.label;
                return (
                  <div key={e.id}>
                    <button
                      onClick={() => setOpen(isOpen ? null : e.id)}
                      aria-expanded={isOpen}
                      className={`flex w-full items-center gap-4 px-4 py-3 text-left transition ${isOpen ? "bg-sunken" : "hover:bg-hover"}`}
                    >
                      <MethodBadge method={e.method} />
                      <span className="flex-1 truncate font-mono text-[13px] text-ink">{e.path}</span>
                      <span className="hidden max-w-[40%] truncate font-mono text-xs text-muted sm:block">{handler}</span>
                      <Icon name="chevron" className={`h-4 w-4 text-muted transition ${isOpen ? "rotate-90" : ""}`} />
                    </button>
                    {isOpen && <EndpointDetail analysisId={analysis.id} endpoint={e} />}
                  </div>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function EndpointDetail({ analysisId, endpoint }: { analysisId: string; endpoint: Endpoint }) {
  const [content, setContent] = useState<string | null>(null);

  useEffect(() => {
    if (!endpoint.file) return;
    api.file(analysisId, endpoint.file).then((f) => setContent(f.content)).catch(() => setContent(null));
  }, [analysisId, endpoint.file]);

  const line = endpoint.line ?? 1;
  const total = content ? content.split("\n").length : 0;
  const range: [number, number] = [Math.max(1, line - 3), Math.min(total, line + 18)];

  return (
    <div className="animate-in space-y-5 border-t border-line bg-sunken px-4 pb-5 pt-4">
      <div>
        <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-muted">Request flow</p>
        <div className="flex flex-wrap items-center gap-2">
          {endpoint.trace.map((step, i) => (
            <div key={i} className="flex items-center gap-2">
              {i > 0 && <Icon name="arrow" className="h-3.5 w-3.5 text-muted" />}
              <div
                className="rounded-lg border border-line bg-surface py-1.5 pl-3 pr-3 shadow-card"
                style={{ boxShadow: `inset 3px 0 0 ${groupColor(STEP_META[step.kind].group)}` }}
                title={step.file ?? undefined}
              >
                <p className="text-[10px] font-medium uppercase tracking-wider text-muted">{STEP_META[step.kind].label}</p>
                <p className="max-w-[260px] truncate font-mono text-xs text-ink">{step.label}</p>
              </div>
            </div>
          ))}
        </div>
        {endpoint.trace.length <= 2 && (
          <p className="mt-3 text-xs text-muted">The handler doesn't call into other files the parser can follow (for example, it's written inline).</p>
        )}
      </div>
      {endpoint.file && content && (
        <div>
          <div className="mb-2 flex items-baseline justify-between">
            <p className="font-mono text-xs text-ink-2">
              {endpoint.file}
              <span className="text-muted">:{endpoint.line}</span>
            </p>
            <Link
              to={`../files?path=${encodeURIComponent(endpoint.file)}&line=${endpoint.line ?? 1}`}
              className="inline-flex items-center gap-1 text-xs font-medium text-accent-text hover:underline"
            >
              Open file <Icon name="arrow" className="h-3 w-3" />
            </Link>
          </div>
          <CodeView path={endpoint.file} content={content} focusLine={endpoint.line} range={range} maxHeight="360px" />
        </div>
      )}
    </div>
  );
}
