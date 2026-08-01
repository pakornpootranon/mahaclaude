from __future__ import annotations

import json
import logging

from newswatch_worker.logging_config import JsonFormatter


def _make_record(**kwargs) -> logging.LogRecord:
    defaults = dict(
        name="newswatch_worker.cycle",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="cycle=%s state=%s",
        args=("abc123", "TRIAGING"),
        exc_info=None,
    )
    defaults.update(kwargs)
    return logging.LogRecord(**defaults)


def test_format_produces_valid_json_with_core_fields():
    record = _make_record()
    line = JsonFormatter().format(record)
    payload = json.loads(line)

    assert payload["level"] == "INFO"
    assert payload["logger"] == "newswatch_worker.cycle"
    assert payload["message"] == "cycle=abc123 state=TRIAGING"
    assert "timestamp" in payload


def test_format_includes_exception_info():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _make_record(msg="failed", args=(), exc_info=sys.exc_info())

    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in payload["exc_info"]


def test_format_includes_extra_fields():
    record = _make_record()
    record.cycle_id = "abc123"
    record.state = "TRIAGING"

    payload = json.loads(JsonFormatter().format(record))
    assert payload["cycle_id"] == "abc123"
    assert payload["state"] == "TRIAGING"
