import { useEffect } from "react";

import { openSankeyStream } from "./api/ws";
import DetailsPane from "./components/DetailsPane";
import FiltersSidebar from "./components/FiltersSidebar";
import FreshnessBanner from "./components/FreshnessBanner";
import Header from "./components/Header";
import Sankey from "./components/Sankey";
import { useFilterStore } from "./store/filterStore";
import { useLiveStore } from "./store/liveStore";

export default function App() {
  useEffect(() => {
    const setDelta = useLiveStore.getState().setDelta;
    const setStatus = useLiveStore.getState().setStatus;
    const handle = openSankeyStream(setDelta, setStatus);
    const unsub = useFilterStore.subscribe((s) =>
      handle.updateFilters({
        src_cidr: s.src_cidr,
        dst_app: s.dst_app,
        proto: s.proto,
        deny_only: s.deny_only,
      })
    );
    return () => {
      handle.close();
      unsub();
    };
  }, []);

  return (
    <div className="grid h-screen grid-rows-[auto_1fr] grid-cols-[16rem_1fr]">
      <Header className="col-span-2 border-b border-slate-800" />
      <FiltersSidebar className="row-span-2 border-r border-slate-800" />
      <main className="flex flex-col min-h-0">
        <FreshnessBanner />
        <div className="flex-1 min-h-0"><Sankey /></div>
        <DetailsPane className="border-t border-slate-800 h-64" />
      </main>
    </div>
  );
}
