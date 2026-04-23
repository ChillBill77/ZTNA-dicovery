export interface NodeLeft { id: string; label: string; size: number }
export interface NodeRight { id: string; label: string; kind: string }
export interface SankeyLink {
  src: string; dst: string; bytes: number; flows: number; users: number;
}
export interface SankeyDelta {
  ts: string;
  window_s: number;
  nodes_left: NodeLeft[];
  nodes_right: NodeRight[];
  links: SankeyLink[];
  lossy: boolean;
  dropped_count: number;
  truncated?: boolean;
  total_links?: number | null;
}

export interface Application {
  id: number; name: string; description: string | null; owner: string | null;
  dst_cidr: string; dst_port_min: number | null; dst_port_max: number | null;
  proto: number | null; priority: number; source: string;
  created_at: string; updated_at: string; updated_by: string | null;
}
export interface ApplicationIn {
  name: string; description?: string | null; owner?: string | null;
  dst_cidr: string; dst_port_min?: number | null; dst_port_max?: number | null;
  proto?: number | null; priority?: number;
}

export interface SaasEntry {
  id: number; name: string; vendor: string | null;
  fqdn_pattern: string; category: string | null; priority: number; source: string;
}

export interface Problem { type?: string; title: string; detail?: string; status?: number }
