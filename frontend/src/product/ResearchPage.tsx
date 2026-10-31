import { useState } from "react";
import { Link } from "react-router-dom";
import { Card, CardTitle, Icon } from "./ui";
import { useSystem } from "../lib/product";

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
  // The live comparison runs every study model on the local Ollama, which a public
  // deployment doesn't have (and the backend refuses there).
  const system = useSystem();
  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <header>
        <p className="text-sm font-medium text-accent-text">The research behind the platform</p>
        <h2 className="mt-2 text-[34px] font-semibold leading-tight tracking-[-0.02em] text-ink">
          Does structured repository representation improve LLM-generated codebase summaries?
        </h2>
        <p className="mt-4 max-w-3xl text-[16px] leading-relaxed text-ink-2">
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
          <CardTitle aside="higher is better">Coverage of the repository's real structure</CardTitle>
          <GroupedBars data={COVERAGE} />
        </Card>
        <Card>
          <CardTitle aside="lower is better">Hallucination score</CardTitle>
          <GroupedBars data={HALLUCINATION} />
        </Card>
      </div>
      <Legend />

      <Card>
        <CardTitle>All figures</CardTitle>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted">
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
                  <tr key={m + a.key} className={`border-t border-line ${a.key === "kg" ? "font-semibold text-ink" : "text-ink-2"}`}>
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
        <p className="mt-4 text-xs leading-relaxed text-muted">
          Means over 18 repositories (17 for the qwen models on tokens), judge gemma2:9b. The knowledge
          graph beats raw source on coverage in every model (Holm-adjusted p ≤ 0.002, rank-biserial r ≥ 0.95)
          and on hallucination (Holm-adjusted p ≤ 0.022).
        </p>
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardTitle>What this platform takes from it</CardTitle>
          <ul className="space-y-2.5 text-sm leading-relaxed text-ink-2 [&>li]:flex [&>li]:gap-2.5 [&>li]:before:mt-2 [&>li]:before:h-1 [&>li]:before:w-1 [&>li]:before:shrink-0 [&>li]:before:rounded-full [&>li]:before:bg-muted [&>li]:before:content-['']">
            <li>The AI summary is written from the knowledge graph, never from raw source.</li>
            <li>Diagrams, endpoints, request flows and data models come straight from the parser: no model involved, so nothing on those tabs can be hallucinated.</li>
            <li>Ask-the-repo pairs the graph with the most relevant source files and shows which files it read.</li>
          </ul>
        </Card>
        <Card>
          <CardTitle>Honest caveats</CardTitle>
          <ul className="space-y-2.5 text-sm leading-relaxed text-ink-2 [&>li]:flex [&>li]:gap-2.5 [&>li]:before:mt-2 [&>li]:before:h-1 [&>li]:before:w-1 [&>li]:before:shrink-0 [&>li]:before:rounded-full [&>li]:before:bg-muted [&>li]:before:content-['']">
            <li>On 552 hand-scored claims the human annotator was 96% accurate, the automatic judge 83%, and they agree at only κ = 0.26: trust the direction of the result, not the absolute scores.</li>
            <li>One generator (codellama:13b) shows an unresolved context-window anomaly, disclosed in the paper.</li>
            <li>Scope: Express.js and NestJS only, local open models only.</li>
          </ul>
        </Card>
      </div>

      {system && !system.public && <Link
        to="/research/live"
        className="group flex items-center justify-between gap-4 rounded-2xl border border-line bg-surface px-6 py-5 shadow-card transition hover:border-line-strong hover:shadow-pop"
      >
        <span>
          <span className="block font-medium text-ink">Run the comparison live</span>
          <span className="block text-sm text-ink-2">Every model on every representation, for one repository. Takes several minutes.</span>
        </span>
        <Icon name="arrow" className="h-5 w-5 text-muted transition group-hover:translate-x-0.5 group-hover:text-ink" />
      </Link>}
    </div>
  );
}

function Headline({ value, label }: { value: string; label: string }) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-5 shadow-card">
      <p className="text-[34px] font-semibold leading-none tracking-[-0.02em] text-ink">{value}</p>
      <p className="mt-2 text-sm leading-snug text-ink-2">{label}</p>
    </div>
  );
}

// Ordered representations, so one hue from light (least structure) to dark (most).
const ARM_COLOR: Record<Arm, string> = {
  raw: "var(--ord-1)",
  dep: "var(--ord-2)",
  kg: "var(--ord-3)",
};

function Legend() {
  return (
    <div className="-mt-2 flex flex-wrap justify-center gap-6 text-sm text-ink-2">
      {ARMS.map((a) => (
        <span key={a.key} className="flex items-center gap-2">
          <span className="h-3 w-3 rounded-sm" style={{ background: ARM_COLOR[a.key] }} /> {a.label}
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
      <div className="relative flex items-end gap-6 border-b border-line-strong pl-8" style={{ height }}>
        {[0, 0.5, 1].map((t) => (
          <div key={t} className="pointer-events-none absolute left-0 right-0 border-t border-line" style={{ bottom: t * height }}>
            <span className="absolute -top-2 left-0 text-[10px] tabular-nums text-muted">{t.toFixed(1)}</span>
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
                  <div className={`w-full rounded-t-[4px] transition-opacity ${hover && !active ? "opacity-40" : ""}`} style={{ height: v * height, background: ARM_COLOR[a.key] }} />
                  {active && (
                    <div className="absolute left-1/2 z-10 -translate-x-1/2 whitespace-nowrap rounded-lg bg-ink px-2.5 py-1.5 text-xs text-page shadow-pop" style={{ bottom: v * height + 4 }}>
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
          <p key={m} className="flex-1 text-center font-mono text-[11px] text-muted">{m}</p>
        ))}
      </div>
    </div>
  );
}
