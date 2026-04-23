from __future__ import annotations

import random


def ise_accounting_line() -> bytes:
    ip = f"10.3.{random.randint(1, 254)}.{random.randint(1, 254)}"
    return (
        f"<14>CISE_RADIUS_Accounting Acct-Status-Type=Start "
        f"User-Name=svc{random.randint(1, 10)}@example.com "
        f"Framed-IP-Address={ip}\n"
    ).encode()
