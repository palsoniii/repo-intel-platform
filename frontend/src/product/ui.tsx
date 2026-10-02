import type { ReactNode, SVGProps } from "react";

// ---------------------------------------------------------------------------
// Layers. The backend classifies files into eleven fine-grained layers; people
// need five, so the UI folds them into groups that each carry one colour,
// everywhere: overview bar, architecture lanes, graph nodes, file tree.
// ---------------------------------------------------------------------------

export type LayerGroup = "setup" | "route" | "middleware" | "service" | "data" | "support" | "test";

export const LAYER_GROUPS: { id: LayerGroup; label: string; hint: string }[] = [
  { id: "setup", label: "App setup", hint: "Entry points, modules and configuration" },
  { id: "route", label: "Routes & controllers", hint: "Where HTTP requests arrive" },
  { id: "middleware", label: "Middleware & auth", hint: "Runs before handlers: auth, guards, validation" },
  { id: "service", label: "Services", hint: "Business logic" },
  { id: "data", label: "Data & models", hint: "Database models, schemas and repositories" },
  { id: "support", label: "Supporting code", hint: "DTOs, types and utilities" },
  { id: "test", label: "Tests", hint: "Test files" },
];

const RAW_TO_GROUP: Record<string, LayerGroup> = {
  entry: "setup",
  module: "setup",
  config: "setup",
  route: "route",
  middleware: "middleware",
  service: "service",
  data: "data",
  contract: "support",
  util: "support",
  other: "support",
  test: "test",
};

export function layerGroup(raw: string | undefined | null): LayerGroup {
  return RAW_TO_GROUP[raw ?? "other"] ?? "support";
}

export function layerColor(raw: string | undefined | null): string {
  return `var(--layer-${layerGroup(raw)})`;
}

export function groupColor(group: LayerGroup): string {
  return `var(--layer-${group})`;
}

export function groupLabel(group: LayerGroup): string {
  return LAYER_GROUPS.find((g) => g.id === group)?.label ?? group;
}

// ---------------------------------------------------------------------------
// Icons (stroke icons, 24px grid, drawn to match each other).
// ---------------------------------------------------------------------------

