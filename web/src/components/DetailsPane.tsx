import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { SankeyLink } from "../api/types";
import { useDetailsStore } from "../store/detailsStore";

import OverrideModal from "./OverrideModal";

interface RawFlowRow {
  time: string;
  src_ip: string;
  dst_ip: string;
  dst_port: number;
  bytes: number;
}

export default function DetailsPane({ className = "" }: { className?: string }) {
  const link = useDetailsStore((s) => s.selectedLink);
  const overrideOpen = useDetailsStore((s) => s.overrideOpen);
  const openOverride = useDetailsStore((s) => s.openOverride);
  const closeOverride = useDetailsStore((s) => s.closeOverride);

  return (
    <section
      className={`p-3 ${className} overflow-auto`}
      aria-label="details"
      data-testid="details-pane"
    >
      {link ? (
        <LinkTab link={link} openOverride={openOverride} />
      ) : (
        <p className="text-slate-500">Click a link to see details</p>
      )}
      {overrideOpen && <OverrideModal onClose={closeOverride} />}
    </section>
  );
}

function LinkTab({ link, openOverride }: { link: SankeyLink; openOverride: () => void }) {
  const src_ip = link.src.replace("ip:", "");
  const dst_app = link.dst.replace("app:", "");
  const { data } = useQuery({
    queryKey: ["raw", src_ip],
    queryFn: () =>
      api<{ items: RawFlowRow[] }>(`/api/flows/raw?src_ip=${src_ip}&limit=10`),
  });
  return (
    <div>
      <h3 className="font-semibold">{src_ip} → {dst_app}</h3>
      <p className="text-sm text-slate-400">
        {link.bytes.toLocaleString()} bytes, {link.flows} flows
      </p>
      <button
        className="mt-2 px-2 py-1 bg-slate-700 rounded"
        onClick={openOverride}
      >Override label</button>
      <ul className="mt-2 text-xs font-mono space-y-1" aria-label="raw-flows">
        {data?.items.map((row, i) => (
          <li key={i}>
            {row.time} {row.src_ip} → {row.dst_ip}:{row.dst_port} {row.bytes}B
          </li>
        ))}
      </ul>
    </div>
  );
}
