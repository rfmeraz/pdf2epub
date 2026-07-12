"""Build provenance manifest — what produced this EPUB, for reproducibility and
audit. NO wall-clock: every field is deterministic for a given machine +
checkout, so two clean builds of the same inputs yield an identical manifest.
The manifest is written once and IMMUTABLE — the QA gate verdict lives in the
separate qa.json sidecar (a mutable QA result must not perturb a byte-stable
provenance record). `run_verify` is the torn-write / stale invariant: the
on-disk EPUB must still hash to what the manifest recorded, and its book.yaml
must not have drifted since the build.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from importlib import metadata as importlib_metadata
from pathlib import Path

# reproducible release epoch fallback (mirrors core/fonts.py SOURCE_DATE_EPOCH)
_DEFAULT_EPOCH = "1767225600"  # 2026-01-01T00:00:00Z
_DEPS = ["PyMuPDF", "lxml", "PyYAML", "rapidfuzz", "Pillow", "fonttools"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fitz_version() -> str:
    try:
        import fitz
        v = getattr(fitz, "version", None)
        return v[0] if isinstance(v, (tuple, list)) and v else str(v)
    except Exception:
        return "unavailable"


def _poppler_version() -> str:
    try:
        p = subprocess.run(["pdftotext", "-v"], capture_output=True, text=True,
                           timeout=15)
        line = (p.stderr + p.stdout).strip().splitlines()[0]
        for tok in line.split():
            if tok[:1].isdigit():
                return tok
        return line
    except Exception:
        return "unavailable"


def _dep_versions() -> dict:
    out = {}
    for name in _DEPS:
        try:
            out[name] = importlib_metadata.version(name)
        except Exception:
            out[name] = "unknown"
    return out


def _git_provenance(inside: Path) -> dict:
    def git(*args):
        return subprocess.run(["git", "-C", str(inside), *args],
                              capture_output=True, text=True, timeout=15)
    try:
        rev = git("rev-parse", "HEAD")
        if rev.returncode != 0:
            return {"rev": "not-a-git-repo", "dirty": None}
        dirty = bool(git("status", "--porcelain").stdout.strip())
        info = {"rev": rev.stdout.strip(), "dirty": dirty}
        if dirty:
            # a clean rev misattributes a dirty-tree build; pin WHAT dirty
            # state produced it with a hash of the working diff.
            info["tree_hash"] = hashlib.sha256(
                git("diff", "HEAD").stdout.encode()).hexdigest()
        return info
    except Exception:
        return {"rev": "unavailable", "dirty": None}


def _release_epoch(cfg) -> str:
    rel = getattr(cfg, "released", None)  # metadata.released (Phase 6)
    if rel:
        return str(rel)
    return os.environ.get("SOURCE_DATE_EPOCH", _DEFAULT_EPOCH)


def build_manifest(cfg, *, epub_sha256: str, epubcheck_ok: bool,
                   epubcheck_version: str) -> dict:
    src_pdf = cfg.pdf_path()
    return {
        "slug": cfg.slug,
        "schema_version": cfg.schema_version,
        "release_epoch": _release_epoch(cfg),
        "book_yaml_path": str(cfg.path),
        "source_pdf_sha256": _sha256(src_pdf) if src_pdf.exists() else None,
        "book_yaml_sha256": _sha256(cfg.path),
        "epub_sha256": epub_sha256,
        "epubcheck": {"ok": epubcheck_ok, "version": epubcheck_version},
        "tools": {
            "python": sys.version.split()[0],
            "pymupdf": _fitz_version(),
            "poppler_pdftotext": _poppler_version(),
            "epubcheck": epubcheck_version,
        },
        "dependencies": _dep_versions(),
        "git": _git_provenance(cfg.path.parent),
    }


def manifest_path(cfg) -> Path:
    return cfg.build_dir / f"{cfg.slug}.manifest.json"


def write_manifest(cfg, manifest: dict) -> Path:
    out = manifest_path(cfg)
    out.write_text(json.dumps(manifest, indent=1, ensure_ascii=False,
                              sort_keys=True) + "\n")
    return out


def run_verify(epub: Path) -> int:
    """Fail if the EPUB no longer matches its provenance manifest (torn write /
    post-build corruption / stale manifest) or its book.yaml drifted since the
    build (the EPUB is stale — rebuild)."""
    epub = epub.expanduser().resolve()
    mpath = epub.parent / f"{epub.stem}.manifest.json"
    if not mpath.exists():
        print(f"VERIFY: no manifest for {epub.name} at {mpath.name}")
        return 1
    try:
        m = json.loads(mpath.read_text())
    except Exception as e:
        print(f"VERIFY FAIL {epub.name}: unreadable manifest — {e}")
        return 1
    problems = []
    if not epub.exists():
        problems.append("EPUB missing")
    elif _sha256(epub) != m.get("epub_sha256"):
        problems.append("EPUB hash != manifest (torn write / corruption / stale)")
    byp = m.get("book_yaml_path")
    if byp and Path(byp).exists() and _sha256(Path(byp)) != m.get("book_yaml_sha256"):
        problems.append("book.yaml changed since build — EPUB is stale, rebuild")
    if problems:
        for p in problems:
            print(f"VERIFY FAIL {epub.name}: {p}")
        return 1
    print(f"VERIFY OK {epub.name}: matches {mpath.name}")
    return 0
