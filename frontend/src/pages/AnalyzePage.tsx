import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { summarizeRepository, ApiError } from "../lib/api";

export default function AnalyzePage() {
  const [url, setUrl] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

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
      <p className="mb-6 text-sm text-slate-600 dark:text-slate-400">
        Paste a GitHub URL for an Express.js or NestJS repo. This calls the real{" "}
        <span className="font-mono">POST /summarize</span> pipeline (parser -&gt; Neo4j -&gt;
        context -&gt; Ollama) -- it needs a reachable Neo4j and Ollama daemon (see backend/
        README) to succeed.
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
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-60"
        >
          {isSubmitting ? "Analyzing..." : "Analyze"}
        </button>
      </form>
      {error && (
        <p className="mt-4 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
        </p>
      )}
    </div>
  );
}
