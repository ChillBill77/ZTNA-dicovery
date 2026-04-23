from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass(frozen=True)
class CursorPayload:
    last_time: datetime
    last_src_ip: str
    last_dst_ip: str
    last_dst_port: int


def encode_cursor(payload: CursorPayload) -> str:
    data = asdict(payload)
    data["last_time"] = payload.last_time.isoformat()
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode_cursor(token: str) -> CursorPayload:
    padded = token + "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode())
        d = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("malformed cursor") from exc
    if not {"last_time", "last_src_ip", "last_dst_ip", "last_dst_port"} <= d.keys():
        raise ValueError("cursor missing required fields")
    return CursorPayload(
        last_time=datetime.fromisoformat(d["last_time"]),
        last_src_ip=str(d["last_src_ip"]),
        last_dst_ip=str(d["last_dst_ip"]),
        last_dst_port=int(d["last_dst_port"]),
    )
