import { sankey as d3sankey, sankeyLinkHorizontal } from "d3-sankey";
import { useMemo } from "react";

import type { SankeyDelta } from "../api/types";
import { colourForLink, opacityFor } from "../lib/theme";
import { useDetailsStore } from "../store/detailsStore";
import { useLiveStore } from "../store/liveStore";
import SankeyCanvas from "./SankeyCanvas";

const SVG_LIMIT = 500;

export default function Sankey() {
  const delta = useLiveStore((s) => s.latest);
  if (!delta) {
    return (
      <div
        className="grid h-full place-items-center text-slate-500"
        data-testid="sankey-canvas"
      >
        awaiting flows…
      </div>
    );
  }
  if (delta.links.length > SVG_LIMIT) return <SankeyCanvas delta={delta} />;
  return <SvgSankey delta={delta} />;
}

interface D3Node {
  id: string;
  label: string;
  x0?: number;
  x1?: number;
  y0?: number;
  y1?: number;
}

interface D3Link {
  source: string | D3Node;
  target: string | D3Node;
  value: number;
  width?: number;
  src: string;
  dst: string;
  bytes: number;
  flows: number;
  users: number;
}

function SvgSankey({ delta }: { delta: SankeyDelta }) {
  const setLink = useDetailsStore((s) => s.setLink);
  const { nodes, links } = useMemo(() => {
    const width = 960;
    const height = 540;
    const layout = d3sankey<D3Node, D3Link>()
      .nodeId((n) => n.id)
      .nodeWidth(12)
      .nodePadding(10)
      .size([width, height]);
    const nodeList: D3Node[] = [...delta.nodes_left, ...delta.nodes_right].map(
      (n) => ({ id: n.id, label: n.label })
    );
    const linkList: D3Link[] = delta.links.map((l) => ({
      source: l.src, target: l.dst, value: l.bytes,
      src: l.src, dst: l.dst, bytes: l.bytes, flows: l.flows, users: l.users,
    }));
    return layout({ nodes: nodeList, links: linkList });
  }, [delta]);

  const maxBytes = Math.max(1, ...delta.links.map((l) => l.bytes));
  const path = sankeyLinkHorizontal<D3Node, D3Link>();

  return (
    <svg viewBox="0 0 960 540" className="w-full h-full" data-testid="sankey-canvas">
      {links.map((l, i) => {
        const src = typeof l.source === "object" ? l.source.id : String(l.source);
        const dst = typeof l.target === "object" ? l.target.id : String(l.target);
        return (
          <path
            key={`${src}->${dst}-${i}`}
            className="sankey-link"
            data-testid="sankey-link"
            d={path(l) ?? undefined}
            fill="none"
            stroke={colourForLink(i)}
            strokeOpacity={opacityFor(l.value, maxBytes)}
            strokeWidth={Math.max(1, l.width ?? 1)}
            tabIndex={0}
            role="button"
            aria-label={`${src} to ${dst}, ${l.value} bytes`}
            onClick={() => setLink({
              src, dst, bytes: l.bytes, flows: l.flows, users: l.users,
            })}
          />
        );
      })}
      {nodes.map((n) => (
        <g key={n.id} transform={`translate(${n.x0 ?? 0},${n.y0 ?? 0})`}>
          <rect
            width={(n.x1 ?? 0) - (n.x0 ?? 0)}
            height={Math.max(1, (n.y1 ?? 0) - (n.y0 ?? 0))}
            fill="#94a3b8"
          />
          <text
            x={-4}
            y={((n.y1 ?? 0) - (n.y0 ?? 0)) / 2}
            textAnchor="end"
            dy="0.35em"
            className="fill-slate-200 text-[10px]"
          >{n.label}</text>
        </g>
      ))}
    </svg>
  );
}
