import { useQuery } from "@tanstack/react-query";

interface Stats {
  unknown_user_ratio?: number;
  group_sync_age_seconds?: number | null;
}

const ALERT_THRESHOLD = 0.5;

/** Amber banner shown when too many flows lack identity binding. */
export default function UnknownStrandBanner(): JSX.Element | null {
  const { data } = useQuery<Stats>({
    queryKey: ["stats"],
    queryFn: async () => {
      const r = await fetch("/api/stats", { credentials: "include" });
      if (!r.ok) throw new Error(`stats failed: ${r.status}`);
      return (await r.json()) as Stats;
    },
    refetchInterval: 5_000,
  });
  const ratio = data?.unknown_user_ratio ?? 0;
  if (ratio < ALERT_THRESHOLD) return null;
  return (
    <div
      role="alert"
      data-testid="unknown-banner"
      className="bg-amber-900/40 border-b border-amber-700 text-amber-100 px-4 py-2 text-sm"
    >
      <strong>Identity coverage low.</strong>{" "}
      {Math.round(ratio * 100)}% of recent flows have no resolved user.
      Check identity sources (AD, Entra, ISE, ClearPass) — see{" "}
      <code>/api/adapters</code>.
    </div>
  );
}
