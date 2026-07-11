"""`pdf2epub kindle`: convert a built EPUB to Kindle AZW3 (KF8) via Calibre.

A thin post-process wrapper — NO pipeline change. The shipped reflowable EPUB 3
is the source of truth; this shells to Calibre's ``ebook-convert`` (the same
external-tool pattern as the epubcheck gate in ``core/qa_epubcheck.py``) and
reports the output path, size, and any converter warnings. AZW3 (KF8) is the
modern Kindle format.

Tool location: ``PDF2EPUB_EBOOK_CONVERT`` overrides; otherwise ``ebook-convert``
is found on PATH. A missing converter is a HARD error (the user explicitly asked
for the artifact), pointing at ``scripts/bootstrap.sh`` — unlike an optional
gate, there is nothing to degrade to.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _ebook_convert() -> str | None:
    """Path to the calibre ``ebook-convert`` binary, or None if unavailable."""
    env = os.environ.get("PDF2EPUB_EBOOK_CONVERT")
    if env:
        return env
    return shutil.which("ebook-convert")


def _fmt_size(n: int) -> str:
    mb = n / (1024 * 1024)
    return f"{mb:.1f} MB" if mb >= 1 else f"{n / 1024:.0f} KB"


def run_kindle(epub: Path, out: Path | None = None, say=print) -> int:
    """Convert ``epub`` to a Kindle AZW3 via Calibre ``ebook-convert``.

    Returns 0 on success, 1 on failure (EPUB missing, converter absent,
    converter error, or no output produced). Output defaults to the EPUB's path
    with an ``.azw3`` suffix (lands in ``build/`` beside ``<slug>.epub``)."""
    epub = Path(epub)
    if not epub.exists():
        say(f"kindle: EPUB not found: {epub}")
        return 1
    tool = _ebook_convert()
    if tool is None:
        say("kindle: ebook-convert not found; install calibre "
            "(see scripts/bootstrap.sh)")
        return 1

    out = Path(out) if out is not None else epub.with_suffix(".azw3")
    # ebook-convert selects AZW3 from the .azw3 extension; the EPUB is already
    # epubcheck-clean, so no heuristics/fixups are needed.
    try:
        proc = subprocess.run([tool, str(epub), str(out)],
                              capture_output=True, text=True)
    except OSError as e:  # tool path from PDF2EPUB_EBOOK_CONVERT not executable
        say(f"kindle: could not run {tool!r}: {e}; install calibre "
            "(see scripts/bootstrap.sh)")
        return 1

    if proc.returncode != 0 or not out.exists():
        say(f"kindle: ebook-convert FAILED (exit {proc.returncode})")
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-8:]
        for ln in tail:
            say(f"  {ln}")
        return 1

    # calibre logs mostly to stdout but routes some notices to stderr — scan
    # both so a "clean" report can't hide a captured warning
    warns = [ln.strip()
             for ln in (proc.stdout + "\n" + proc.stderr).splitlines()
             if ln.strip().startswith("WARNING")]
    for ln in warns[:8]:
        say(f"  {ln}")
    say(f"→ {out} ({_fmt_size(out.stat().st_size)})")
    say(f"kindle: {'clean' if not warns else f'{len(warns)} warning(s)'}")
    return 0
