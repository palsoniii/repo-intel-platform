import { useEffect, useMemo, useState } from "react";
import { api, type Dependency } from "../../lib/product";
import { useRepo } from "../RepoLayout";
import { Empty, ErrorBox, Loading } from "../ui";

export default function DependenciesTab() {
  const { analysis } = useRepo();
  const [deps, setDeps] = useState<Dependency[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showDev, setShowDev] = useState(false);

  useEffect(() => {
    api.dependencies(analysis.id).then(setDeps).catch((e) => setError(String(e.message ?? e)));
  }, [analysis.id]);

  const groups = useMemo(() => {
    const map = new Map<string, Dependency[]>();
    for (const d of deps ?? []) {
      if (!showDev && d.dep_type === "dev") continue;
      map.set(d.category, [...(map.get(d.category) ?? []), d]);
    }
    return [...map.entries()].sort(([a], [b]) => (a === "Other" ? 1 : b === "Other" ? -1 : a.localeCompare(b)));
  }, [deps, showDev]);

  if (error) return <ErrorBox>{error}</ErrorBox>;
  if (!deps) return <Loading />;
  if (deps.length === 0) return <Empty title="No package.json dependencies found" />;

  const runtime = deps.filter((d) => d.dep_type !== "dev").length;
  const dev = deps.length - runtime;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {runtime} runtime packages, {dev} development packages, from <code>package.json</code>.
        </p>
        <label className="flex cursor-pointer items-center gap-1.5 text-sm">
          <input type="checkbox" checked={showDev} onChange={(e) => setShowDev(e.target.checked)} />
          Show development packages
        </label>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {groups.map(([category, items]) => (
          <section key={category} className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
            <h3 className="mb-2 text-sm font-semibold">
              {category} <span className="font-normal text-slate-400">{items.length}</span>
            </h3>
            <ul className="space-y-1.5">
              {items.map((d) => (
                <li key={d.name} className="text-sm">
                  <div className="flex items-baseline gap-2">
                    <a
                      href={`https://www.npmjs.com/package/${d.name}`}
                      target="_blank"
                      rel="noreferrer"
                      className="font-mono text-xs font-medium hover:text-indigo-600"
                    >
                      {d.name}
                    </a>
                    {d.version && <span className="font-mono text-[11px] text-slate-400">{d.version}</span>}
                    {d.dep_type === "dev" && (
                      <span className="rounded bg-slate-100 px-1 text-[10px] text-slate-500 dark:bg-slate-800">dev</span>
                    )}
                  </div>
                  {d.description && <p className="text-xs text-slate-500 dark:text-slate-400">{d.description}</p>}
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
