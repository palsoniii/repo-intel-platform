import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { summarizeRepository, ApiError } from "../lib/api";

export default function AnalyzePage() {
  const [url, setUrl] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  // Without a visible timer the page looks frozen: a small repo takes ~28s and a large
  // one 47-146s, and the only previous signal was the button label. Users concluded it
  // was broken and navigated away mid-run.
  useEffect(() => {
    if (!isSubmitting) {
      setElapsed(0);
      return;
    }
    const id = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [isSubmitting]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const result = await summarizeRepository(url);
      navigate(`/repo/${encodeURIComponent(result.repoName)}/summary`, {
        state: { real: result },
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl">
      <h2 className="mb-2 text-2xl font-semibold">Analyze a repository</h2>
      <p className="mb-2 text-sm text-slate-600 dark:text-slate-400">
        Paste a GitHub URL for an <strong>Express.js or NestJS</strong> repository. This
        runs the real pipeline: shallow clone -&gt; tree-sitter parse -&gt; Neo4j -&gt;
        context -&gt; local model.
      </p>
      <p className="mb-6 text-xs text-slate-500 dark:text-slate-400">
        Expect <strong>~30 seconds</strong> for a small repository and up to{" "}
        <strong>2-3 minutes</strong> for a large one -- generation runs on a local 7B model
        with CPU offload, so it is slow but it is working. Monorepos whose server lives in
        a subdirectory (immich, directus, vendure) are rejected: the parser looks at the
        repository root.
      </p>
      <form onSubmit={handleSubmit} className="flex gap-2">
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
          className="whitespace-nowrap rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-60"
        >
          {isSubmitting ? `Analyzing... ${elapsed}s` : "Analyze"}
        </button>
      </form>

      {isSubmitting && (
        <div className="mt-4 rounded-md border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm dark:border-indigo-900 dark:bg-indigo-950">
          <p className="font-medium text-indigo-800 dark:text-indigo-200">
            Running -- {elapsed}s elapsed
          </p>
          <p className="mt-1 text-xs text-indigo-700 dark:text-indigo-300">
            {elapsed < 20
              ? "Cloning and parsing the repository..."
              : elapsed < 60
                ? "Parsed. The local model is generating the summary now."
                : "Still generating -- large repositories can take several minutes. Do not navigate away."}
          </p>
        </div>
      )}

      {error && (
        <p className="mt-4 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
        </p>
      )}
    </div>
  );
}
