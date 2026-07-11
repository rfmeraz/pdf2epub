"""`pdf2epub kindle` — the Calibre AZW3 post-process wrapper.

The external `ebook-convert` call is mocked (subprocess + shutil.which) so the
command construction, default output path, and failure/skip behavior are pinned
without needing calibre installed.
"""

from pathlib import Path
from types import SimpleNamespace

from pdf2epub import kindle


def _epub(tmp_path):
    p = tmp_path / "book.epub"
    p.write_bytes(b"epub")
    return p


def test_missing_tool_returns_1(tmp_path, monkeypatch):
    monkeypatch.delenv("PDF2EPUB_EBOOK_CONVERT", raising=False)
    monkeypatch.setattr(kindle.shutil, "which", lambda name: None)
    msgs: list[str] = []
    assert kindle.run_kindle(_epub(tmp_path), say=msgs.append) == 1
    assert any("install calibre" in m for m in msgs)


def test_default_output_path_and_command(tmp_path, monkeypatch):
    monkeypatch.delenv("PDF2EPUB_EBOOK_CONVERT", raising=False)
    monkeypatch.setattr(kindle.shutil, "which",
                        lambda name: "/usr/bin/ebook-convert")
    calls = {}

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        Path(cmd[2]).write_bytes(b"azw3-bytes")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(kindle.subprocess, "run", fake_run)
    epub = _epub(tmp_path)
    assert kindle.run_kindle(epub, say=lambda m: None) == 0
    assert calls["cmd"][0] == "/usr/bin/ebook-convert"
    assert calls["cmd"][1] == str(epub)
    assert calls["cmd"][2] == str(epub.with_suffix(".azw3"))
    assert (tmp_path / "book.azw3").exists()


def test_env_override_and_explicit_out(tmp_path, monkeypatch):
    monkeypatch.setenv("PDF2EPUB_EBOOK_CONVERT", "/opt/ec")
    calls = {}

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        Path(cmd[2]).write_bytes(b"d")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(kindle.subprocess, "run", fake_run)
    out = tmp_path / "custom.azw3"
    assert kindle.run_kindle(_epub(tmp_path), out=out, say=lambda m: None) == 0
    assert calls["cmd"][0] == "/opt/ec"
    assert calls["cmd"][2] == str(out)


def test_converter_failure_returns_1(tmp_path, monkeypatch):
    monkeypatch.delenv("PDF2EPUB_EBOOK_CONVERT", raising=False)
    monkeypatch.setattr(kindle.shutil, "which",
                        lambda name: "/usr/bin/ebook-convert")
    monkeypatch.setattr(kindle.subprocess, "run",
                        lambda cmd, **kw: SimpleNamespace(
                            returncode=1, stdout="", stderr="boom"))
    msgs: list[str] = []
    assert kindle.run_kindle(_epub(tmp_path), say=msgs.append) == 1
    assert any("FAILED" in m for m in msgs)


def test_missing_epub_returns_1(tmp_path):
    msgs: list[str] = []
    assert kindle.run_kindle(tmp_path / "nope.epub", say=msgs.append) == 1
    assert any("not found" in m for m in msgs)


def test_unexecutable_tool_returns_1(tmp_path, monkeypatch):
    # a bad PDF2EPUB_EBOOK_CONVERT path must fail cleanly, not raise
    monkeypatch.setenv("PDF2EPUB_EBOOK_CONVERT", "/nonexistent/ebook-convert")

    def boom(cmd, **kw):
        raise FileNotFoundError(2, "No such file or directory", cmd[0])

    monkeypatch.setattr(kindle.subprocess, "run", boom)
    msgs: list[str] = []
    assert kindle.run_kindle(_epub(tmp_path), say=msgs.append) == 1
    assert any("could not run" in m for m in msgs)
