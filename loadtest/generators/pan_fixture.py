from __future__ import annotations

import random
import time


def _rand_ip(prefix: str) -> str:
    return f"{prefix}.{random.randint(1, 254)}.{random.randint(1, 254)}"


def pan_traffic_line(now: float | None = None) -> bytes:
    """Minimal Palo Alto TRAFFIC syslog CSV line (log_subtype=end)."""

    t = time.gmtime(now or time.time())
    ts = time.strftime("%Y/%m/%d %H:%M:%S", t)
    src = _rand_ip("10.0")
    dst = _rand_ip("203.0")
    port = random.choice([443, 53, 8080])
    bytes_ = random.randint(100, 50_000)
    return (
        f"<14>{ts} FW01 1,2026/04/22 10:00:00,001,TRAFFIC,end,"
        f"1,2026/04/22 10:00:00,{src},{dst},0.0.0.0,0.0.0.0,rule1,user,"
        f"app,vsys1,trust,untrust,ethernet1/1,ethernet1/2,Logs,{ts},"
        f"12345,1,12345,{port},0,0,0x0,tcp,allow,{bytes_},{bytes_ // 2},"
        f"{bytes_ // 2},10,{ts},0,any,0,1,0x0,US,US,,0,0\n"
    ).encode()
