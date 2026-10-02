import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type FileEntry } from "../../lib/product";
import { useRepo } from "../RepoLayout";
import CodeView from "../CodeView";
import { ErrorBox, LAYER_COLORS, LAYER_LABELS, Loading } from "../ui";

interface Dir {
  name: string;
  path: string;
  dirs: Map<string, Dir>;
  files: FileEntry[];
}

function buildTree(files: FileEntry[]): Dir {
  const root: Dir = { name: "", path: "", dirs: new Map(), files: [] };
  for (const f of files) {
    const parts = f.path.split("/");
    let node = root;
    for (const part of parts.slice(0, -1)) {
      const path = node.path ? `${node.path}/${part}` : part;
      if (!node.dirs.has(part)) node.dirs.set(part, { name: part, path, dirs: new Map(), files: [] });
      node = node.dirs.get(part)!;
    }
    node.files.push(f);
  }
  return root;
}

export default function FilesTab() {
  const { analysis } = useRepo();
  const [params, setParams] = useSearchParams();
  const [files, setFiles] = useState<FileEntry[] | null>(null);
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const selected = params.get("path");
  const line = params.get("line") ? Number(params.get("line")) : null;

  useEffect(() => {
    api.files(analysis.id).then(setFiles).catch((e) => setError(String(e.message ?? e)));
  }, [analysis.id]);

  useEffect(() => {
    if (!files || selected) return;
    const first = files.find((f) => /(^|\/)(main|app|index|server)\.[jt]s$/.test(f.path) && f.layer === "entry") ?? files[0];
    if (first) setParams({ path: first.path }, { replace: true });
  }, [files, selected, setParams]);

  useEffect(() => {
    if (!selected) return;
    setContent(null);
    api.file(analysis.id, selected).then((f) => setContent(f.content)).catch(() => setContent(""));
  }, [analysis.id, selected]);

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return (files ?? []).filter((f) => !q || f.path.toLowerCase().includes(q));
  }, [files, filter]);
  const tree = useMemo(() => buildTree(shown), [shown]);

  if (error) return <ErrorBox>{error}</ErrorBox>;
  if (!files) return <Loading />;
  const current = files.find((f) => f.path === selected);

  return (
    <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
      <aside className="rounded-xl border border-slate-200 p-2 dark:border-slate-800">
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={`Filter ${files.length} files…`}
          className="mb-2 w-full rounded-md border border-slate-300 px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-900"
        />
        <div className="max-h-[70vh] overflow-y-auto text-sm">
          <TreeNode dir={tree} depth={0} selected={selected} onSelect={(p) => setParams({ path: p })} forceOpen={!!filter} />
        </div>
      </aside>
      <section className="min-w-0">
        {current && (
          <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
            <span className="font-mono text-sm text-slate-800 dark:text-slate-200">{current.path}</span>
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-sm" style={{ background: LAYER_COLORS[current.layer] }} />
              {LAYER_LABELS[current.layer] ?? current.layer}
            </span>
            <span>imports {current.imports}</span>
            <span>imported by {current.imported_by}</span>
            {current.classes.length > 0 && <span className="font-mono">{current.classes.join(", ")}</span>}
          </div>
        )}
        {selected && content !== null ? (
          <CodeView path={selected} content={content} focusLine={line} />
        ) : (
          <Loading />
        )}
      </section>
    </div>
  );
}

function TreeNode({
  dir,
  depth,
  selected,
  onSelect,
  forceOpen,
}: {
  dir: Dir;
  depth: number;
  selected: string | null;
  onSelect: (path: string) => void;
  forceOpen: boolean;
}) {
  const containsSelected = !!selected && (dir.path === "" || selected.startsWith(dir.path + "/"));
  const [open, setOpen] = useState(depth < 1 || containsSelected);
  const isOpen = open || forceOpen;
  const dirs = [...dir.dirs.values()].sort((a, b) => a.name.localeCompare(b.name));

  return (
    <div>
      {dir.name && (
        <button
          onClick={() => setOpen(!open)}
          className="flex w-full items-center gap-1 rounded px-1 py-0.5 text-left text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          style={{ paddingLeft: depth * 12 }}
        >
          <span className="w-3 text-[10px] text-slate-400">{isOpen ? "▾" : "▸"}</span>
          {dir.name}
        </button>
      )}
      {isOpen && (
        <>
          {dirs.map((d) => (
            <TreeNode key={d.path} dir={d} depth={depth + (dir.name ? 1 : 0)} selected={selected} onSelect={onSelect} forceOpen={forceOpen} />
          ))}
          {dir.files
            .slice()
            .sort((a, b) => a.path.localeCompare(b.path))
            .map((f) => (
              <button
                key={f.path}
                onClick={() => onSelect(f.path)}
                className={`flex w-full items-center gap-1.5 truncate rounded px-1 py-0.5 text-left font-mono text-xs ${
                  f.path === selected
                    ? "bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-200"
                    : "hover:bg-slate-100 dark:hover:bg-slate-800"
                }`}
                style={{ paddingLeft: (depth + (dir.name ? 1 : 0)) * 12 + 4 }}
                title={f.path}
              >
                <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: LAYER_COLORS[f.layer] }} />
                <span className="truncate">{f.path.split("/").pop()}</span>
              </button>
            ))}
        </>
      )}
    </div>
  );
}
