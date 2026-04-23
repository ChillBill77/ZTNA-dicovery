from __future__ import annotations

from datetime import datetime
from typing import TypedDict


class FlowEvent(TypedDict):
    ts: datetime
    src_ip: str
    src_port: int
    dst_ip: str
    dst_port: int
    proto: int
    bytes: int
    packets: int
    action: str  # 'allow' | 'deny' | 'drop'
    fqdn: str | None  # firewall-supplied hostname
    app_id: str | None  # vendor App-ID
    source: str  # adapter name, e.g. 'palo_alto'
    raw_id: str | None


class IdentityEvent(TypedDict):
    ts: datetime
    src_ip: str
    user_upn: str
    source: str
    event_type: str  # 'logon' | 'nac-auth' | 'nac-auth-stop' | 'dhcp'
    confidence: int  # 0-100
    ttl_seconds: int
    mac: str | None
    raw_id: str | None
