"""Minimal Chrome DevTools Protocol client for EPUB-slice screenshots.

System Chrome IS the engine most EPUB readers embed, so its rendering of the
shipped CSS/fonts is the fidelity target. Four CDP calls cover everything:
navigate, loadEventFired, Runtime.evaluate (anchor offsets + fonts.ready),
Page.captureScreenshot with a clip (captureBeyondViewport — no scrolling or
stitching). Chrome absent or wedged -> ChromeUnavailable; callers degrade to
PDF-side renders + manifest.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request


class ChromeUnavailable(RuntimeError):
    pass


def find_chrome() -> str | None:
    env = os.environ.get("PDF2EPUB_CHROME")
    if env:
        return env if shutil.which(env) or os.path.exists(env) else None
    for name in ("google-chrome", "google-chrome-stable", "chromium-browser",
                 "chromium"):
        path = shutil.which(name)
        if path:
            return path
    return None


class Chrome:
    """Context manager around one headless Chrome + one reused tab."""

    def __init__(self, viewport: tuple[int, int] = (600, 800)):
        self._exe = find_chrome()
        if self._exe is None:
            raise ChromeUnavailable("no chrome/chromium binary found "
                                    "(set PDF2EPUB_CHROME to override)")
        self._proc = None
        self._ws = None
        self._msg_id = 0
        self._viewport = viewport
        self._profile = None

    # ---------------- lifecycle ----------------

    def __enter__(self):
        self._profile = tempfile.mkdtemp(prefix="pdf2epub-chrome-")
        w, h = self._viewport
        try:
            self._proc = subprocess.Popen(
                [self._exe, "--headless=new", "--remote-debugging-port=0",
                 f"--user-data-dir={self._profile}", "--no-first-run",
                 "--no-default-browser-check", "--disable-gpu",
                 "--hide-scrollbars", "--allow-file-access-from-files",
                 f"--window-size={w},{h}", "about:blank"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            raise ChromeUnavailable(f"chrome failed to launch: {e}") from e
        port = self._wait_port()
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")
            tab = json.loads(urllib.request.urlopen(req, timeout=10).read())
            import websocket

            self._ws = websocket.create_connection(
                tab["webSocketDebuggerUrl"], timeout=15,
                suppress_origin=True)
        except Exception as e:
            self.__exit__(None, None, None)
            raise ChromeUnavailable(f"devtools connection failed: {e}") from e
        self._cmd("Page.enable")
        return self

    def __exit__(self, *exc):
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._profile:
            shutil.rmtree(self._profile, ignore_errors=True)
        return False

    def _wait_port(self, timeout: float = 10.0) -> int:
        path = os.path.join(self._profile, "DevToolsActivePort")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise ChromeUnavailable("chrome exited during startup")
            try:
                with open(path) as f:
                    return int(f.readline().strip())
            except (OSError, ValueError):
                time.sleep(0.05)
        raise ChromeUnavailable("DevToolsActivePort never appeared")

    # ---------------- protocol ----------------

    def _cmd(self, method: str, params: dict | None = None,
             wait_event: str | None = None, timeout: float = 10.0) -> dict:
        self._msg_id += 1
        mid = self._msg_id
        self._ws.settimeout(timeout)
        self._ws.send(json.dumps({"id": mid, "method": method,
                                  "params": params or {}}))
        result: dict | None = None
        got_event = wait_event is None
        deadline = time.monotonic() + timeout
        while (result is None or not got_event) and time.monotonic() < deadline:
            msg = json.loads(self._ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise ChromeUnavailable(f"{method}: {msg['error']}")
                result = msg.get("result", {})
            elif msg.get("method") == wait_event:
                got_event = True
        if result is None or not got_event:
            raise ChromeUnavailable(f"{method}: timed out")
        return result

    # ---------------- public API ----------------

    def open(self, url: str, timeout: float = 10.0) -> None:
        """Navigate the tab and wait for load + shipped fonts."""
        self._cmd("Page.navigate", {"url": url},
                  wait_event="Page.loadEventFired", timeout=timeout)
        self.eval("document.fonts.ready.then(() => 1)", await_promise=True)

    def eval(self, js: str, await_promise: bool = False, timeout: float = 5.0):
        got = self._cmd("Runtime.evaluate",
                        {"expression": js, "returnByValue": True,
                         "awaitPromise": await_promise}, timeout=timeout)
        return got.get("result", {}).get("value")

    def screenshot(self, x: float, y: float, w: float, h: float,
                   scale: float = 2.0) -> bytes:
        import base64

        got = self._cmd("Page.captureScreenshot",
                        {"format": "png", "captureBeyondViewport": True,
                         "clip": {"x": x, "y": y, "width": w, "height": h,
                                  "scale": scale}}, timeout=30.0)
        return base64.b64decode(got["data"])


def file_url(path: str) -> str:
    return "file://" + urllib.parse.quote(os.path.abspath(path))
