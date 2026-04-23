import { create } from "zustand";

import type { SankeyDelta } from "../api/types";

interface LiveState {
  latest: SankeyDelta | null;
  status: "open" | "closed" | "error";
  setDelta: (d: SankeyDelta) => void;
  setStatus: (s: LiveState["status"]) => void;
  secondsBehind: () => number;
}

export const useLiveStore = create<LiveState>((set, get) => ({
  latest: null,
  status: "closed",
  setDelta: (d) => set({ latest: d }),
  setStatus: (s) => set({ status: s }),
  secondsBehind: () => {
    const l = get().latest;
    if (!l) return Infinity;
    return Math.max(0, (Date.now() - new Date(l.ts).getTime()) / 1000);
  },
}));
