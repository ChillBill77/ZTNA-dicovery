from __future__ import annotations

# Backwards-compatible re-export: FlowAdapter and FlowEvent now live in the
# shared ``ztna_common`` package so id-ingest can subclass the same ABC.
from ztna_common.adapter_base import FlowAdapter
from ztna_common.event_types import FlowEvent

__all__ = ["FlowAdapter", "FlowEvent"]
