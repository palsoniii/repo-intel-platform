import { useParams } from "react-router-dom";
import { mockAnalysis } from "../lib/mockData";

export default function SummaryPage() {
  const { repoName } = useParams();
  const { summary, sourceUrl, framework } = mockAnalysis;

  return (
    <div>
      <h2 className="text-2xl font-semibold">{repoName}</h2>
      <p className="mb-6 text-sm text-slate-500 dark:text-slate-400">
        <a href={sourceUrl} className="underline">
          {sourceUrl}
        </a>{" "}
        &middot; detected framework: {framework}
      </p>

      <section className="mb-6 rounded-lg border border-slate-200 p-4 dark:border-slate-800">
        <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Overview
        </h3>
        <p>{summary.overview}</p>
      </section>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <ListCard title="Tech stack" items={summary.techStack} />
        <ListCard title="Services" items={summary.services} />
        <ListCard title="Dependencies" items={summary.dependencies} />
      </div>
    </div>
  );
}

function ListCard({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
      <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h3>
      <ul className="space-y-1 text-sm">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
