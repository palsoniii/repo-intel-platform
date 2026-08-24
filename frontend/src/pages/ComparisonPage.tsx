import { useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { mockAnalysis } from "../lib/mockData";
import { CONTEXT_VARIANTS, type ContextVariant } from "../lib/types";
import { compareModels, ApiError, type CompareResponse } from "../lib/api";

// Normalized shape covering both the real API runs (scores are number | null, with a
// status) and the mock runs (number, no status/coverage), so the aggregate logic
// below works whether or not a backend is attached.
interface NormalizedRun {
  model: string;
  contextVariant: ContextVariant;
  latencyMs: number;
  inputTokens: number;
  outputTokens: number;
  hallucinationScore: number | null;
  coverageScore: number | null;
  status?: string;
  // Text-overlap against the repo's reference summary -- null on mock data and on
  // real runs where no reference_summaries/<repo>.json exists yet.
  bleu4: number | null;
  rougeL: number | null;
  meteor: number | null;
  failureTags: string[];
}

export default function ComparisonPage() {
  const { repoName } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const real = (location.state as { real?: CompareResponse } | null)?.real;

  const [url, setUrl] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const result = await compareModels(url);
      navigate(`/repo/${encodeURIComponent(result.repoName)}/comparison`, {
        state: { real: result },
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsSubmitting(false);
    }
  }

  const displayName = real?.repoName ?? repoName;
  const rawRuns = real?.runs ?? mockAnalysis.comparisonRuns;
  const runs: NormalizedRun[] = rawRuns.map((r) => ({
    model: r.model,
    contextVariant: r.contextVariant,
    latencyMs: r.latencyMs,
    inputTokens: r.inputTokens,
    outputTokens: r.outputTokens,
    hallucinationScore: r.hallucinationScore ?? null,
    coverageScore: "coverageScore" in r ? r.coverageScore : null,
    status: "status" in r ? r.status : undefined,
    bleu4: "bleu4" in r ? r.bleu4 : null,
    rougeL: "rougeL" in r ? r.rougeL : null,
    meteor: "meteor" in r ? r.meteor : null,
    failureTags: "failureTags" in r ? r.failureTags : [],
  }));

  const hallucinationAverages = representationAverages(runs, "hallucinationScore", "min");
  const coverageAverages = representationAverages(runs, "coverageScore", "max");
  const bestRun = bestRunKey(runs);

  return (
    <div>
      <h2 className="mb-2 text-2xl font-semibold">{displayName} -- model comparison</h2>
      <p className="mb-4 text-sm text-slate-600 dark:text-slate-400">
        All 3 models x 3 representations -- the ablation this project's research
        question is about. Each summary is graded on several axes: hallucination
        (0 = fully grounded -- lower is better) and coverage (1.0 = mentions every
        fact the parser found -- higher is better) are grounded LLM-as-judge scores
        against the parser's own static-analysis output; BLEU-4/ROUGE-L/METEOR (when
        a reference summary exists for the repo) measure text overlap against a
        human-reviewable reference; and failure tags flag the specific way a summary
        went wrong (fabricated claim, missed fact, over-generic phrasing) when it did.
        A summary can hit 0 hallucination by saying almost nothing, which low
        coverage would reveal -- no single metric alone is "quality." That's 9
        generations plus two judge calls each, so expect several minutes, not
        seconds.
      </p>

      <form onSubmit={handleSubmit} className="mb-4 flex gap-2">
        <input
          type="url"
          required
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://github.com/owner/repo"
          disabled={isSubmitting}
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900"
        />
        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-60"
        >
          {isSubmitting ? "Comparing... (this takes a while)" : "Run comparison"}
        </button>
      </form>
      {error && (
        <p className="mb-4 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
        </p>
      )}
      {!real && (
        <p className="mb-4 text-xs text-slate-500 dark:text-slate-400">
          Showing placeholder data for {mockAnalysis.repoName} -- submit a URL above for the
          real thing (real runs include live hallucination + coverage scores).
        </p>
      )}

      {/* Per-representation aggregates -- directly answer "which representation wins?"
          on each axis. Hallucination's best is the lowest average; coverage's best is
          the highest -- kept as two separate panels rather than one combined "winner"
          because the two metrics can (and do) disagree on which representation is best. */}
      <AggregatePanel
        title="Average hallucination by representation"
        hint="(mean across models, lower = better)"
        averages={hallucinationAverages}
        formatValue={(v) => v.toFixed(2)}
      />
      <AggregatePanel
        title="Average coverage by representation"
        hint="(mean across models, higher = better)"
        averages={coverageAverages}
        formatValue={(v) => v.toFixed(2)}
      />

      <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 dark:bg-slate-900">
            <tr>
              <th className="px-4 py-2 font-medium">Model</th>
              <th className="px-4 py-2 font-medium">Representation</th>
              <th className="px-4 py-2 font-medium">Latency</th>
              <th className="px-4 py-2 font-medium">
                Token efficiency
                <span className="block text-[10px] font-normal text-slate-400">output / input</span>
              </th>
              <th className="px-4 py-2 font-medium">Hallucination</th>
              <th className="px-4 py-2 font-medium">Coverage</th>
              <th className="px-4 py-2 font-medium">
                Text overlap
                <span className="block text-[10px] font-normal text-slate-400">BLEU / ROUGE / METEOR</span>
              </th>
              <th className="px-4 py-2 font-medium">Failure tags</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => {
              const key = `${run.model}-${run.contextVariant}`;
              const isBest = key === bestRun;
              return (
                <tr
                  key={key}
                  className={
                    "border-t border-slate-200 dark:border-slate-800 " +
                    (isBest ? "bg-emerald-50 dark:bg-emerald-950" : "")
                  }
                >
                  <td className="px-4 py-2 font-mono">{run.model}</td>
                  <td className="px-4 py-2">
                    {CONTEXT_VARIANTS.find((v) => v.value === run.contextVariant)?.label}
                  </td>
                  <td className="px-4 py-2">{run.latencyMs.toLocaleString()} ms</td>
                  <td className="px-4 py-2">{renderTokenEfficiency(run)}</td>
                  <td className="px-4 py-2">
                    {renderScore(run.hallucinationScore, run.status)}
                    {isBest && (
                      <span className="ml-2 rounded bg-emerald-600 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                        ★ best
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2">{renderScore(run.coverageScore, run.status)}</td>
                  <td className="px-4 py-2 font-mono text-xs">{renderTextOverlap(run)}</td>
                  <td className="px-4 py-2">{renderFailureTags(run.failureTags)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AggregatePanel({
  title,
  hint,
  averages,
  formatValue,
}: {
  title: string;
  hint: string;
  averages: VariantAverage[];
  formatValue: (v: number) => string;
}) {
  return (
    <section className="mb-4">
      <h3 className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-300">
        {title} <span className="font-normal text-slate-500 dark:text-slate-400">{hint}</span>
      </h3>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        {averages.map((a) => (
          <div
            key={a.variant}
            className={
              "rounded-lg border p-3 " +
              (a.isBest
                ? "border-emerald-400 bg-emerald-50 dark:border-emerald-700 dark:bg-emerald-950"
                : "border-slate-200 dark:border-slate-800")
            }
          >
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
                {a.label}
              </span>
              {a.isBest && (
                <span className="rounded bg-emerald-600 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                  BEST
                </span>
              )}
            </div>
            <div className="mt-1 text-2xl font-semibold tabular-nums">
              {a.avg === null ? "—" : formatValue(a.avg)}
            </div>
            <div className="text-xs text-slate-500 dark:text-slate-400">
              {a.count > 0 ? `${a.count} judged run${a.count === 1 ? "" : "s"}` : "no judged runs"}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function renderScore(score: number | null, status?: string): string {
  if (typeof score === "number") return score.toFixed(2);
  if (status === "failed") return "failed";
  return "—"; // em dash: no score (run failed, or the judge's own output didn't parse)
}

// "0.12 / 0.34 / 0.28" or an em dash when no reference summary exists yet for this
// repo (reference_summaries/<repo>.json) -- BLEU/ROUGE/METEOR need one to compare
// against, unlike hallucination/coverage which are scored against parser output.
function renderTextOverlap(run: NormalizedRun): string {
  if (run.bleu4 === null && run.rougeL === null && run.meteor === null) return "—";
  const fmt = (v: number | null) => (v === null ? "—" : v.toFixed(2));
  return `${fmt(run.bleu4)} / ${fmt(run.rougeL)} / ${fmt(run.meteor)}`;
}

function renderFailureTags(tags: string[]) {
  if (!tags.length) {
    return <span className="text-xs text-slate-400">—</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {tags.map((tag) => (
        <span
          key={tag}
          className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800 dark:bg-amber-950 dark:text-amber-300"
        >
          {tag.replace(/_/g, " ")}
        </span>
      ))}
    </div>
  );
}

// Output tokens produced per input token consumed -- how much summary you get back
// for the context you fed in. Structured representations feed far fewer input
// tokens for comparable output, so this reads much higher for them than for raw.
function renderTokenEfficiency(run: NormalizedRun): string {
  if (run.status === "failed" || run.inputTokens === 0) return "—";
  return `${((run.outputTokens / run.inputTokens) * 100).toFixed(0)}%`;
}

// -- aggregate helpers ------------------------------------------------------

interface VariantAverage {
  variant: ContextVariant;
  label: string;
  avg: number | null; // null when no run of this representation was judged
  count: number;
  isBest: boolean;
}

function representationAverages(
  runs: NormalizedRun[],
  field: "hallucinationScore" | "coverageScore",
  direction: "min" | "max",
): VariantAverage[] {
  const raw = CONTEXT_VARIANTS.map((v) => {
    const scored = runs.filter((r) => r.contextVariant === v.value && typeof r[field] === "number");
    const avg = scored.length
      ? scored.reduce((sum, r) => sum + (r[field] as number), 0) / scored.length
      : null;
    return { variant: v.value, label: v.label, avg, count: scored.length };
  });

  const withAvg = raw.filter((a) => a.avg !== null);
  const bestAvg = withAvg.length
    ? withAvg.reduce((best, a) =>
        direction === "min"
          ? (a.avg as number) < (best.avg as number) ? a : best
          : (a.avg as number) > (best.avg as number) ? a : best,
      ).avg
    : null;

  return raw.map((a) => ({ ...a, isBest: a.avg !== null && a.avg === bestAvg }));
}

// Row key (`${model}-${variant}`) of the single lowest-hallucination run, or null.
function bestRunKey(runs: NormalizedRun[]): string | null {
  const scored = runs.filter((r) => typeof r.hallucinationScore === "number");
  if (!scored.length) return null;
  const best = scored.reduce((b, r) =>
    (r.hallucinationScore as number) < (b.hallucinationScore as number) ? r : b,
  );
  return `${best.model}-${best.contextVariant}`;
}
