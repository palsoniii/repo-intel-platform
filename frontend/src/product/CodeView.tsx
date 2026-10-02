import { useEffect, useMemo, useRef } from "react";
import hljs from "highlight.js/lib/core";
import javascript from "highlight.js/lib/languages/javascript";
import typescript from "highlight.js/lib/languages/typescript";
import json from "highlight.js/lib/languages/json";
import markdown from "highlight.js/lib/languages/markdown";
import "./code-theme.css";

hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("json", json);
hljs.registerLanguage("markdown", markdown);

function languageFor(path: string): string | null {
  if (/\.(ts|tsx|mts|cts)$/.test(path)) return "typescript";
  if (/\.(js|jsx|mjs|cjs)$/.test(path)) return "javascript";
  if (/\.json$/.test(path)) return "json";
  if (/\.md$/i.test(path)) return "markdown";
  return null;
}

// Highlighted source with line numbers. `focusLine` is scrolled into view and marked;
// `range` limits rendering to an excerpt (used for endpoint snippets).
export default function CodeView({
  path,
  content,
  focusLine,
  range,
  maxHeight = "70vh",
}: {
  path: string;
  content: string;
  focusLine?: number | null;
  range?: [number, number];
  maxHeight?: string;
}) {
  const lines = useMemo(() => {
    const lang = languageFor(path);
    const html = lang ? hljs.highlight(content, { language: lang, ignoreIllegals: true }).value : escapeHtml(content);
    return splitHighlighted(html);
  }, [path, content]);
  const focusRef = useRef<HTMLTableRowElement>(null);

  useEffect(() => {
    focusRef.current?.scrollIntoView({ block: "center" });
  }, [focusLine, content]);

  const [start, end] = range ?? [1, lines.length];
  return (
    <div className="hljs-wrap scroll-quiet overflow-auto rounded-xl border border-line bg-code py-2 text-[12.5px] leading-[1.6] shadow-card" style={{ maxHeight }}>
      <table className="w-full border-collapse font-mono">
        <tbody>
          {lines.slice(start - 1, end).map((html, i) => {
            const n = start + i;
            const focused = n === focusLine;
            return (
              <tr key={n} ref={focused ? focusRef : undefined} className={focused ? "bg-accent-soft" : ""}>
                <td className={`w-12 select-none px-3 text-right align-top tabular-nums ${focused ? "text-accent-text" : "text-muted/70"}`}>{n}</td>
                <td className="whitespace-pre pl-2 pr-4 text-ink" dangerouslySetInnerHTML={{ __html: html || " " }} />
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function escapeHtml(s: string) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// highlight.js returns one HTML string; spans can cross newlines (block comments,
// template literals), so close and reopen open spans at each line break.
function splitHighlighted(html: string): string[] {
  const out: string[] = [];
  const open: string[] = [];
  let line = "";
  const re = /(<span[^>]*>)|(<\/span>)|(\n)|([^<\n]+|<)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(html))) {
    if (m[1]) {
      open.push(m[1]);
      line += m[1];
    } else if (m[2]) {
      open.pop();
      line += m[2];
    } else if (m[3]) {
      out.push(line + "</span>".repeat(open.length));
      line = open.join("");
    } else {
      line += m[4];
    }
  }
  out.push(line + "</span>".repeat(open.length));
  return out;
}
