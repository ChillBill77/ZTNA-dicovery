from __future__ import annotations

import json
import sys

import pytest
from api.logging_config import configure_logging, set_trace_id
from loguru import logger


@pytest.fixture(autouse=True)
def _reset_logger() -> None:
    """Each test reconfigures loguru fresh — previous `logger.add` sinks stay
    unless we ``logger.remove()`` between cases."""

    yield
    logger.remove()


def test_info_log_hashes_upn_and_ip(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    logger.bind(upn="alice@example.com", src_ip="10.0.0.1").info("flow observed")
    sys.stderr.flush()
    out = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(out)
    assert record["record"]["extra"]["upn"].startswith("sha256:")
    assert record["record"]["extra"]["src_ip"].startswith("sha256:")
    assert record["record"]["extra"]["upn"] != "alice@example.com"


def test_debug_log_keeps_raw_pii(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("DEBUG")
    logger.bind(upn="alice@example.com", src_ip="10.0.0.1").debug("flow observed")
    sys.stderr.flush()
    out = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(out)
    assert record["record"]["extra"]["upn"] == "alice@example.com"
    assert record["record"]["extra"]["src_ip"] == "10.0.0.1"


def test_trace_id_propagated(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    set_trace_id("00-abcdef1234567890abcdef1234567890-1111111111111111-01")
    logger.info("with trace")
    sys.stderr.flush()
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["record"]["extra"]["trace_id"] == "abcdef1234567890abcdef1234567890"
