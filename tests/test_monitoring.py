"""Run-health summary tests on a small hand-made trace file."""

import json

from riskdesk import monitoring


def _write(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_run_health_counts_outcomes_by_run(tmp_path):
    p = tmp_path / "traces.jsonl"
    _write(p, [
        {"run_id": "r1", "node": "draft_report", "latency_ms": 100, "drafter": "ollama_tools", "tokens": 10,
         "prompt_version": "2.1.0", "fallback_reason": None},
        {"run_id": "r1", "node": "validate", "latency_ms": 5, "grounding_ok": True, "prompt_version": "2.1.0"},
        {"run_id": "r1", "node": "challenge", "latency_ms": 50, "agrees": True},
        {"run_id": "r2", "node": "draft_report", "latency_ms": 300, "drafter": "template_fallback", "tokens": 0,
         "prompt_version": "2.1.0", "fallback_reason": "content_check_failed: classification not named"},
        {"run_id": "r2", "node": "validate", "latency_ms": 5, "grounding_ok": False, "prompt_version": "2.1.0"},
        {"run_id": "r2", "node": "challenge", "latency_ms": 60, "agrees": False},
    ])
    h = monitoring.run_health(str(p))
    assert h["runs"] == 2
    assert h["drafters"] == {"ollama_tools": 1, "template_fallback": 1}
    assert h["fallback_reasons"] == {"content_check_failed": 1}
    assert h["challenges"] == 2 and h["challenger_disagreements"] == 1
    assert h["grounding_failures"] == 1
    assert h["tokens_total"] == 10
    assert h["run_latency_ms_p50"] == 365  # run totals are 155 ms and 365 ms; the p50 index selects the second


def test_run_health_handles_missing_or_empty_file(tmp_path):
    assert monitoring.run_health(str(tmp_path / "absent.jsonl")) == {"runs": 0}
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert monitoring.run_health(str(empty)) == {"runs": 0}
