import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import MermaidDiagram from "../../components/MermaidDiagram";
import { api, type Entity } from "../../lib/product";
import { useRepo } from "../RepoLayout";
import { Card, Empty, ErrorBox, Loading, Pill, SectionTitle } from "../ui";

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
      <Empty title="No data models found">
        Models are detected for Mongoose, TypeORM, Sequelize and Prisma. This repository either uses a
        different data layer, or none.
      </Empty>
    );

  const orms = [...new Set(data.entities.map((e) => ORM_LABELS[e.orm] ?? e.orm))];

  return (
    <div className="space-y-6">
      <Card>
        <SectionTitle hint={orms.join(" · ")}>Entity relationships</SectionTitle>
        <div className="max-h-[70vh] overflow-auto">
          {data.mermaid && <MermaidDiagram chart={data.mermaid} />}
        </div>
      </Card>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data.entities.map((e) => (
          <Card key={`${e.source_path}:${e.name}`} className="!p-4">
            <div className="flex items-start justify-between gap-2">
              <p className="font-mono font-semibold">{e.name}</p>
              <Pill>{ORM_LABELS[e.orm] ?? e.orm}</Pill>
            </div>
            <Link
              to={`../files?path=${encodeURIComponent(e.source_path)}&line=${e.line}`}
              className="mt-0.5 block truncate text-xs text-indigo-700 hover:underline dark:text-indigo-300"
            >
              {e.source_path}:{e.line}
            </Link>
            <table className="mt-3 w-full text-xs">
              <tbody>
                {e.fields.map((f) => (
                  <tr key={f.name} className="border-t border-slate-100 dark:border-slate-800">
                    <td className="py-1 pr-2 font-mono">{f.name}</td>
                    <td className="py-1 text-right font-mono text-slate-500">{f.type}</td>
                  </tr>
                ))}
                {e.relations.map((r, i) => (
                  <tr key={`r${i}`} className="border-t border-slate-100 dark:border-slate-800">
                    <td className="py-1 pr-2 font-mono">{r.field || "(association)"}</td>
                    <td className="py-1 text-right font-mono text-rose-600 dark:text-rose-400">
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
