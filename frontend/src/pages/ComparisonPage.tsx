import { useParams } from "react-router-dom";
import { mockAnalysis } from "../lib/mockData";
import { CONTEXT_VARIANTS } from "../lib/types";

export default function ComparisonPage() {
  const { repoName } = useParams();
  const { comparisonRuns } = mockAnalysis;

  return (
    <div>
      <h2 className="mb-2 text-2xl font-semibold">{repoName} -- model comparison</h2>
      <p className="mb-6 text-sm text-slate-600 dark:text-slate-400">
        Placeholder numbers for all 3 models x 3 representations (the ablation this
        project's research question is about). Hallucination score is 0 = no
        unsupported claims found by the LLM-as-judge; real scoring lands in Week 4.
      </p>

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
            {comparisonRuns.map((run) => (
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
                <td className="px-4 py-2">{run.hallucinationScore.toFixed(2)}</td>
                <td className="px-4 py-2">${run.estimatedCostUsd.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
