import type { ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={`rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900/60 ${className}`}
    >
      {children}
    </div>
  );
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-4">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {children}
      </h3>
      {hint && <span className="text-xs text-slate-400 dark:text-slate-500">{hint}</span>}
    </div>
  );
}

const METHOD_COLORS: Record<string, string> = {
  GET: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  POST: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  PUT: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  PATCH: "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300",
  DELETE: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
};

export function MethodBadge({ method }: { method: string }) {
  return (
    <span
      className={`inline-block w-16 shrink-0 rounded px-1.5 py-0.5 text-center font-mono text-[11px] font-bold ${
        METHOD_COLORS[method] ?? "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300"
      }`}
    >
      {method}
    </span>
  );
}

export function Pill({ children, tone = "slate" }: { children: ReactNode; tone?: "slate" | "indigo" | "emerald" | "amber" | "rose" }) {
  const tones = {
    slate: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
    indigo: "bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300",
    emerald: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
    amber: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
    rose: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
  };
  return <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${tones[tone]}`}>{children}</span>;
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="4" />
      <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
    </svg>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-12 text-sm text-slate-500 dark:text-slate-400">
      <Spinner /> {label}
    </div>
  );
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/60 dark:text-rose-300">
      {children}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 px-6 py-12 text-center dark:border-slate-700">
      <p className="font-medium text-slate-700 dark:text-slate-300">{title}</p>
      {children && <div className="mx-auto mt-2 max-w-lg text-sm text-slate-500 dark:text-slate-400">{children}</div>}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900/60" title={hint}>
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      <div className="text-xs text-slate-500 dark:text-slate-400">{label}</div>
    </div>
  );
}

// One colour per architectural layer, shared by the overview bar, file tree and graph.
export const LAYER_COLORS: Record<string, string> = {
  entry: "#6366f1",
  module: "#8b5cf6",
  route: "#0ea5e9",
  middleware: "#f59e0b",
  service: "#10b981",
  data: "#ef4444",
  contract: "#64748b",
  config: "#a855f7",
  util: "#14b8a6",
  other: "#94a3b8",
  test: "#cbd5e1",
};

export const LAYER_LABELS: Record<string, string> = {
  entry: "Entry points",
  module: "Modules",
  route: "Routes & controllers",
  middleware: "Middleware & auth",
  service: "Services",
  data: "Data & models",
  contract: "DTOs & types",
  config: "Configuration",
  util: "Utilities",
  other: "Other",
  test: "Tests",
};

export function frameworkLabel(framework: string | null | undefined): string {
  if (!framework) return "Unknown";
  const f = framework.toLowerCase();
  if (f === "nestjs") return "NestJS";
  if (f === "express") return "Express.js";
  return framework;
}

export function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}
