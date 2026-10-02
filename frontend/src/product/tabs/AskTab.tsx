import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { askRepo, type AskEvent } from "../../lib/product";
import { ApiError } from "../../lib/api";
import { useRepo } from "../RepoLayout";
import { Spinner } from "../ui";

interface Turn {
  role: "user" | "assistant";
  content: string;
  sources?: { path: string }[];
  pending?: boolean;
  error?: string;
  stats?: { output_tokens?: number; duration_ms?: number };
}

// Conversations survive tab switches within a session (but not reloads).
const conversations = new Map<string, Turn[]>();

export default function AskTab() {
  const { analysis } = useRepo();
  const [turns, setTurns] = useState<Turn[]>(() => conversations.get(analysis.id) ?? []);
  const [input, setInput] = useState("");
  const busy = turns.some((t) => t.pending);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    conversations.set(analysis.id, turns);
    bottom.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [turns, analysis.id]);

  useEffect(() => () => abort.current?.abort(), []);

  async function send(question: string) {
    if (!question.trim() || busy) return;
    const history = turns.filter((t) => !t.error).map((t) => ({ role: t.role, content: t.content }));
    setInput("");
    setTurns((ts) => [...ts, { role: "user", content: question }, { role: "assistant", content: "", pending: true }]);
    const update = (fn: (t: Turn) => Turn) =>
      setTurns((ts) => ts.map((t, i) => (i === ts.length - 1 ? fn(t) : t)));

    abort.current = new AbortController();
    try {
      await askRepo(
        analysis.id,
        question,
        history,
        (e: AskEvent) => {
          if (e.type === "sources") update((t) => ({ ...t, sources: e.sources }));
          else if (e.type === "token") update((t) => ({ ...t, content: t.content + e.text }));
          else if (e.type === "done") update((t) => ({ ...t, pending: false, stats: e }));
          else if (e.type === "error") update((t) => ({ ...t, pending: false, error: e.message }));
        },
        abort.current.signal,
      );
      update((t) => ({ ...t, pending: false }));
    } catch (err) {
      update((t) => ({ ...t, pending: false, error: err instanceof ApiError ? err.message : "Something went wrong." }));
    }
  }

  const suggestions = analysis.suggested_questions ?? [];

  return (
    <div className="mx-auto max-w-3xl">
      {turns.length === 0 && (
        <div className="py-6 text-center">
          <p className="text-lg font-medium">Ask anything about {analysis.repo_name}</p>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Answers come from a local model, grounded in this repository's knowledge graph and the most
            relevant source files, which are listed under each answer.
          </p>
          <div className="mt-6 flex flex-wrap justify-center gap-2">
            {suggestions.map((q) => (
              <button
                key={q}
                onClick={() => void send(q)}
                className="rounded-full border border-slate-300 px-3 py-1.5 text-sm hover:border-indigo-400 hover:text-indigo-700 dark:border-slate-700 dark:hover:text-indigo-300"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-5">
        {turns.map((t, i) =>
          t.role === "user" ? (
            <div key={i} className="flex justify-end">
              <p className="max-w-[85%] rounded-2xl rounded-br-sm bg-indigo-600 px-4 py-2 text-sm text-white">{t.content}</p>
            </div>
          ) : (
            <div key={i} className="rounded-2xl rounded-bl-sm border border-slate-200 px-4 py-3 dark:border-slate-800">
              {t.sources && t.sources.length > 0 && (
                <div className="mb-2 flex flex-wrap items-center gap-1.5 text-xs">
                  <span className="text-slate-400">Read:</span>
                  {t.sources.map((s) => (
                    <Link
                      key={s.path}
                      to={`../files?path=${encodeURIComponent(s.path)}`}
                      className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-slate-600 hover:text-indigo-700 dark:bg-slate-800 dark:text-slate-300"
                    >
                      {s.path}
                    </Link>
                  ))}
                </div>
              )}
              {t.content ? (
                <Markdown text={t.content} />
              ) : t.pending ? (
                <p className="flex items-center gap-2 text-sm text-slate-500">
                  <Spinner /> Reading the code…
                </p>
              ) : null}
              {t.error && <p className="mt-2 text-sm text-rose-600 dark:text-rose-400">{t.error}</p>}
              {t.stats?.duration_ms && !t.pending && (
                <p className="mt-2 text-right text-[11px] text-slate-400">
                  {t.stats.output_tokens} tokens · {(t.stats.duration_ms / 1000).toFixed(1)}s · local model
                </p>
              )}
            </div>
          ),
        )}
      </div>
      <div ref={bottom} />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
        className="sticky bottom-4 mt-6 flex gap-2 rounded-xl border border-slate-200 bg-white p-2 shadow-sm dark:border-slate-800 dark:bg-slate-900"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="How does this repository handle…"
          className="min-w-0 flex-1 bg-transparent px-2 text-sm outline-none"
          disabled={busy}
        />
        {busy ? (
          <button
            type="button"
            onClick={() => abort.current?.abort()}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700"
          >
            Stop
          </button>
        ) : (
          <button type="submit" className="rounded-lg bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-500">
            Ask
          </button>
        )}
      </form>
    </div>
  );
}

// Minimal Markdown: fenced code, bullets/numbered lists, paragraphs, **bold** and
// `code`. Backticked repo paths become links to the file viewer. Rendered as React
// elements (never innerHTML) because the text comes from a model.
function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim().startsWith("```")) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) body.push(lines[i++]);
      i++;
      blocks.push(
        <pre key={blocks.length} className="my-2 overflow-x-auto rounded-lg bg-slate-100 p-3 text-xs dark:bg-slate-900">
          <code>{body.join("\n")}</code>
        </pre>,
      );
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const items: string[] = [];
      const ordered = /^\s*\d+\./.test(line);
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, ""));
        i++;
      }
      const ListTag = ordered ? "ol" : "ul";
      blocks.push(
        <ListTag key={blocks.length} className={`my-2 space-y-1 pl-5 text-sm ${ordered ? "list-decimal" : "list-disc"}`}>
          {items.map((it, j) => (
            <li key={j}>
              <Inline text={it} />
            </li>
          ))}
        </ListTag>,
      );
      continue;
    }
    if (line.trim() === "") {
      i++;
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() !== "" && !lines[i].trim().startsWith("```") && !/^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
      para.push(lines[i++]);
    }
    const joined = para.join(" ");
    const heading = /^#{1,4}\s+/.test(joined);
    blocks.push(
      <p key={blocks.length} className={`my-2 text-sm leading-relaxed ${heading ? "font-semibold" : ""}`}>
        <Inline text={joined.replace(/^#{1,4}\s+/, "")} />
      </p>,
    );
  }
  return <div className="text-slate-800 dark:text-slate-200">{blocks}</div>;
}

function Inline({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith("`") && p.endsWith("`")) {
          const code = p.slice(1, -1);
          if (/^[\w./-]+\.(js|ts|json|prisma|mjs|cjs)$/.test(code)) {
            return (
              <Link key={i} to={`../files?path=${encodeURIComponent(code)}`} className="rounded bg-indigo-50 px-1 font-mono text-[0.85em] text-indigo-700 hover:underline dark:bg-indigo-950 dark:text-indigo-300">
                {code}
              </Link>
            );
          }
          return (
            <code key={i} className="rounded bg-slate-100 px-1 font-mono text-[0.85em] dark:bg-slate-800">
              {code}
            </code>
          );
        }
        if (p.startsWith("**") && p.endsWith("**")) return <strong key={i}>{p.slice(2, -2)}</strong>;
        return <Fragment key={i}>{p}</Fragment>;
      })}
    </>
  );
}
