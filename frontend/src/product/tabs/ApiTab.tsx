import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Endpoint, type TraceStep } from "../../lib/product";
import { useRepo } from "../RepoLayout";
import CodeView from "../CodeView";
import { Empty, ErrorBox, Loading, MethodBadge } from "../ui";

const STEP_STYLES: Record<TraceStep["kind"], { label: string; cls: string }> = {
  endpoint: { label: "Request", cls: "border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/50" },
  middleware: { label: "Middleware", cls: "border-orange-300 bg-orange-50 dark:border-orange-900 dark:bg-orange-950/40" },
  handler: { label: "Handler", cls: "border-sky-300 bg-sky-50 dark:border-sky-800 dark:bg-sky-950/50" },
  service: { label: "Service", cls: "border-emerald-300 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/50" },
  data: { label: "Data access", cls: "border-rose-300 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40" },
  entity: { label: "Model", cls: "border-rose-400 bg-rose-100 dark:border-rose-800 dark:bg-rose-950/60" },
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
      <Empty title="No HTTP endpoints found">
        The parser looks for Express <code>app/router.get(...)</code> calls and NestJS route decorators.
        GraphQL resolvers aren't counted.
      </Empty>
    );

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {endpoints.length} endpoints. Click one to trace the request through the code.
        </p>
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter by path, method, handler…"
          className="w-72 rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
        />
      </div>
      <div className="space-y-5">
        {groups.map(([group, eps]) => (
          <section key={group}>
            <h3 className="mb-2 font-mono text-xs font-semibold text-slate-500 dark:text-slate-400">{group}</h3>
            <div className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
              {eps.map((e) => (
                <div key={e.id}>
                  <button
                    onClick={() => setOpen(open === e.id ? null : e.id)}
                    className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-slate-50 dark:hover:bg-slate-900"
                  >
                    <MethodBadge method={e.method} />
                    <span className="flex-1 truncate font-mono text-sm">{e.path}</span>
                    <span className="hidden truncate font-mono text-xs text-slate-500 sm:block">
                      {e.handler ? `${e.handler}()` : e.trace.find((s) => s.kind === "handler")?.label}
                    </span>
                    <span className="text-slate-400">{open === e.id ? "▾" : "▸"}</span>
                  </button>
                  {open === e.id && <EndpointDetail analysisId={analysis.id} endpoint={e} />}
                </div>
              ))}
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
    <div className="space-y-4 bg-slate-50/60 px-4 py-4 dark:bg-slate-900/40">
      <div>
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Request flow</p>
        <div className="flex flex-wrap items-center gap-1.5">
          {endpoint.trace.map((step, i) => (
            <div key={i} className="flex items-center gap-1.5">
              {i > 0 && <span className="text-slate-400">→</span>}
              <div className={`rounded-lg border px-2.5 py-1 ${STEP_STYLES[step.kind].cls}`} title={step.file ?? undefined}>
                <p className="text-[10px] uppercase tracking-wide text-slate-500">{STEP_STYLES[step.kind].label}</p>
                <p className="max-w-[260px] truncate font-mono text-xs">{step.label}</p>
              </div>
            </div>
          ))}
        </div>
        {endpoint.trace.length <= 2 && (
          <p className="mt-2 text-xs text-slate-500">
            The handler doesn't call into other files the parser can follow (for example, it's inline).
          </p>
        )}
      </div>
      {endpoint.file && content && (
        <div>
          <div className="mb-1 flex items-baseline justify-between">
            <p className="font-mono text-xs text-slate-500">
              {endpoint.file}:{endpoint.line}
            </p>
            <Link
              to={`../files?path=${encodeURIComponent(endpoint.file)}&line=${endpoint.line ?? 1}`}
              className="text-xs text-indigo-700 hover:underline dark:text-indigo-300"
            >
              Open file →
            </Link>
          </div>
          <CodeView path={endpoint.file} content={content} focusLine={endpoint.line} range={range} maxHeight="360px" />
        </div>
      )}
    </div>
  );
}
