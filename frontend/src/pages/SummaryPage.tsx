import { useLocation, useParams } from "react-router-dom";
import type { SummarizeResponse } from "../lib/api";

export default function SummaryPage() {
  const { repoName } = useParams();
  const location = useLocation();
  const real = (location.state as { real?: SummarizeResponse } | null)?.real;

  if (real) {
    return <RealSummary repoName={repoName} real={real} />;
  }

  return <EmptySummary repoName={repoName} />;
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
      endpoints={real.summary.endpoints ?? []}
      components={real.summary.components ?? []}
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
  endpoints,
  components,
}: {
  repoName: string | undefined;
  sourceUrl: string;
  framework: string;
  overview: string;
  techStack: string[];
  services: string[];
  dependencies: string[];
  endpoints: string[];
  components: string[];
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

      {/* Rendered only when present: a model that predates the endpoints/components
          fields still returns a valid summary, and an empty card would read as
          "this repo has no endpoints" rather than "this run did not report any". */}
      {(endpoints.length > 0 || components.length > 0) && (
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          {endpoints.length > 0 && <ListCard title="API endpoints" items={endpoints} />}
          {components.length > 0 && <ListCard title="Components" items={components} />}
        </div>
      )}
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
        {/* Keyed by position, not by value: local models repeat entries (the same path
            under two methods, a dependency listed twice), and a value key silently
            drops the duplicate -- so the card under-reports what the model returned. */}
        {items.map((item, index) => (
          <li key={`${index}-${item}`}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

// Shown until a real summary exists. This page previously fell back to a hardcoded
// summary for a repo the user never submitted. It was prefixed "[Placeholder]", but a
// dashboard that renders invented content at all trains the reader to skim the label.
function EmptySummary({ repoName }: { repoName?: string }) {
  return (
    <div>
      <h2 className="mb-2 text-2xl font-semibold">{repoName ?? "Repository"} -- summary</h2>
      <div className="rounded-lg border border-dashed border-slate-300 p-8 text-center dark:border-slate-700">
        <h3 className="mb-2 text-base font-medium text-slate-700 dark:text-slate-300">
          No summary yet
        </h3>
        <p className="mx-auto max-w-lg text-sm text-slate-500 dark:text-slate-400">
          Run an analysis from the Analyze tab. Summaries are generated by a local model
          from the parsed repository, so there is nothing meaningful to show without a
          real run.
        </p>
      </div>
    </div>
  );
}
