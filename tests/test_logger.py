# tests/test_logger.py
import json
import logging
import pytest
from pathlib import Path
from notifier.logger import get_logger


def test_logger_writes_json_line(tmp_path):
    log_file = tmp_path / "test.log"
    logger = get_logger("test", str(log_file))
    logger.info("order placed", extra={"symbol": "BTC/USDT", "order_id": "ord-001"})

    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["message"] == "order placed"
    assert record["symbol"] == "BTC/USDT"
    assert record["level"] == "INFO"


def test_logger_includes_module_name(tmp_path):
    log_file = tmp_path / "test2.log"
    logger = get_logger("engine", str(log_file))
    logger.warning("risk limit hit")

    lines = log_file.read_text().strip().splitlines()
    record = json.loads(lines[0])
    assert record["level"] == "WARNING"
    assert "timestamp" in record
