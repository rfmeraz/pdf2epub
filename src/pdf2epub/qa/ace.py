"""Ace by DAISY wrapper for the a11y-readiness gate (26).

Ace is the accessibility checker (https://daisy.github.io/ace/); its exit code
does NOT encode violations, so we judge the emitted report.json
(https://daisy.github.io/ace/docs/report-json/) — failed assertions grouped by
`earl:test.earl:impact`, gating on critical/serious. Ace is PINNED via the
committed tools/ace/package.json (npm ci); `npx --no-install` never
auto-downloads. Genuine ABSENCE (not installed) skips (ok=None); a crash /
timeout / missing-or-malformed report is a real FAILURE (ok=False) — a broken
checker must not silently pass as "skipped".
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

_GATING = {"critical", "serious"}


def _pinned_ace() -> Path:
    # src/pdf2epub/qa/ace.py -> repo root -> tools/ace/node_modules/.bin/ace
    return (Path(__file__).resolve().parents[3]
            / "tools" / "ace" / "node_modules" / ".bin" / "ace")


def _ace_cmd() -> list[str] | None:
    """The command to invoke Ace, or None if genuinely not installed."""
    env = os.environ.get("PDF2EPUB_ACE")
    if env:
        return env.split()
    pinned = _pinned_ace()
    if pinned.exists():                       # the bootstrap `npm ci` location
        return [str(pinned)]
    if shutil.which("ace"):
        return ["ace"]
    npx = shutil.which("npx")
    if not npx:
        return None
    try:
        p = subprocess.run([npx, "--no-install", "@daisy/ace", "--version"],
                           capture_output=True, text=True, timeout=60)
        if p.returncode == 0:
            return [npx, "--no-install", "@daisy/ace"]
    except (subprocess.SubprocessError, OSError):
        return None
    return None


def _judge(data: dict) -> tuple[bool, list[str]]:
    counts: dict[str, int] = {}
    examples: list[str] = []
    for top in data.get("assertions", []):
        for a in top.get("assertions", []):
            if (a.get("earl:result", {}) or {}).get("earl:outcome") != "fail":
                continue
            test = a.get("earl:test", {}) or {}
            impact = str(test.get("earl:impact") or "unknown").lower()
            counts[impact] = counts.get(impact, 0) + 1
            if impact in _GATING and len(examples) < 8:
                examples.append(f"{impact}: {test.get('dct:title', '?')}")
    gating = sum(counts.get(k, 0) for k in _GATING)
    return gating == 0, [f"ace: {dict(sorted(counts.items()))}; "
                         f"{gating} critical/serious"] + examples


def run_ace(epub: Path, timeout: int = 300) -> tuple[bool | None, list[str]]:
    """Returns (ok, messages). ok is None ⇒ SKIPPED (Ace genuinely absent);
    True ⇒ no critical/serious; False ⇒ critical/serious OR Ace failed to run."""
    cmd = _ace_cmd()
    if cmd is None:
        return None, ["ace not installed; a11y Ace check skipped "
                      "(pin+install via scripts/bootstrap.sh / tools/ace)"]
    with tempfile.TemporaryDirectory() as td:
        try:
            proc = subprocess.run(cmd + ["-o", td, "-f", str(epub)],
                                  capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, [f"ace TIMED OUT after {timeout}s"]
        except (subprocess.SubprocessError, OSError) as e:
            return False, [f"ace failed to launch: {e}"]
        report = Path(td) / "report.json"
        if not report.exists():
            return False, [f"ace produced no report.json (exit {proc.returncode}): "
                           f"{(proc.stderr or proc.stdout)[:300]}"]
        try:
            data = json.loads(report.read_text())
        except (json.JSONDecodeError, OSError) as e:
            return False, [f"ace report.json malformed: {e}"]
    return _judge(data)
