import { useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { mockAnalysis } from "../lib/mockData";
import { CONTEXT_VARIANTS } from "../lib/types";
import { compareModels, ApiError, type CompareResponse } from "../lib/api";

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
  const runs = real?.runs ?? mockAnalysis.comparisonRuns;

  return (
    <div>
      <h2 className="mb-2 text-2xl font-semibold">{displayName} -- model comparison</h2>
      <p className="mb-4 text-sm text-slate-600 dark:text-slate-400">
        All 3 models x 3 representations -- the ablation this project's research
        question is about. Each summary is also graded for hallucination (0 = fully
        grounded in the parser's facts). That's 9 generations plus a judge call each,
        so expect several minutes, not seconds.
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
          real thing (real runs include live hallucination scores).
        </p>
      )}

      <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 dark:bg-slate-900">
            <tr>
              <th className="px-4 py-2 font-medium">Model</th>
              <th className="px-4 py-2 font-medium">Representation</th>
              <th className="px-4 py-2 font-medium">Latency</th>
              <th className="px-4 py-2 font-medium">Input tokens</th>
              <th className="px-4 py-2 font-medium">Output tokens</th>
              <th className="px-4 py-2 font-medium">Hallucination score</th>
              <th className="px-4 py-2 font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr
                key={`${run.model}-${run.contextVariant}`}
                className="border-t border-slate-200 dark:border-slate-800"
              >
                <td className="px-4 py-2 font-mono">{run.model}</td>
                <td className="px-4 py-2">
                  {CONTEXT_VARIANTS.find((v) => v.value === run.contextVariant)?.label}
                </td>
                <td className="px-4 py-2">{run.latencyMs.toLocaleString()} ms</td>
                <td className="px-4 py-2">{run.inputTokens}</td>
                <td className="px-4 py-2">{run.outputTokens}</td>
                <td className="px-4 py-2">{renderScore(run)}</td>
                <td className="px-4 py-2">${run.estimatedCostUsd.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function renderScore(run: { hallucinationScore: number | null; status?: string }): string {
  if (typeof run.hallucinationScore === "number") return run.hallucinationScore.toFixed(2);
  if (run.status === "failed") return "failed";
  return "—"; // em dash: no score (run failed, or the judge's own output didn't parse)
}
