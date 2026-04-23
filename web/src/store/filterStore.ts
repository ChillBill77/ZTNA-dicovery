import { create } from "zustand";

export interface Filters {
  mode: "live" | "historical";
  src_cidr?: string;
  dst_app?: string;
  category?: string;
  proto?: number;
  deny_only?: boolean;
  range?: { from: string; to: string };
}

interface FilterState extends Filters {
  set: (patch: Partial<Filters>) => void;
  reset: () => void;
}

export const useFilterStore = create<FilterState>((set) => ({
  mode: "live",
  set: (patch) => set(patch),
  reset: () => set({
    mode: "live", src_cidr: undefined, dst_app: undefined,
    category: undefined, proto: undefined, deny_only: false, range: undefined,
  }),
}));
