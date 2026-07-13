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


def test_verify_fails_on_recorded_input_missing(tmp_path):
    # a recorded input that has since VANISHED must fail, not silently pass
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
    by.unlink()                                          # input deleted/relocated
    assert run_verify(epub) == 1


def test_verify_checks_source_pdf(tmp_path):
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"e")
    pdf = tmp_path / "src.pdf"
    pdf.write_bytes(b"PDF-v1")
    (tmp_path / "book.manifest.json").write_text(json.dumps({
        "epub_sha256": _sha(b"e"),
        "source_pdf_path": str(pdf),
        "source_pdf_sha256": _sha(b"PDF-v1"),
    }))
    assert run_verify(epub) == 0
    pdf.write_bytes(b"PDF-v2-changed")                   # source drift
    assert run_verify(epub) == 1


def _cfg(tmp_path):
    (tmp_path / "book.yaml").write_text("schema_version: 1\n")
    cfg = PdfBookConfig(path=tmp_path / "book.yaml")
    cfg.slug = "x"
    cfg.pdf = "missing.pdf"
    return cfg


def test_manifest_deterministic_and_no_wallclock(tmp_path):
    cfg = _cfg(tmp_path)
    snap = dict(book_yaml_sha256="bookhash", source_pdf_path="/src/x.pdf",
                source_pdf_sha256="pdfhash")
    m1 = build_manifest(cfg, epub_sha256="abc", epubcheck_status="passed",
                        epubcheck_version="5.3.0", **snap)
    m2 = build_manifest(cfg, epub_sha256="abc", epubcheck_status="passed",
                        epubcheck_version="5.3.0", **snap)
    assert m1 == m2                                    # reproducible, no wall-clock
    assert m1["epub_sha256"] == "abc"
    # the manifest records the SNAPSHOTTED input hashes/paths verbatim (not
    # recomputed at manifest time)
    assert m1["book_yaml_sha256"] == "bookhash"
    assert m1["source_pdf_path"] == "/src/x.pdf"
    assert m1["source_pdf_sha256"] == "pdfhash"
    assert m1["epubcheck"] == {"ok": True, "status": "passed", "version": "5.3.0"}
    assert "timestamp" not in json.dumps(m1).lower()


def test_manifest_skipped_epubcheck_is_not_ok(tmp_path):
    m = build_manifest(_cfg(tmp_path), epub_sha256="abc", epubcheck_status="skipped",
                       epubcheck_version=None, book_yaml_sha256="b",
                       source_pdf_path=None, source_pdf_sha256=None)
    # skipped must NOT read as a passing check
    assert m["epubcheck"] == {"ok": None, "status": "skipped", "version": None}
