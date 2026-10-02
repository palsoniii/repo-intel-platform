import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";
import { token, useResolvedTheme } from "../lib/theme";

// Renders Mermaid source to an SVG, themed from the app's design tokens and redrawn
// when the theme changes. Falls back to showing the raw source if Mermaid can't
// parse it, so the page never ends up blank.
export default function MermaidDiagram({ chart, bare = false }: { chart: string; bare?: boolean }) {
  const theme = useResolvedTheme();
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const counter = useRef(0);
  const base = useRef(`mermaid-${Math.random().toString(36).slice(2)}`);

  useEffect(() => {
    let cancelled = false;
    const t = (n: string) => token(n);
    mermaid.initialize({
      startOnLoad: false,
      theme: "base",
      themeVariables: {
        background: t("sunken"),
        primaryColor: t("surface"),
        primaryTextColor: t("ink"),
        primaryBorderColor: t("line-strong"),
        lineColor: t("muted"),
        secondaryColor: t("sunken"),
        tertiaryColor: t("surface"),
        textColor: t("ink"),
        mainBkg: t("surface"),
        nodeBorder: t("line-strong"),
        clusterBkg: t("sunken"),
        edgeLabelBackground: t("surface"),
        attributeBackgroundColorOdd: t("surface"),
        attributeBackgroundColorEven: t("sunken"),
        rowOdd: t("surface"),
        rowEven: t("sunken"),
        fontFamily: "ui-sans-serif, system-ui, -apple-system, sans-serif",
        fontSize: "13px",
      },
      securityLevel: "strict",
      // Grouped diagrams of large repos exceed Mermaid's default limits.
      maxEdges: 2000,
      maxTextSize: 200000,
      flowchart: { useMaxWidth: false, htmlLabels: true, curve: "basis" },
      er: { useMaxWidth: false },
    });
    // Mermaid refuses to reuse an id it has rendered, so each render gets a fresh one.
    counter.current += 1;
    mermaid
      .render(`${base.current}-${counter.current}`, chart)
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
  }, [chart, theme]);

  return (
    <div>
      {error ? (
        <p className="mb-3 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">
          Couldn't render this diagram ({error}). The source is below.
        </p>
      ) : !svg ? (
        <div className="skeleton h-40 w-full" />
      ) : (
        <div className={bare ? "" : "overflow-x-auto"} dangerouslySetInnerHTML={{ __html: svg }} />
      )}

      {(!bare || error) && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-muted hover:text-ink">Mermaid source</summary>
          <pre className="scroll-quiet mt-2 overflow-x-auto rounded-xl border border-line bg-code p-4 font-mono text-xs text-ink">
            <code>{chart}</code>
          </pre>
        </details>
      )}
    </div>
  );
}
