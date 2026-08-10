import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";

// Renders Mermaid source to an SVG. Falls back to showing the raw source if Mermaid
// can't parse it (a local model or an odd repo shape can produce invalid syntax), so
// the page never ends up blank.
export default function MermaidDiagram({ chart }: { chart: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const idRef = useRef(`mermaid-${Math.random().toString(36).slice(2)}`);

  useEffect(() => {
    let cancelled = false;
    const dark = window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
    mermaid.initialize({
      startOnLoad: false,
      theme: dark ? "dark" : "default",
      securityLevel: "strict",
    });
    mermaid
      .render(idRef.current, chart)
      .then(({ svg }) => {
        if (!cancelled) {
          setSvg(svg);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to render diagram");
          setSvg(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [chart]);

  return (
    <div>
      {error ? (
        <p className="mb-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
          Couldn't render this as a diagram ({error}). The raw Mermaid source is below.
        </p>
      ) : !svg ? (
        <p className="mb-3 text-sm text-slate-500 dark:text-slate-400">Rendering diagram…</p>
      ) : (
        <div
          className="overflow-x-auto rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950"
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      )}

      <details className="mt-3">
        <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200">
          View Mermaid source
        </summary>
        <pre className="mt-2 overflow-x-auto rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm dark:border-slate-800 dark:bg-slate-900">
          <code>{chart}</code>
        </pre>
      </details>
    </div>
  );
}
