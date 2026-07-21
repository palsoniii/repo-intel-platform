import { useLocation, useParams } from "react-router-dom";
import { mockAnalysis } from "../lib/mockData";
import type { SummarizeResponse } from "../lib/api";

export default function SummaryPage() {
  const { repoName } = useParams();
  const location = useLocation();
  const real = (location.state as { real?: SummarizeResponse } | null)?.real;

  if (real) {
    return <RealSummary repoName={repoName} real={real} />;
  }

  const { summary, sourceUrl, framework } = mockAnalysis;
  return (
    <SummaryLayout
      repoName={repoName}
      sourceUrl={sourceUrl}
      framework={framework}
      overview={summary.overview}
      techStack={summary.techStack}
      services={summary.services}
      dependencies={summary.dependencies}
    />
  );
}

function RealSummary({
  repoName,
  real,
}: {
  repoName: string | undefined;
  real: SummarizeResponse;
}) {
  if (real.status !== "success" || !real.summary) {
    return (
      <div>
        <h2 className="text-2xl font-semibold">{repoName}</h2>
        <p className="mb-6 text-sm text-slate-500 dark:text-slate-400">
          <a href={real.sourceUrl} className="underline">
            {real.sourceUrl}
          </a>{" "}
          &middot; detected framework: {real.framework ?? "unknown"}
        </p>
        <section className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm dark:border-amber-900 dark:bg-amber-950">
          <p className="mb-2 font-medium">
            {real.status === "success"
              ? "The model's response didn't parse as the expected structured JSON."
              : `The model run did not succeed (status: ${real.status}).`}
          </p>
          {real.error && <p className="mb-2 text-red-700 dark:text-red-300">{real.error}</p>}
          {real.summaryRawText && (
            <>
              <p className="mb-1 text-slate-600 dark:text-slate-400">Raw model output:</p>
              <pre className="overflow-x-auto rounded bg-white p-2 dark:bg-slate-900">
                {real.summaryRawText}
              </pre>
            </>
          )}
        </section>
      </div>
    );
  }

  return (
    <SummaryLayout
      repoName={repoName}
      sourceUrl={real.sourceUrl}
      framework={real.framework ?? "unknown"}
      overview={real.summary.overview}
      techStack={real.summary.tech_stack}
      services={real.summary.services}
      dependencies={real.summary.dependencies}
    />
  );
}

function SummaryLayout({
  repoName,
  sourceUrl,
  framework,
  overview,
  techStack,
  services,
  dependencies,
}: {
  repoName: string | undefined;
  sourceUrl: string;
  framework: string;
  overview: string;
  techStack: string[];
  services: string[];
  dependencies: string[];
}) {
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
        <p>{overview}</p>
      </section>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <ListCard title="Tech stack" items={techStack} />
        <ListCard title="Services" items={services} />
        <ListCard title="Dependencies" items={dependencies} />
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
