"""CDP screenshot capture — skips when no Chrome is installed.

Locally, an installed-but-unlaunchable Chrome (sandboxed / headless-broken)
skips too; in the browser CI tier (PDF2EPUB_REQUIRE_BROWSER=1), a launch or
protocol failure FAILS instead of hiding a CDP regression."""

import io
import os

import pytest

from pdf2epub.qa.cdp import Chrome, ChromeUnavailable, file_url, find_chrome

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(find_chrome() is None,
                       reason="no chrome/chromium on this machine"),
]


def test_capture_clip(tmp_path):
    (tmp_path / "page.xhtml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><head>\n'
        '<link rel="stylesheet" type="text/css" href="css/s.css"/>\n'
        '</head><body>\n'
        '<div id="pg-1" epub:type="pagebreak" aria-label="1"></div>\n'
        '<p style="height:400px">alpha</p>\n'
        '<div id="pg-2" epub:type="pagebreak" aria-label="2"></div>\n'
        '<p style="height:300px">beta</p>\n'
        "</body></html>")
    (tmp_path / "css").mkdir()
    (tmp_path / "css" / "s.css").write_text("p { background: #ddeeff; }")
    try:
        with Chrome() as ch:
            ch.open(file_url(str(tmp_path / "page.xhtml")))
            got = ch.eval(
                "JSON.stringify({h: document.documentElement.scrollHeight,"
                " pb: [...document.querySelectorAll('div[id^=pg-]')]"
                ".map(d => d.getBoundingClientRect().top + window.scrollY)})")
            import json

            info = json.loads(got)
            assert len(info["pb"]) == 2 and info["pb"][1] > info["pb"][0]
            png = ch.screenshot(0, info["pb"][0], 600,
                                info["pb"][1] - info["pb"][0], scale=2.0)
    except ChromeUnavailable as e:
        if os.environ.get("PDF2EPUB_REQUIRE_BROWSER"):
            raise
        pytest.skip(f"chrome present but would not launch: {e}")
    from PIL import Image

    img = Image.open(io.BytesIO(png))
    assert img.width == 1200                       # 600 css px at scale 2
    assert abs(img.height - 2 * (info["pb"][1] - info["pb"][0])) <= 2
    # the styled paragraph background must be visible (page actually loaded
    # its relative stylesheet over file://)
    colors = img.convert("RGB").getcolors(maxcolors=100000)
    assert any(c[1] == (221, 238, 255) for c in colors)
