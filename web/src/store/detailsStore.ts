import { create } from "zustand";

import type { NodeRight, SankeyLink } from "../api/types";

interface DetailsState {
  selectedLink: SankeyLink | null;
  selectedRight: NodeRight | null;
  overrideOpen: boolean;
  setLink: (l: SankeyLink | null) => void;
  setRight: (n: NodeRight | null) => void;
  openOverride: () => void;
  closeOverride: () => void;
}

export const useDetailsStore = create<DetailsState>((set) => ({
  selectedLink: null,
  selectedRight: null,
  overrideOpen: false,
  setLink: (l) => set({ selectedLink: l }),
  setRight: (n) => set({ selectedRight: n }),
  openOverride: () => set({ overrideOpen: true }),
  closeOverride: () => set({ overrideOpen: false }),
}));
