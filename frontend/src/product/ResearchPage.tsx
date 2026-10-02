import { useState } from "react";
import { Link } from "react-router-dom";
import { Card, SectionTitle } from "./ui";

// Figures from the submitted paper (docs/paper.tex): Figure "fig:main" and Table
// "tab:tokens". 18 repositories, judge gemma2:9b, generators run on a GPU cluster.
// Edit only alongside the paper.
const MODELS = ["codellama:13b", "qwen2.5-coder:14b", "qwen2.5-coder:32b"] as const;
const ARMS = [
  { key: "raw", label: "Raw source" },
  { key: "dep", label: "Dependency graph" },
  { key: "kg", label: "Knowledge graph" },
] as const;
type Arm = (typeof ARMS)[number]["key"];

const COVERAGE: Record<(typeof MODELS)[number], Record<Arm, number>> = {
  "codellama:13b": { raw: 0.177, dep: 0.428, kg: 0.775 },
  "qwen2.5-coder:14b": { raw: 0.454, dep: 0.682, kg: 0.83 },
  "qwen2.5-coder:32b": { raw: 0.442, dep: 0.693, kg: 0.947 },
};
const HALLUCINATION: typeof COVERAGE = {
  "codellama:13b": { raw: 0.789, dep: 0.514, kg: 0.239 },
  "qwen2.5-coder:14b": { raw: 0.468, dep: 0.365, kg: 0.189 },
  "qwen2.5-coder:32b": { raw: 0.549, dep: 0.395, kg: 0.208 },
};
const TOKENS: typeof COVERAGE = {
  "codellama:13b": { raw: 4641, dep: 3038, kg: 3492 },
  "qwen2.5-coder:14b": { raw: 5798, dep: 2422, kg: 2854 },
  "qwen2.5-coder:32b": { raw: 5798, dep: 2422, kg: 2854 },
};

