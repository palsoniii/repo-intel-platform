import { useEffect, useState } from "react";
import MermaidDiagram from "../../components/MermaidDiagram";
import LayeredArchitecture from "../LayeredArchitecture";
import { api, type Architecture } from "../../lib/product";
import { useRepo } from "../RepoLayout";
import { Card, ErrorBox, Loading, SectionTitle } from "../ui";

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

  return (
    <div className="space-y-6">
      <Card>
        <SectionTitle
          hint={
            <label className="flex cursor-pointer items-center gap-1.5">
              <input type="checkbox" checked={includeTests} onChange={(e) => setIncludeTests(e.target.checked)} />
              include tests
            </label>
          }
        >
          Layered architecture
        </SectionTitle>
        <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
          Files grouped by role, with arrows for imports. Hover a box to see what it depends on and what
          depends on it; click to open the file.{" "}
          {data.layered.grouped
            ? `This repository is large, so files are collapsed by directory (${data.layered.node_count} groups); thicker arrows stand for more imports.`
            : `${data.layered.node_count} files, ${data.layered.edge_count} import links.`}{" "}
          Generated deterministically from the parse: no LLM involved.
        </p>
        <LayeredArchitecture graph={data.layered.graph} />
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-700 dark:text-slate-400">
            Static diagram (Mermaid, for export)
          </summary>
          <div className="mt-2 max-h-[60vh] overflow-auto">
            <MermaidDiagram chart={data.layered.mermaid} />
          </div>
        </details>
      </Card>

      {data.nest_modules && (
        <Card>
          <SectionTitle hint={`${data.nest_modules.modules} modules`}>NestJS module map</SectionTitle>
          <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
            How the application's <code>@Module</code> files import each other: the architecture a NestJS
            app declares for itself.
          </p>
          <div className="max-h-[70vh] overflow-auto">
            <MermaidDiagram chart={data.nest_modules.mermaid} />
          </div>
        </Card>
      )}
    </div>
  );
}
