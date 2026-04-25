import { useQuery, useQueryClient } from "@tanstack/react-query";

export type Role = "viewer" | "editor" | "admin";

export interface Me {
  user_upn: string;
  roles: Role[];
}

/** Fetch the current user once + cache for a minute. Returns null when the
 *  api responds 401 (no session) so callers can route to the login page. */
export function useAuth(): {
  me: Me | null;
  loading: boolean;
  refetch: () => void;
} {
  const qc = useQueryClient();
  const q = useQuery<Me | null>({
    queryKey: ["auth", "me"],
    queryFn: async () => {
      const r = await fetch("/api/auth/me", { credentials: "include" });
      if (r.status === 401) return null;
      if (!r.ok) throw new Error(`me failed: ${r.status}`);
      return (await r.json()) as Me;
    },
    staleTime: 60_000,
    retry: false,
  });
  return {
    me: q.data ?? null,
    loading: q.isLoading,
    refetch: () => qc.invalidateQueries({ queryKey: ["auth", "me"] }),
  };
}
