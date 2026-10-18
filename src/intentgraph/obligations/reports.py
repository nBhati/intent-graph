"""Validation of submitted test reports (collection mode ``validated_report``).

The tool parses the report itself and checks that the claimed result matches
what the report says. Supported formats are deliberately few; anything else is
``opaque`` and can only be an ``agent_submitted_report``.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ..errors import InvalidInput

SUPPORTED_FORMATS = ("junit-xml", "intentgraph-test-report/0.1", "opaque")


def validate_report(path: Path, fmt: str, claimed_result: str) -> dict[str, Any]:
    """Return a summary dict or raise ``InvalidInput(report_validation_failed)``."""
    if fmt == "opaque":
        raise InvalidInput("an opaque artifact cannot be validated; submit it as agent_submitted_report or use a supported format", code="report_validation_failed", details={"supported": list(SUPPORTED_FORMATS)})
    if fmt == "junit-xml":
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as exc:
            raise InvalidInput(f"junit report is not well-formed XML: {exc}", code="report_validation_failed") from exc
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        tests = sum(int(s.get("tests", 0)) for s in suites)
        failures = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
        summary = {"format": fmt, "tests": tests, "failures": failures}
    elif fmt == "intentgraph-test-report/0.1":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InvalidInput(f"report is not valid JSON: {exc}", code="report_validation_failed") from exc
        if not isinstance(data, dict) or data.get("format") != fmt or not isinstance(data.get("runs"), list):
            raise InvalidInput("report must be {format: 'intentgraph-test-report/0.1', runs: [{test_id, outcome}]}", code="report_validation_failed")
        runs = data["runs"]
        tests = len(runs)
        failures = sum(1 for r in runs if not isinstance(r, dict) or r.get("outcome") != "passed")
        summary = {"format": fmt, "tests": tests, "failures": failures, "test_ids": [r.get("test_id") for r in runs if isinstance(r, dict)]}
    else:
        raise InvalidInput(f"unsupported report format {fmt!r}", code="report_validation_failed", details={"supported": list(SUPPORTED_FORMATS)})
    if tests == 0:
        raise InvalidInput("report contains no test runs", code="report_validation_failed", details=summary)
    actual = "passed" if failures == 0 else "failed"
    if claimed_result != actual:
        raise InvalidInput(f"claimed result {claimed_result!r} but the report shows {actual} ({failures} failure(s) of {tests})", code="report_validation_failed", details=summary)
    return summary
