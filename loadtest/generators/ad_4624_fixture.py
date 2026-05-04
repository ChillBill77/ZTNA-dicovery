from __future__ import annotations

import random


def ad_4624_line() -> bytes:
    ip = f"10.2.{random.randint(1, 254)}.{random.randint(1, 254)}"
    upn = random.choice(["alice@example.com", "bob@example.com", "carol@example.com"])
    logon_type = random.choice([2, 3, 10])
    return (
        f"<14>EventID=4624 TargetUserName={upn} IpAddress={ip} LogonType={logon_type}\n"
    ).encode()
