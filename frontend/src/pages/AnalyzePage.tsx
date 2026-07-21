import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { mockAnalysis } from "../lib/mockData";

export default function AnalyzePage() {
  const [url, setUrl] = useState("");
  const navigate = useNavigate();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    // Placeholder: real submit will POST to /analyze (backend/app/main.py) and
    // route to the returned repo's pages. For now every submission jumps to the
    // one mock repo so the rest of the dashboard is reachable.
    navigate(`/repo/${encodeURIComponent(mockAnalysis.repoName)}/summary`);
  }

  return (
    <div className="mx-auto max-w-xl">
      <h2 className="mb-2 text-2xl font-semibold">Analyze a repository</h2>
      <p className="mb-6 text-sm text-slate-600 dark:text-slate-400">
        Paste a GitHub URL for an Express.js or NestJS repo. This form is not wired to
        the backend yet -- submitting takes you to placeholder results for{" "}
        <span className="font-mono">{mockAnalysis.repoName}</span>.
      </p>
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          type="url"
          required
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://github.com/owner/repo"
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 dark:border-slate-700 dark:bg-slate-900"
        />
        <button
          type="submit"
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500"
        >
          Analyze
        </button>
      </form>
    </div>
  );
}
