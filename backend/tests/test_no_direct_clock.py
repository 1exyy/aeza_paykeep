"""Invariant AGENTS §4.1: time comes only from app/core/clock.py; no floats for money."""

import re
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
FORBIDDEN = re.compile(r"\b(date\.today|datetime\.now|datetime\.utcnow|time\.time)\s*\(")


def test_no_direct_clock_calls() -> None:
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        if path.relative_to(APP_DIR).as_posix() == "core/clock.py":
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if FORBIDDEN.search(line):
                offenders.append(f"{path.relative_to(APP_DIR)}:{i}: {line.strip()}")
    assert not offenders, "Use app.core.clock instead:\n" + "\n".join(offenders)


def test_no_float_in_money_code() -> None:
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\bfloat\s*\(|:\s*float\b|\bFloat\b", line):
                offenders.append(f"{path.relative_to(APP_DIR)}:{i}: {line.strip()}")
    assert not offenders, "\n".join(offenders)
