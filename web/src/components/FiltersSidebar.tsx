import { useFilterStore } from "../store/filterStore";

export default function FiltersSidebar({ className = "" }: { className?: string }) {
  const f = useFilterStore();
  return (
    <aside className={`p-3 space-y-3 text-sm ${className}`}>
      <h2 className="font-semibold">Filters</h2>
      <label className="block">
        <span className="block text-slate-400">Source CIDR</span>
        <input
          className="mt-1 w-full bg-slate-800 px-2 py-1 rounded"
          placeholder="10.0.0.0/8"
          value={f.src_cidr ?? ""}
          onChange={(e) => f.set({ src_cidr: e.target.value || undefined })}
          aria-label="source-cidr"
        />
      </label>
      <label className="block">
        <span className="block text-slate-400">Destination app</span>
        <input
          className="mt-1 w-full bg-slate-800 px-2 py-1 rounded"
          value={f.dst_app ?? ""}
          onChange={(e) => f.set({ dst_app: e.target.value || undefined })}
          aria-label="dst-app"
        />
      </label>
      <label className="flex items-center gap-2">
        <input
          type="checkbox" checked={!!f.deny_only}
          onChange={(e) => f.set({ deny_only: e.target.checked })}
        />
        <span>Deny only</span>
      </label>
      <button onClick={() => f.reset()} className="mt-2 px-2 py-1 bg-slate-700 rounded">
        Reset
      </button>
    </aside>
  );
}
