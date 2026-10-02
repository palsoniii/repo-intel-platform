import { useEffect, useState } from "react";
import MermaidDiagram from "../../components/MermaidDiagram";
import LayeredArchitecture from "../LayeredArchitecture";
import { api, type Architecture } from "../../lib/product";
import { useRepo } from "../RepoLayout";
import { Card, CardTitle, ErrorBox, LAYER_GROUPS, LayerDot, Loading, PageHeader, layerGroup } from "../ui";

export default function ArchitectureTab() {
  const { analysis } = useRepo();
  const [data, setData] = useState<Architecture | null>(null);
  const [includeTests, setIncludeTests] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    api.architecture(analysis.id, includeTests).then(setData).catch((e) => setError(String(e.message ?? e)));
  }, [analysis.id, includeTests]);

  if (error) return <ErrorBox>{error}</ErrorBox>;
  if (!data) return <Loading label="Laying out the architecture…" />;

  const present = new Set(data.layered.graph.nodes.map((n) => layerGroup(n.layer)));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Architecture"
        description={
          <>
            Every file, grouped by the role it plays, top to bottom in the order a request travels.
            Arrows are imports. Hover a file to see what it depends on; click to open it.
            {data.layered.grouped && " This repository is large, so files are grouped by folder."}
          </>
        }
        actions={
          <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-2">
            <input type="checkbox" className="accent-[var(--accent)]" checked={includeTests} onChange={(e) => setIncludeTests(e.target.checked)} />
            Show tests
          </label>
        }
      />

      <Card padded={false} className="p-3">
        <LayeredArchitecture graph={data.layered.graph} />
        <div className="flex flex-wrap items-center justify-between gap-3 px-3 pb-1 pt-4">
          <div className="flex flex-wrap gap-x-5 gap-y-1.5">
            {LAYER_GROUPS.filter((g) => present.has(g.id)).map((g) => (
              <span key={g.id} className="flex items-center gap-1.5 text-xs text-ink-2">
                <LayerDot group={g.id} className="h-2 w-2" /> {g.label}
              </span>
            ))}
          </div>
          <span className="text-xs text-muted">
            {data.layered.node_count} {data.layered.grouped ? "folders" : "files"} · {data.layered.edge_count} import links · no model involved
          </span>
        </div>
      </Card>

      {data.nest_modules && (
        <Card>
          <CardTitle aside={`${data.nest_modules.modules} modules`}>NestJS module map</CardTitle>
          <p className="-mt-2 mb-5 text-sm text-ink-2">
            How the app's <code className="font-mono text-[0.9em]">@Module</code> files import each other: the
            structure a NestJS application declares for itself.
          </p>
          <div className="scroll-quiet max-h-[70vh] overflow-auto">
            <MermaidDiagram chart={data.nest_modules.mermaid} />
          </div>
        </Card>
      )}

      <details className="rounded-2xl border border-line bg-surface px-5 py-4 shadow-card">
        <summary className="cursor-pointer text-sm font-medium text-ink-2">Export as a Mermaid diagram</summary>
        <div className="scroll-quiet mt-4 max-h-[60vh] overflow-auto">
          <MermaidDiagram chart={data.layered.mermaid} />
        </div>
      </details>
    </div>
  );
}
