from __future__ import annotations

import inspect

from ztna_common.adapter_base import FlowAdapter, IdentityAdapter
from ztna_common.event_types import FlowEvent, IdentityEvent


def test_flow_adapter_has_required_abstract_methods() -> None:
    methods = {
        name
        for name, m in inspect.getmembers(FlowAdapter)
        if getattr(m, "__isabstractmethod__", False)
    }
    assert {"run", "healthcheck"} <= methods


def test_identity_adapter_has_required_abstract_methods() -> None:
    methods = {
        name
        for name, m in inspect.getmembers(IdentityAdapter)
        if getattr(m, "__isabstractmethod__", False)
    }
    assert {"run", "healthcheck"} <= methods


def test_identity_event_required_keys() -> None:
    required = {
        "ts",
        "src_ip",
        "user_upn",
        "source",
        "event_type",
        "confidence",
        "ttl_seconds",
    }
    assert required <= set(IdentityEvent.__required_keys__)


def test_flow_event_required_keys() -> None:
    required = {"ts", "src_ip", "dst_ip", "dst_port", "proto", "bytes", "packets", "source"}
    assert required <= set(FlowEvent.__required_keys__)
