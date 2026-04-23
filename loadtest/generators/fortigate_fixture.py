from __future__ import annotations

import random
import time


def fortigate_traffic_line() -> bytes:
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    src = f"10.1.{random.randint(1, 254)}.{random.randint(1, 254)}"
    dst = f"198.51.{random.randint(1, 254)}.{random.randint(1, 254)}"
    port = random.choice([443, 80, 22])
    return (
        f"<134>date={ts} devname=fw02 type=traffic subtype=forward "
        f"status=close srcip={src} dstip={dst} dstport={port} "
        f"proto=6 sentbyte={random.randint(100, 40000)} "
        f"rcvdbyte={random.randint(100, 40000)} app=HTTPS.WEB\n"
    ).encode()
