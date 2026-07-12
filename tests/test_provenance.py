"""Provenance manifest + verify invariant (Phase 2)."""

import hashlib
import json

from pdf2epub.config import PdfBookConfig
from pdf2epub.provenance import build_manifest, run_verify


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_verify_ok_then_corruption(tmp_path):
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"epub-bytes")
    (tmp_path / "book.manifest.json").write_text(
        json.dumps({"epub_sha256": _sha(b"epub-bytes")}))
    assert run_verify(epub) == 0
    epub.write_bytes(b"epub-bytes-CHANGED")          # torn write / corruption
    assert run_verify(epub) == 1


def test_verify_missing_manifest(tmp_path):
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"x")
    assert run_verify(epub) == 1


def test_verify_book_yaml_drift(tmp_path):
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"e")
    by = tmp_path / "book.yaml"
    by.write_text("schema_version: 1\n")
    (tmp_path / "book.manifest.json").write_text(json.dumps({
        "epub_sha256": _sha(b"e"),
        "book_yaml_path": str(by),
        "book_yaml_sha256": _sha(b"schema_version: 1\n"),
    }))
    assert run_verify(epub) == 0
    by.write_text("schema_version: 1\n# edited after build\n")   # config drift
    assert run_verify(epub) == 1


def test_manifest_deterministic_and_no_wallclock(tmp_path):
    (tmp_path / "book.yaml").write_text("schema_version: 1\n")
    cfg = PdfBookConfig(path=tmp_path / "book.yaml")
    cfg.slug = "x"
    cfg.pdf = "missing.pdf"
    m1 = build_manifest(cfg, epub_sha256="abc", epubcheck_ok=True,
                        epubcheck_version="5.3.0")
    m2 = build_manifest(cfg, epub_sha256="abc", epubcheck_ok=True,
                        epubcheck_version="5.3.0")
    assert m1 == m2                                    # reproducible, no wall-clock
    assert m1["epub_sha256"] == "abc"
    assert m1["book_yaml_sha256"] == _sha((tmp_path / "book.yaml").read_bytes())
    # no field should carry a current timestamp
    assert "timestamp" not in json.dumps(m1).lower()
