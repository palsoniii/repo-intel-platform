import { useEffect, useMemo, useState } from "react";
import { api, type Dependency } from "../../lib/product";
import { useRepo } from "../RepoLayout";
import CodeSwitcher from "../CodeSwitcher";
import { Empty, ErrorBox, Loading, PageHeader } from "../ui";

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
    return [...map.entries()].sort(([a, x], [b, y]) => (a === "Other" ? 1 : b === "Other" ? -1 : y.length - x.length));
  }, [deps, showDev]);

  if (error) return <ErrorBox>{error}</ErrorBox>;
  if (!deps) return <Loading />;

  const runtime = deps.filter((d) => d.dep_type !== "dev").length;
  const dev = deps.length - runtime;

  return (
    <div>
      <PageHeader
        title="Packages"
        description={`${runtime} packages the app runs on and ${dev} used only in development, from package.json, grouped by what they're for.`}
        actions={
          <>
            <label className="mr-2 flex cursor-pointer items-center gap-2 text-sm text-ink-2">
              <input type="checkbox" className="accent-[var(--accent)]" checked={showDev} onChange={(e) => setShowDev(e.target.checked)} />
              Include development
            </label>
            <CodeSwitcher />
          </>
        }
      />
      {deps.length === 0 ? (
        <Empty icon="package" title="No package.json dependencies found" />
      ) : (
        <div className="columns-1 gap-4 md:columns-2 xl:columns-3">
          {groups.map(([category, items]) => (
            <section key={category} className="mb-4 break-inside-avoid rounded-2xl border border-line bg-surface p-5 shadow-card">
              <h3 className="mb-3 flex items-baseline justify-between text-sm font-semibold text-ink">
                {category} <span className="text-xs font-normal text-muted">{items.length}</span>
              </h3>
              <ul className="space-y-2.5">
                {items.map((d) => (
                  <li key={d.name}>
                    <div className="flex items-baseline gap-2">
                      <a
                        href={`https://www.npmjs.com/package/${d.name}`}
                        target="_blank"
                        rel="noreferrer"
                        className="font-mono text-[13px] font-medium text-ink hover:underline"
                      >
                        {d.name}
                      </a>
                      {d.dep_type === "dev" && <span className="rounded border border-line px-1 text-[10px] text-muted">dev</span>}
                      {d.version && <span className="ml-auto font-mono text-[11px] text-muted">{d.version}</span>}
                    </div>
                    {d.description && <p className="mt-0.5 text-xs leading-relaxed text-ink-2">{d.description}</p>}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
