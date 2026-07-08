# Forked from idml2epub src/idml2epub/qa/epubcheck.py @ 7eb7eac (jar path/env var
# point at pdf2epub's own vendor/)
"""epubcheck wrapper: the non-negotiable validity gate."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _jar() -> Path:
    env = os.environ.get("PDF2EPUB_EPUBCHECK")
    if env:
        return Path(env)
    # src/pdf2epub/core/qa_epubcheck.py -> repo root
    return Path(__file__).resolve().parents[3] / "vendor" / "epubcheck" / "epubcheck.jar"


def run_epubcheck(epub: Path) -> tuple[bool, list[str]]:
    """Returns (ok, human-readable messages). ok = zero errors/fatals."""
    jar = _jar()
    if not jar.exists():
        return False, [f"epubcheck jar not found at {jar}; run scripts/bootstrap.sh"]
    proc = subprocess.run(
        ["java", "-jar", str(jar), str(epub), "--json", "-"],
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return False, [f"epubcheck produced no JSON (exit {proc.returncode}): {proc.stderr[:400]}"]
    messages = []
    n_err = 0
    for m in data.get("messages", []):
        sev = m.get("severity", "")
        if sev in ("ERROR", "FATAL"):
            n_err += 1
        if sev in ("ERROR", "FATAL", "WARNING"):
            locs = m.get("locations", [])[:1]
            loc = f" [{locs[0].get('path')}:{locs[0].get('line')}]" if locs else ""
            messages.append(f"{sev}: {m.get('message', '')[:200]}{loc}")
    checker = data.get("checker", {})
    messages.append(
        f"epubcheck {checker.get('checkerVersion', '?')}: "
        f"{checker.get('nError', n_err)} errors, {checker.get('nWarning', 0)} warnings"
    )
    return n_err == 0, messages
