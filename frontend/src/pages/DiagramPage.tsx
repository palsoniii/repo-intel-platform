import { useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { mockAnalysis } from "../lib/mockData";
import { getArchitectureDiagram, ApiError, type DiagramResponse } from "../lib/api";

export default function DiagramPage() {
  const { repoName } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const real = (location.state as { real?: DiagramResponse } | null)?.real;

  const [url, setUrl] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const result = await getArchitectureDiagram(url);
      navigate(`/repo/${encodeURIComponent(result.repoName)}/diagram`, {
        state: { real: result },
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setIsSubmitting(false);
    }
  }

  const displayName = real?.repoName ?? repoName;
  const diagramMermaid = real?.diagramMermaid ?? mockAnalysis.diagramMermaid;

  return (
    <div>
      <h2 className="mb-2 text-2xl font-semibold">{displayName} -- architecture diagram</h2>
      <p className="mb-4 text-sm text-slate-600 dark:text-slate-400">
        Raw Mermaid source generated directly from the Neo4j graph -- no LLM call.
        Rendering it visually (not just as text) is still open.
      </p>

      <form onSubmit={handleSubmit} className="mb-6 flex gap-2">
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
          {isSubmitting ? "Generating..." : "Generate diagram"}
        </button>
      </form>
      {error && (
        <p className="mb-4 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
        </p>
      )}
      {!real && (
        <p className="mb-4 text-xs text-slate-500 dark:text-slate-400">
          Showing placeholder data for {mockAnalysis.repoName} -- submit a URL above for the
          real thing.
        </p>
      )}

      <pre className="overflow-x-auto rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm dark:border-slate-800 dark:bg-slate-900">
        <code>{diagramMermaid}</code>
      </pre>
    </div>
  );
}
