import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { openSankeyStream } from "./api/ws";
import AuthProvider from "./auth/AuthProvider";
import DetailsPane from "./components/DetailsPane";
import FiltersSidebar from "./components/FiltersSidebar";
import FreshnessBanner from "./components/FreshnessBanner";
import GroupMembersModal from "./components/GroupMembersModal";
import Header from "./components/Header";
import Sankey from "./components/Sankey";
import UnknownStrandBanner from "./components/UnknownStrandBanner";
import { useFilterStore } from "./store/filterStore";
import { useLiveStore } from "./store/liveStore";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
});

function AppShell(): JSX.Element {
  const [openGroupId, setOpenGroupId] = useState<string | null>(null);
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
        group_by: s.group_by,
        group: s.group,
        user: s.user,
        exclude_groups: s.exclude_groups,
      }),
    );
    return () => {
      handle.close();
      unsub();
    };
  }, []);

  // Listen for left-node clicks dispatched by the Sankey component (custom
  // event keeps SVG/canvas wiring out of the global store).
  useEffect(() => {
    function _open(e: Event): void {
      const ce = e as CustomEvent<{ groupId: string }>;
      if (ce.detail?.groupId) setOpenGroupId(ce.detail.groupId);
    }
    window.addEventListener("ztna:open-group", _open as EventListener);
    return () =>
      window.removeEventListener("ztna:open-group", _open as EventListener);
  }, []);

  return (
    <div className="grid h-screen grid-rows-[auto_1fr] grid-cols-[16rem_1fr]">
      <Header className="col-span-2 border-b border-slate-800" />
      <FiltersSidebar className="row-span-2 border-r border-slate-800" />
      <main className="flex flex-col min-h-0">
        <UnknownStrandBanner />
        <FreshnessBanner />
        <div className="flex-1 min-h-0">
          <Sankey />
        </div>
        <DetailsPane className="border-t border-slate-800 h-64" />
      </main>
      <GroupMembersModal
        groupId={openGroupId}
        onClose={() => setOpenGroupId(null)}
      />
    </div>
  );
}

export default function App(): JSX.Element {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <AppShell />
      </AuthProvider>
    </QueryClientProvider>
  );
}