export default function ResearchPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <header>
        <p className="text-sm font-medium text-indigo-600 dark:text-indigo-400">The research behind the platform</p>
        <h2 className="mt-1 text-3xl font-semibold tracking-tight">
          Does structured repository representation improve LLM-generated codebase summaries?
        </h2>
        <p className="mt-3 max-w-3xl text-slate-600 dark:text-slate-400">
          A model handed raw source has to do static analysis and writing at once, and the analysis
          half is where it invents frameworks, dependencies and endpoints. We tested handing that job
          to a deterministic parser instead: the same parse rendered three ways, sent to three local
          code models, scored by an independent judge across 18 Express.js and NestJS repositories.
        </p>
      </header>

      <div className="grid gap-3 sm:grid-cols-3">
        <Headline value="4.4×" label="coverage gain for the weakest model (0.177 → 0.775)" />
        <Headline value="> 50%" label="fewer hallucinated claims with the knowledge graph, all three models" />
        <Headline value="1.3–2.0×" label="fewer input tokens than raw source" />
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <SectionTitle hint="higher is better">Coverage of the repository's real structure</SectionTitle>
          <GroupedBars data={COVERAGE} />
        </Card>
        <Card>
          <SectionTitle hint="lower is better">Hallucination score</SectionTitle>
          <GroupedBars data={HALLUCINATION} />
        </Card>
      </div>
      <Legend />

      <Card>
        <SectionTitle>All figures</SectionTitle>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500 dark:text-slate-400">
                <th className="py-1.5 pr-4 font-medium">Model</th>
                <th className="py-1.5 pr-4 font-medium">Representation</th>
                <th className="py-1.5 pr-4 text-right font-medium">Coverage</th>
                <th className="py-1.5 pr-4 text-right font-medium">Hallucination</th>
                <th className="py-1.5 text-right font-medium">Input tokens</th>
              </tr>
            </thead>
            <tbody>
              {MODELS.flatMap((m) =>
                ARMS.map((a, i) => (
                  <tr key={m + a.key} className={`border-t border-slate-100 dark:border-slate-800 ${a.key === "kg" ? "font-medium" : ""}`}>
                    <td className="py-1.5 pr-4 font-mono text-xs">{i === 0 ? m : ""}</td>
                    <td className="py-1.5 pr-4">{a.label}</td>
                    <td className="py-1.5 pr-4 text-right tabular-nums">{COVERAGE[m][a.key].toFixed(3)}</td>
                    <td className="py-1.5 pr-4 text-right tabular-nums">{HALLUCINATION[m][a.key].toFixed(3)}</td>
                    <td className="py-1.5 text-right tabular-nums">{TOKENS[m][a.key].toLocaleString()}</td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
          Means over 18 repositories (17 for the qwen models on tokens), judge gemma2:9b. The knowledge
          graph beats raw source on coverage in every model (Holm-adjusted p ≤ 0.002, rank-biserial r ≥ 0.95)
          and on hallucination (Holm-adjusted p ≤ 0.022).
        </p>
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <SectionTitle>What this platform takes from it</SectionTitle>
          <ul className="list-inside list-disc space-y-1.5 text-sm text-slate-700 dark:text-slate-300">
            <li>The AI summary is written from the knowledge graph, never from raw source.</li>
            <li>Diagrams, endpoints, request flows and data models come straight from the parser: no model involved, so nothing on those tabs can be hallucinated.</li>
            <li>Ask-the-repo pairs the graph with the most relevant source files and shows which files it read.</li>
          </ul>
        </Card>
        <Card>
          <SectionTitle>Honest caveats</SectionTitle>
          <ul className="list-inside list-disc space-y-1.5 text-sm text-slate-700 dark:text-slate-300">
            <li>On 552 hand-scored claims the human annotator was 96% accurate, the automatic judge 83%, and they agree at only κ = 0.26: trust the direction of the result, not the absolute scores.</li>
            <li>One generator (codellama:13b) shows an unresolved context-window anomaly, disclosed in the paper.</li>
            <li>Scope: Express.js and NestJS only, local open models only.</li>
          </ul>
        </Card>
      </div>

      <p className="text-sm text-slate-500 dark:text-slate-400">
        Want to run the comparison live on one repository?{" "}
        <Link to="/research/live" className="text-indigo-700 hover:underline dark:text-indigo-300">
          Open the live comparison
        </Link>{" "}
        (runs every model on every representation, so it takes several minutes).
      </p>
    </div>
  );
}

function Headline({ value, label }: { value: string; label: string }) {
  return (
    <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
      <p className="text-3xl font-semibold tracking-tight">{value}</p>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{label}</p>
    </div>
  );
}

// Ordered representations, so one hue from light (least structure) to dark (most).
const ARM_CLASS: Record<Arm, string> = {
  raw: "bg-indigo-300 dark:bg-indigo-800",
  dep: "bg-indigo-500 dark:bg-indigo-500",
  kg: "bg-indigo-800 dark:bg-indigo-200",
};

function Legend() {
  return (
    <div className="-mt-4 flex flex-wrap justify-center gap-5 text-sm text-slate-600 dark:text-slate-400">
      {ARMS.map((a) => (
        <span key={a.key} className="flex items-center gap-2">
          <span className={`h-3 w-3 rounded-sm ${ARM_CLASS[a.key]}`} /> {a.label}
        </span>
      ))}
    </div>
  );
}

function GroupedBars({ data }: { data: typeof COVERAGE }) {
  const [hover, setHover] = useState<{ m: string; a: Arm } | null>(null);
  const height = 180;
  return (
    <div>
      <div className="relative flex items-end gap-6 border-b border-slate-200 pl-8 dark:border-slate-700" style={{ height }}>
        {[0, 0.5, 1].map((t) => (
          <div key={t} className="pointer-events-none absolute left-0 right-0 border-t border-slate-100 dark:border-slate-800" style={{ bottom: t * height }}>
            <span className="absolute -top-2 left-0 text-[10px] tabular-nums text-slate-400">{t.toFixed(1)}</span>
          </div>
        ))}
        {MODELS.map((m) => (
          <div key={m} className="relative flex flex-1 items-end justify-center gap-[2px]" style={{ height }}>
            {ARMS.map((a) => {
              const v = data[m][a.key];
              const active = hover?.m === m && hover.a === a.key;
              return (
                <div
                  key={a.key}
                  onMouseEnter={() => setHover({ m, a: a.key })}
                  onMouseLeave={() => setHover(null)}
                  className="relative flex h-full w-5 items-end"
                >
                  <div className={`w-full rounded-t ${ARM_CLASS[a.key]} ${hover && !active ? "opacity-50" : ""}`} style={{ height: v * height }} />
                  {active && (
                    <div className="absolute bottom-full left-1/2 z-10 mb-1 -translate-x-1/2 whitespace-nowrap rounded bg-slate-900 px-2 py-1 text-xs text-white shadow dark:bg-slate-100 dark:text-slate-900" style={{ bottom: v * height + 4 }}>
                      {ARMS.find((x) => x.key === a.key)?.label}: {v.toFixed(3)}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
      <div className="flex gap-6 pl-8 pt-1.5">
        {MODELS.map((m) => (
          <p key={m} className="flex-1 text-center font-mono text-[11px] text-slate-500 dark:text-slate-400">{m}</p>
        ))}
      </div>
    </div>
  );
}
