import { useFilterStore } from "../store/filterStore";

export default function Header({ className = "" }: { className?: string }) {
  const mode = useFilterStore((s) => s.mode);
  const set = useFilterStore((s) => s.set);
  return (
    <header className={`p-2 flex items-center gap-4 ${className}`}>
      <div className="font-semibold">ZTNA Flow Discovery</div>
      <div className="ml-auto flex gap-2 text-sm">
        <button
          className={`px-3 py-1 rounded ${
            mode === "live" ? "bg-okabe-sky text-black" : "bg-slate-800"
          }`}
          onClick={() => set({ mode: "live" })}
        >Live</button>
        <button
          className={`px-3 py-1 rounded ${
            mode === "historical" ? "bg-okabe-sky text-black" : "bg-slate-800"
          }`}
          onClick={() => set({ mode: "historical" })}
        >Historical</button>
      </div>
    </header>
  );
}
