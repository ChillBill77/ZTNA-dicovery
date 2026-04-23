"""Locust entry — scenario picked via env var ``LOAD_SCENARIO``.

Each User subclass opens raw UDP sockets to Traefik's syslog entrypoints and
fires synthetic lines. The HTTP target on ``--host`` is ignored by these
tasks but required by Locust's startup.
"""

from __future__ import annotations

import os
import socket

from locust import User, between, events, task

from loadtest.generators.ad_4624_fixture import ad_4624_line
from loadtest.generators.fortigate_fixture import fortigate_traffic_line
from loadtest.generators.ise_fixture import ise_accounting_line
from loadtest.generators.pan_fixture import pan_traffic_line

SYSLOG_HOST = os.getenv("SYSLOG_HOST", "traefik")
FIREWALL_PORT = int(os.getenv("FIREWALL_PORT", "514"))
AD_PORT = int(os.getenv("AD_PORT", "516"))
ISE_PORT = int(os.getenv("ISE_PORT", "517"))
SCENARIO = os.getenv("LOAD_SCENARIO", "sustained")


class _UdpClient:
    def __init__(self, host: str, port: int) -> None:
        self._addr = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, payload: bytes) -> None:
        self._sock.sendto(payload, self._addr)


class FlowSender(User):
    wait_time = between(0, 0)

    def on_start(self) -> None:
        self.client_pan = _UdpClient(SYSLOG_HOST, FIREWALL_PORT)
        self.client_fgt = _UdpClient(SYSLOG_HOST, FIREWALL_PORT)

    @task(2)
    def pan(self) -> None:
        self.client_pan.send(pan_traffic_line())

    @task(1)
    def fortigate(self) -> None:
        self.client_fgt.send(fortigate_traffic_line())


class IdentitySender(User):
    wait_time = between(0, 0)

    def on_start(self) -> None:
        self.client_ad = _UdpClient(SYSLOG_HOST, AD_PORT)
        self.client_ise = _UdpClient(SYSLOG_HOST, ISE_PORT)

    @task(1)
    def ad(self) -> None:
        self.client_ad.send(ad_4624_line())

    @task(1)
    def ise(self) -> None:
        self.client_ise.send(ise_accounting_line())


@events.test_start.add_listener
def _announce(environment: object, **_kwargs: object) -> None:
    print(f"Load test scenario={SCENARIO} host={SYSLOG_HOST}")
