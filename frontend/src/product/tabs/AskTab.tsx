import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { askRepo, type AskEvent } from "../../lib/product";
import { ApiError } from "../../lib/api";
import { useRepo } from "../RepoLayout";
import { Button, Icon, Spinner } from "../ui";

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
    <div className="mx-auto flex max-w-3xl flex-col">
      {turns.length === 0 && (
        <div className="py-10 text-center">
          <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl border border-line bg-surface text-accent shadow-card">
            <Icon name="sparkles" className="h-5 w-5" />
          </span>
          <h2 className="mt-5 text-2xl font-semibold tracking-tight text-ink">Ask about {analysis.repo_name}</h2>
          <p className="mx-auto mt-2 max-w-lg text-sm leading-relaxed text-ink-2">
            Answers come from a local model that reads this repository's structure and its most
            relevant files. It lists the files it read, so you can check.
          </p>
          <div className="mx-auto mt-8 grid max-w-2xl gap-2 text-left sm:grid-cols-2">
            {suggestions.map((q) => (
              <button
                key={q}
                onClick={() => void send(q)}
                className="group flex items-center justify-between gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-sm text-ink shadow-card transition hover:border-line-strong hover:shadow-pop"
              >
                <span>{q}</span>
                <Icon name="arrow" className="h-4 w-4 shrink-0 text-muted transition group-hover:translate-x-0.5 group-hover:text-ink" />
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-8">
        {turns.map((t, i) =>
          t.role === "user" ? (
            <div key={i} className="flex justify-end">
              <p className="max-w-[80%] rounded-2xl rounded-br-md bg-ink px-4 py-2.5 text-sm leading-relaxed text-page">{t.content}</p>
            </div>
          ) : (
            <div key={i} className="flex gap-3">
              <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-line bg-surface text-accent">
                <Icon name="sparkles" className="h-3.5 w-3.5" />
              </span>
              <div className="min-w-0 flex-1">
                {t.sources && t.sources.length > 0 && (
                  <div className="mb-3 flex flex-wrap items-center gap-1.5">
                    <span className="mr-0.5 text-xs text-muted">Read</span>
                    {t.sources.map((s) => (
                      <Link
                        key={s.path}
                        to={`../files?path=${encodeURIComponent(s.path)}`}
                        title={s.path}
                        className="inline-flex items-center gap-1 rounded-md border border-line bg-surface px-1.5 py-0.5 font-mono text-[11px] text-ink-2 transition hover:border-line-strong hover:text-ink"
                      >
                        <Icon name="file" className="h-3 w-3" />
                        {s.path.split("/").pop()}
                      </Link>
                    ))}
                  </div>
                )}
                {t.content ? (
                  <Markdown text={t.content} />
                ) : t.pending ? (
                  <div className="space-y-2.5 pt-1">
                    <p className="flex items-center gap-2 text-sm text-ink-2">
                      <Spinner /> Reading the code…
                    </p>
                    <div className="skeleton h-3.5 w-full" />
                    <div className="skeleton h-3.5 w-3/4" />
                  </div>
                ) : null}
                {t.error && <p className="mt-2 text-sm text-danger">{t.error}</p>}
                {t.stats?.duration_ms && !t.pending && (
                  <p className="mt-3 text-[11px] text-muted">
                    {(t.stats.duration_ms / 1000).toFixed(0)}s · {t.stats.output_tokens} tokens · local model
                  </p>
                )}
              </div>
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
        className="sticky bottom-6 mt-10 flex items-center gap-2 rounded-2xl border border-line bg-surface p-2 shadow-pop"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={turns.length ? "Ask a follow-up…" : "How does this repository handle…"}
          className="h-10 min-w-0 flex-1 bg-transparent px-3 text-sm text-ink outline-none placeholder:text-muted"
          disabled={busy}
        />
        {busy ? (
          <Button type="button" variant="secondary" onClick={() => abort.current?.abort()}>
            <Icon name="stop" className="h-3.5 w-3.5" /> Stop
          </Button>
        ) : (
          <Button type="submit" variant="primary" disabled={!input.trim()}>
            Ask <Icon name="send" className="h-3.5 w-3.5" />
          </Button>
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
        <pre key={blocks.length} className="my-3 overflow-x-auto rounded-xl border border-line bg-code p-4 font-mono text-xs leading-relaxed text-ink">
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
        <ListTag key={blocks.length} className={`my-3 space-y-1.5 pl-5 text-[15px] leading-relaxed marker:text-muted ${ordered ? "list-decimal" : "list-disc"}`}>
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
      <p key={blocks.length} className={`my-3 text-[15px] leading-relaxed first:mt-0 ${heading ? "font-semibold" : ""}`}>
        <Inline text={joined.replace(/^#{1,4}\s+/, "")} />
      </p>,
    );
  }
  return <div className="text-ink">{blocks}</div>;
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
              <Link key={i} to={`../files?path=${encodeURIComponent(code)}`} className="rounded-md bg-accent-soft px-1.5 py-px font-mono text-[0.82em] text-accent-text hover:underline">
                {code}
              </Link>
            );
          }
          return (
            <code key={i} className="rounded-md border border-line bg-sunken px-1.5 py-px font-mono text-[0.82em]">
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