const ICONS: Record<string, ReactNode> = {
  overview: (<><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></>),
  ask: (<><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /><path d="M8 9h8M8 13h5" /></>),
  layers: (<><path d="m12 2 10 5-10 5L2 7z" /><path d="m2 17 10 5 10-5" /><path d="m2 12 10 5 10-5" /></>),
  graph: (<><circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" /><path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4" /></>),
  api: (<><path d="M4 7h11M4 12h16M4 17h8" /><circle cx="18" cy="7" r="2" /><circle cx="15" cy="17" r="2" /></>),
  database: (<><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5" /><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></>),
  code: (<><path d="m16 18 6-6-6-6M8 6l-6 6 6 6" /></>),
  file: (<><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /></>),
  package: (<><path d="M21 8 12 3 3 8v8l9 5 9-5z" /><path d="m3 8 9 5 9-5M12 13v8" /></>),
  sun: (<><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>),
  moon: (<><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" /></>),
  monitor: (<><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" /></>),
  search: (<><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>),
  external: (<><path d="M15 3h6v6M10 14 21 3" /><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /></>),
  refresh: (<><path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5" /><path d="M21 12a9 9 0 0 1-15 6.7L3 16M8 16H3v5" /></>),
  sparkles: (<><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" /><path d="M19 16l.7 1.8L21.5 18.5l-1.8.7L19 21l-.7-1.8-1.8-.7 1.8-.7z" /></>),
  arrow: (<><path d="M5 12h14M13 6l6 6-6 6" /></>),
  check: (<><path d="M20 6 9 17l-5-5" /></>),
  book: (<><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z" /><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5" /></>),
  chevron: (<><path d="m9 6 6 6-6 6" /></>),
  fit: (<><path d="M3 8V5a2 2 0 0 1 2-2h3M16 3h3a2 2 0 0 1 2 2v3M21 16v3a2 2 0 0 1-2 2h-3M8 21H5a2 2 0 0 1-2-2v-3" /></>),
  alert: (<><circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" /></>),
  stop: (<><rect x="6" y="6" width="12" height="12" rx="2" /></>),
  send: (<><path d="M5 12h14M13 6l6 6-6 6" /></>),
};

export type IconName = keyof typeof ICONS;

export function Icon({ name, className = "h-4 w-4", ...rest }: { name: IconName } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`shrink-0 ${className}`}
      aria-hidden="true"
      {...rest}
    >
      {ICONS[name]}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Primitives
// ---------------------------------------------------------------------------

export function Card({ children, className = "", padded = true }: { children: ReactNode; className?: string; padded?: boolean }) {
  return (
    <div className={`rounded-2xl border border-line bg-surface shadow-card ${padded ? "p-6" : ""} ${className}`}>
      {children}
    </div>
  );
}

export function CardTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-4">
      <h3 className="text-[15px] font-semibold tracking-tight text-ink">{children}</h3>
      {aside && <div className="text-xs text-muted">{aside}</div>}
    </div>
  );
}

// Every repository view starts with this: what you're looking at, in one line.
export function PageHeader({ title, description, actions }: { title: string; description: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-2xl">
        <h2 className="text-xl font-semibold tracking-tight text-ink">{title}</h2>
        <p className="mt-1 text-sm leading-relaxed text-ink-2">{description}</p>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

const METHOD_TONE: Record<string, string> = {
  GET: "var(--layer-setup)",
  POST: "var(--layer-middleware)",
  PUT: "var(--layer-service)",
  PATCH: "var(--layer-service)",
  DELETE: "var(--danger)",
};

// Method as text in a neutral chip with a coloured rule: readable without colour.
export function MethodBadge({ method }: { method: string }) {
  return (
    <span
      className="inline-flex w-[62px] shrink-0 items-center justify-center rounded-md border border-line bg-sunken py-0.5 font-mono text-[11px] font-semibold tracking-wide text-ink"
      style={{ boxShadow: `inset 3px 0 0 ${METHOD_TONE[method] ?? "var(--muted)"}` }}
    >
      {method}
    </span>
  );
}

export function Chip({ children, tone = "neutral", className = "" }: { children: ReactNode; tone?: "neutral" | "accent" | "success" | "danger"; className?: string }) {
  const tones = {
    neutral: "border-line bg-sunken text-ink-2",
    accent: "border-transparent bg-accent-soft text-accent-text",
    success: "border-line bg-surface text-ink-2",
    danger: "border-transparent bg-danger-soft text-danger",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${tones[tone]} ${className}`}>
      {tone === "success" && <span className="h-1.5 w-1.5 rounded-full bg-success" />}
      {children}
    </span>
  );
}

export function Button({
  children,
  variant = "secondary",
  size = "md",
  className = "",
  ...rest
}: {
  children: ReactNode;
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md" | "lg";
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const variants = {
    primary: "bg-ink text-page hover:opacity-90 shadow-card",
    secondary: "border border-line bg-surface text-ink hover:bg-hover shadow-card",
    ghost: "text-ink-2 hover:bg-hover hover:text-ink",
  };
  const sizes = { sm: "h-8 px-3 text-xs", md: "h-9 px-3.5 text-sm", lg: "h-12 px-5 text-[15px]" };
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-lg font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${sizes[size]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

export function SearchInput({ value, onChange, placeholder, className = "" }: { value: string; onChange: (v: string) => void; placeholder: string; className?: string }) {
  return (
    <label className={`flex h-9 items-center gap-2 rounded-lg border border-line bg-surface px-3 text-sm shadow-card focus-within:border-line-strong ${className}`}>
      <Icon name="search" className="h-4 w-4 text-muted" />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="min-w-0 flex-1 bg-transparent text-ink outline-none placeholder:text-muted"
      />
    </label>
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="space-y-3 py-6" aria-busy="true">
      <div className="flex items-center gap-2 text-sm text-muted">
        <Spinner /> {label}
      </div>
      <div className="skeleton h-28 w-full" />
      <div className="grid grid-cols-3 gap-3">
        <div className="skeleton h-16" />
        <div className="skeleton h-16" />
        <div className="skeleton h-16" />
      </div>
    </div>
  );
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return (
    <div className="flex gap-3 rounded-xl border border-transparent bg-danger-soft px-4 py-3 text-sm text-danger">
      <Icon name="alert" className="mt-0.5 h-4 w-4" />
      <div>{children}</div>
    </div>
  );
}

export function Empty({ icon = "search", title, children }: { icon?: IconName; title: string; children?: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-line-strong bg-surface px-6 py-16 text-center">
      <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-sunken text-muted">
        <Icon name={icon} className="h-5 w-5" />
      </div>
      <p className="font-medium text-ink">{title}</p>
      {children && <div className="mx-auto mt-1.5 max-w-md text-sm text-ink-2">{children}</div>}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3.5 shadow-card" title={hint}>
      <div className="text-2xl font-semibold tracking-tight text-ink">{value}</div>
      <div className="mt-0.5 text-xs text-muted">{label}</div>
    </div>
  );
}

export function LayerDot({ raw, group, className = "h-2.5 w-2.5" }: { raw?: string; group?: LayerGroup; className?: string }) {
  return (
    <span
      className={`inline-block shrink-0 rounded-full ${className}`}
      style={{ background: group ? groupColor(group) : layerColor(raw) }}
    />
  );
}

export function frameworkLabel(framework: string | null | undefined): string {
  if (!framework) return "Unknown";
  const f = framework.toLowerCase();
  if (f === "nestjs") return "NestJS";
  if (f === "express") return "Express.js";
  return framework;
}

export function languageLabel(lang: string | null | undefined): string {
  if (!lang) return "";
  const l = lang.toLowerCase();
  if (l === "typescript") return "TypeScript";
  if (l === "javascript") return "JavaScript";
  return lang;
}

export function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}
