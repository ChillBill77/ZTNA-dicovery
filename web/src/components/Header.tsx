import LogoutButton from "../auth/LogoutButton";
import { useFilterStore } from "../store/filterStore";

import LeftColumnModeToggle from "./LeftColumnModeToggle";

export default function Header({
  className = "",
}: {
  className?: string;
}): JSX.Element {
  const mode = useFilterStore((s) => s.mode);
  const groupBy = useFilterStore((s) => s.group_by);
  const set = useFilterStore((s) => s.set);
  return (
    <header
      className={`p-2 flex items-center gap-4 ${className}`}
      data-testid="app-header"
    >
      <div className="font-semibold">ZTNA Flow Discovery</div>
      <LeftColumnModeToggle
        value={groupBy}
        onChange={(g) => set({ group_by: g })}
      />
      <div className="ml-auto flex items-center gap-3 text-sm">
        <div className="inline-flex rounded bg-slate-800 p-1">
          <button
            data-testid="mode-live"
            className={`px-3 py-1 rounded ${
              mode === "live" ? "bg-okabe-sky text-black" : "text-slate-300"
            }`}
            onClick={() => set({ mode: "live" })}
          >
            Live
          </button>
          <button
            data-testid="mode-historical"
            className={`px-3 py-1 rounded ${
              mode === "historical"
                ? "bg-okabe-sky text-black"
                : "text-slate-300"
            }`}
            onClick={() => set({ mode: "historical" })}
          >
            Historical
          </button>
        </div>
        <LogoutButton />
      </div>
    </header>
  );
}
