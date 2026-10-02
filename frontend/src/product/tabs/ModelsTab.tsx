import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import MermaidDiagram from "../../components/MermaidDiagram";
import { api, type Entity } from "../../lib/product";
import { useRepo } from "../RepoLayout";
import { Card, Empty, ErrorBox, Icon, Loading, PageHeader } from "../ui";

const ORM_LABELS: Record<string, string> = {
  mongoose: "Mongoose",
  typeorm: "TypeORM",
  sequelize: "Sequelize",
  prisma: "Prisma",
};

export default function ModelsTab() {
  const { analysis } = useRepo();
  const [data, setData] = useState<{ mermaid: string | null; entities: Entity[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.models(analysis.id).then(setData).catch((e) => setError(String(e.message ?? e)));
  }, [analysis.id]);

  if (error) return <ErrorBox>{error}</ErrorBox>;
  if (!data) return <Loading />;
  if (data.entities.length === 0)
    return (
      <Empty icon="database" title="No data models found">
        Models are detected for Mongoose, TypeORM, Sequelize and Prisma. This repository uses a
        different data layer, or none.
      </Empty>
    );

  const orms = [...new Set(data.entities.map((e) => ORM_LABELS[e.orm] ?? e.orm))];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Data models"
        description={`${data.entities.length} models found in the ${orms.join(" and ")} definitions, with their fields and how they relate. Read straight from the code.`}
      />
      <Card padded={false} className="p-4">
        <div className="scroll-quiet max-h-[70vh] overflow-auto rounded-xl bg-sunken p-4">
          {data.mermaid && <MermaidDiagram chart={data.mermaid} bare />}
        </div>
      </Card>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data.entities.map((e) => (
          <Card key={`${e.source_path}:${e.name}`} padded={false} className="overflow-hidden">
            <div className="border-b border-line px-5 py-4">
              <div className="flex items-center justify-between gap-2">
                <p className="truncate font-mono text-[15px] font-semibold text-ink">{e.name}</p>
                <span className="rounded-md border border-line px-1.5 py-0.5 text-[11px] text-muted">{ORM_LABELS[e.orm] ?? e.orm}</span>
              </div>
              <Link
                to={`../files?path=${encodeURIComponent(e.source_path)}&line=${e.line}`}
                className="mt-1 inline-flex max-w-full items-center gap-1 truncate text-xs text-accent-text hover:underline"
              >
                {e.source_path}
                <Icon name="arrow" className="h-3 w-3" />
              </Link>
            </div>
            <table className="w-full text-[13px]">
              <tbody>
                {e.fields.map((f) => (
                  <tr key={f.name} className="border-b border-line last:border-0">
                    <td className="px-5 py-1.5 font-mono text-ink">{f.name}</td>
                    <td className="px-5 py-1.5 text-right font-mono text-xs text-muted">{f.type}</td>
                  </tr>
                ))}
                {e.relations.map((r, i) => (
                  <tr key={`r${i}`} className="border-b border-line bg-sunken/60 last:border-0">
                    <td className="px-5 py-1.5 font-mono text-ink">{r.field || "association"}</td>
                    <td className="px-5 py-1.5 text-right font-mono text-xs text-accent-text">
                      → {r.target}
                      {r.kind === "many" ? "[]" : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        ))}
      </div>
    </div>
  );
}
