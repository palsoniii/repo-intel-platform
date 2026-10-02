import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type FileEntry } from "../../lib/product";
import { useRepo } from "../RepoLayout";
import CodeView from "../CodeView";
import CodeSwitcher from "../CodeSwitcher";
import { ErrorBox, Icon, LayerDot, Loading, PageHeader, SearchInput, groupLabel, layerGroup } from "../ui";

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
    const first = files.find((f) => f.layer === "entry") ?? files[0];
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
    <div>
      <PageHeader
        title="Source code"
        description="Browse the files the analysis read. The dot beside each file shows its layer."
        actions={<CodeSwitcher />}
      />
      <div className="grid gap-4 lg:grid-cols-[290px_1fr]">
        <aside className="rounded-2xl border border-line bg-surface p-2 shadow-card">
          <SearchInput value={filter} onChange={setFilter} placeholder={`Search ${files.length} files`} className="mb-2 shadow-none" />
          <div className="scroll-quiet max-h-[68vh] overflow-y-auto pb-1 text-sm">
            <TreeNode dir={tree} depth={0} selected={selected} onSelect={(p) => setParams({ path: p })} forceOpen={!!filter} />
          </div>
        </aside>
        <section className="min-w-0">
          {current && (
            <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-xl border border-line bg-surface px-4 py-2.5 text-xs text-ink-2 shadow-card">
              <span className="font-mono text-[13px] font-medium text-ink">{current.path}</span>
              <span className="flex items-center gap-1.5">
                <LayerDot raw={current.layer} className="h-2 w-2" /> {groupLabel(layerGroup(current.layer))}
              </span>
              <span className="text-muted">imports {current.imports}</span>
              <span className="text-muted">used by {current.imported_by}</span>
              {current.classes.length > 0 && <span className="truncate font-mono text-muted">{current.classes.join(", ")}</span>}
            </div>
          )}
          {selected && content !== null ? <CodeView path={selected} content={content} focusLine={line} /> : <Loading />}
        </section>
      </div>
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
  const childDepth = depth + (dir.name ? 1 : 0);

  return (
    <div>
      {dir.name && (
        <button
          onClick={() => setOpen(!open)}
          className="flex w-full items-center gap-1.5 rounded-md py-1 pr-2 text-left text-[13px] text-ink-2 transition hover:bg-hover hover:text-ink"
          style={{ paddingLeft: depth * 14 + 6 }}
        >
          <Icon name="chevron" className={`h-3 w-3 text-muted transition ${isOpen ? "rotate-90" : ""}`} />
          {dir.name}
        </button>
      )}
      {isOpen && (
        <>
          {dirs.map((d) => (
            <TreeNode key={d.path} dir={d} depth={childDepth} selected={selected} onSelect={onSelect} forceOpen={forceOpen} />
          ))}
          {dir.files
            .slice()
            .sort((a, b) => a.path.localeCompare(b.path))
            .map((f) => {
              const active = f.path === selected;
              return (
                <button
                  key={f.path}
                  onClick={() => onSelect(f.path)}
                  className={`flex w-full items-center gap-2 truncate rounded-md py-1 pr-2 text-left font-mono text-xs transition ${
                    active ? "bg-accent-soft text-accent-text" : "text-ink hover:bg-hover"
                  }`}
                  style={{ paddingLeft: childDepth * 14 + 8 }}
                  title={f.path}
                >
                  <LayerDot raw={f.layer} className="h-1.5 w-1.5" />
                  <span className="truncate">{f.path.split("/").pop()}</span>
                </button>
              );
            })}
        </>
      )}
    </div>
  );
}
