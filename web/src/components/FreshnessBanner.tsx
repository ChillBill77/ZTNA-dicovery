import { useLiveStore } from "../store/liveStore";

export default function FreshnessBanner() {
  const latest = useLiveStore((s) => s.latest);
  const status = useLiveStore((s) => s.status);
  const secs = latest ? Math.round(useLiveStore.getState().secondsBehind()) : Infinity;

  let tone = "green";
  if (!latest) tone = "gray";
  else if (latest.lossy || secs > 30) tone = "amber";
  if (secs > 60) tone = "red";

  const tint: Record<string, string> = {
    green: "bg-green-900/30 text-green-200",
    amber: "bg-amber-900/40 text-amber-200",
    red: "bg-red-900/40 text-red-200",
    gray: "bg-slate-800/50 text-slate-300",
  };

  return (
    <div
      role="status"
      data-testid="freshness"
      className={`px-3 py-1 text-xs ${tint[tone]} ${tone}`}
    >
      {status === "open" ? "Live" : status === "closed" ? "Reconnecting" : "Error"}
      {" · "}
      {secs === Infinity ? "no data" : `${secs}s behind`}
      {latest?.lossy ? " · lossy window (under-counting)" : ""}
    </div>
  );
}
