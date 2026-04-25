import type { SankeyDelta } from "./types";

export type WSFilter = Partial<{
  src_cidr: string; dst_app: string; proto: number; deny_only: boolean;
  group_by: "group" | "user" | "src_ip";
  group: string[];
  user: string;
  exclude_groups: string;
}>;

export interface SankeyStreamHandle {
  updateFilters(f: WSFilter): void;
  close(): void;
}

export function openSankeyStream(
  onMessage: (d: SankeyDelta) => void,
  onStatus: (s: "open" | "closed" | "error") => void,
): SankeyStreamHandle {
  let ws: WebSocket | null = null;
  let closed = false;
  let currentFilter: WSFilter = {};
  let backoffMs = 500;

  const connect = () => {
    if (closed) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws/sankey`);
    ws.onopen = () => {
      backoffMs = 500;
      onStatus("open");
      ws!.send(JSON.stringify({ filter: currentFilter }));
    };
    ws.onmessage = (e) => {
      try { onMessage(JSON.parse(e.data) as SankeyDelta); } catch { /* ignore */ }
    };
    ws.onerror = () => onStatus("error");
    ws.onclose = () => {
      onStatus("closed");
      setTimeout(connect, backoffMs);
      backoffMs = Math.min(backoffMs * 2, 10_000);
    };
  };
  connect();

  return {
    updateFilters(f) {
      currentFilter = f;
      if (ws?.readyState === 1) ws.send(JSON.stringify({ filter: f }));
    },
    close() { closed = true; ws?.close(); },
  };
}
