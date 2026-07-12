#!/usr/bin/env bash
# One-time machine setup for pdf2epub. Idempotent.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${HOME}/pyenv/bin/python"
PIP="${HOME}/pyenv/bin/pip"

echo "== python deps (into ~/pyenv) =="
"$PIP" install --quiet PyMuPDF lxml PyYAML rapidfuzz Pillow fonttools pytest \
  websocket-client
"$PIP" install --quiet -e "$REPO_DIR"

echo "== epubcheck (own vendored copy) =="
EPUBCHECK_VERSION=5.3.0
JAR_DIR="$REPO_DIR/vendor/epubcheck"
if [ ! -f "$JAR_DIR/epubcheck.jar" ]; then
  mkdir -p "$JAR_DIR"
  tmp=$(mktemp -d)
  curl -sL -o "$tmp/epubcheck.zip" \
    "https://github.com/w3c/epubcheck/releases/download/v${EPUBCHECK_VERSION}/epubcheck-${EPUBCHECK_VERSION}.zip"
  unzip -q "$tmp/epubcheck.zip" -d "$tmp"
  cp -r "$tmp/epubcheck-${EPUBCHECK_VERSION}/"* "$JAR_DIR/"
  mv "$JAR_DIR/epubcheck-${EPUBCHECK_VERSION}.jar" "$JAR_DIR/epubcheck.jar" 2>/dev/null || true
  # some releases name the jar epubcheck.jar already
  [ -f "$JAR_DIR/epubcheck.jar" ] || { echo "epubcheck jar not found after unzip"; exit 1; }
  rm -rf "$tmp"
fi
java -jar "$JAR_DIR/epubcheck.jar" --version

echo "== fonts (OFL faces used for embeds/substitutes) =="
# note: grep WITHOUT -q — under pipefail, grep -q's early exit SIGPIPEs fc-list
# and the pipeline reports failure even on a match
fonts_avail="$(fc-list 2>/dev/null)"
need_dnf=()
grep -i "amiri" >/dev/null <<<"$fonts_avail" || need_dnf+=(amiri-fonts)
grep -i "noto serif cjk" >/dev/null <<<"$fonts_avail" || need_dnf+=(google-noto-serif-cjk-fonts)
if [ ${#need_dnf[@]} -gt 0 ]; then
  echo "installing: ${need_dnf[*]} (sudo dnf)"
  sudo dnf install -y "${need_dnf[@]}"
fi

echo "== poppler CLI (QA ground truth + engine cross-check) =="
for tool in pdftotext pdfinfo pdfimages; do
  command -v "$tool" >/dev/null || { echo "MISSING: $tool (dnf install poppler-utils)"; exit 1; }
done

echo "== chrome (qa --visual EPUB-slice renders; warn-only) =="
command -v google-chrome >/dev/null || command -v chromium >/dev/null || \
  echo "NOTE: no chrome/chromium — 'pdf2epub qa --visual' will skip EPUB-side renders (PDF panels + manifest still produced)"

echo "== calibre (pdf2epub kindle -> AZW3; warn-only) =="
command -v ebook-convert >/dev/null || \
  echo "NOTE: no calibre/ebook-convert — 'pdf2epub kindle' is unavailable (install calibre; or set PDF2EPUB_EBOOK_CONVERT)"

echo "== Ace by DAISY (QA gate 26 a11y readiness; warn-only, pinned) =="
if command -v npm >/dev/null; then
  ( cd "$REPO_DIR/tools/ace" && npm ci --no-audit --no-fund >/dev/null 2>&1 ) \
    && echo "Ace pinned install OK (npx --no-install @daisy/ace)" \
    || echo "NOTE: 'npm ci' for Ace failed — gate 26 will SKIP the Ace check (alt+metadata still gate)"
else
  echo "NOTE: no npm — gate 26 will SKIP the Ace check; install Node/npm to enable it"
fi

echo "bootstrap OK"
