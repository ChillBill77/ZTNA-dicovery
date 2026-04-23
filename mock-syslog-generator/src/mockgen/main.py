from __future__ import annotations

import asyncio
import random
import socket

from loguru import logger
from pydantic_settings import BaseSettings, SettingsConfigDict

from mockgen.templates import fgt_line, pan_line


class MockSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    mockgen_target_host: str = "traefik"
    mockgen_target_port: int = 514
    mockgen_rate_per_s: int = 100
    mockgen_vendors: str = "palo_alto,fortigate"


async def _run(s: MockSettings) -> None:
    vendors = [v.strip() for v in s.mockgen_vendors.split(",") if v.strip()]
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    interval = 1.0 / max(1, s.mockgen_rate_per_s)

    logger.info(
        "mock syslog generator: {} vendors at {} qps → {}:{}",
        vendors,
        s.mockgen_rate_per_s,
        s.mockgen_target_host,
        s.mockgen_target_port,
    )
    while True:
        v = random.choice(vendors)
        line = (pan_line() if v == "palo_alto" else fgt_line()) + "\n"
        try:
            sock.sendto(line.encode(), (s.mockgen_target_host, s.mockgen_target_port))
        except OSError as exc:
            logger.warning("mockgen send failed: {}", exc)
            await asyncio.sleep(1)
        await asyncio.sleep(interval)


def main() -> None:
    asyncio.run(_run(MockSettings()))


if __name__ == "__main__":
    main()
