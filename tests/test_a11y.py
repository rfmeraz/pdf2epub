"""Ace parser + absence-vs-failure distinction (gate 26 support)."""

from pdf2epub.qa import ace as ace_mod
from pdf2epub.qa.ace import _judge, run_ace

# report.json shape per https://daisy.github.io/ace/docs/report-json/ :
# nested assertions; impact under earl:test.earl:impact, outcome under earl:result.
_CLEAN = {"assertions": [{"assertions": [
    {"earl:test": {"earl:impact": "minor", "dct:title": "ok"},
     "earl:result": {"earl:outcome": "pass"}}]}]}
_SERIOUS = {"assertions": [{"assertions": [
    {"earl:test": {"earl:impact": "serious", "dct:title": "Image missing alt"},
     "earl:result": {"earl:outcome": "fail"}},
    {"earl:test": {"earl:impact": "minor", "dct:title": "nit"},
     "earl:result": {"earl:outcome": "fail"}}]}]}


def test_judge_clean_passes():
    ok, lines = _judge(_CLEAN)
    assert ok


def test_judge_serious_fails_and_names_it():
    ok, lines = _judge(_SERIOUS)
    assert not ok
    assert any("serious" in ln for ln in lines)
    assert any("Image missing alt" in ln for ln in lines)


def test_absence_skips_not_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(ace_mod, "_ace_cmd", lambda: None)
    ok, lines = run_ace(tmp_path / "x.epub")
    assert ok is None                      # genuine absence ⇒ SKIP
    assert any("skipped" in ln for ln in lines)


def test_installed_but_no_report_is_failure(monkeypatch, tmp_path):
    # 'true' exists, exits 0, writes no report.json → must FAIL, not skip
    monkeypatch.setattr(ace_mod, "_ace_cmd", lambda: ["true"])
    ok, lines = run_ace(tmp_path / "x.epub", timeout=15)
    assert ok is False
    assert any("no report" in ln.lower() for ln in lines)
