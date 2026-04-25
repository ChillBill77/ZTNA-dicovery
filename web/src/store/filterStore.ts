import { create } from "zustand";

export type GroupBy = "group" | "user" | "src_ip";

export interface Filters {
  mode: "live" | "historical";
  group_by: GroupBy;
  src_cidr?: string;
  dst_app?: string;
  category?: string;
  proto?: number;
  deny_only?: boolean;
  range?: { from: string; to: string };
  /** Multi-select of group ids/names to include. */
  group?: string[];
  /** Restrict to a specific user UPN. */
  user?: string;
  /** CSV of group labels to drop from the left column. */
  exclude_groups?: string;
}

interface FilterState extends Filters {
  set: (patch: Partial<Filters>) => void;
  reset: () => void;
}

export const useFilterStore = create<FilterState>((set) => ({
  mode: "live",
  group_by: "group",
  set: (patch) => set(patch),
  reset: () =>
    set({
      mode: "live",
      group_by: "group",
      src_cidr: undefined,
      dst_app: undefined,
      category: undefined,
      proto: undefined,
      deny_only: false,
      range: undefined,
      group: undefined,
      user: undefined,
      exclude_groups: undefined,
    }),
}));
