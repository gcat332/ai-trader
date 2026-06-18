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


def test_logger_serializes_exception_args_without_logging_error(tmp_path):
    log_file = tmp_path / "test3.log"
    logger = get_logger("supervisor-test", str(log_file))

    logger.error("Supervised task %s failed: %s", "api", RuntimeError("boom"))

    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["message"] == "Supervised task api failed: boom"
    assert record["level"] == "ERROR"


def test_logger_serializes_non_json_extra_fields(tmp_path):
    log_file = tmp_path / "test4.log"
    logger = get_logger("extra-test", str(log_file))

    logger.warning("risk event", extra={"error": RuntimeError("bad state")})

    record = json.loads(log_file.read_text().strip())
    assert record["error"] == "bad state"
