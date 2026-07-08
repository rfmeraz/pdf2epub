"""Fonts stage (JP-P7): OFL embeds from system font files, subset to use.

Never extracts fonts from the PDF; never embeds proprietary faces. Default
posture is NO Latin embed (reader serif) — entries exist only for glyphs
reader fonts can't cover (honorifics via Amiri, CJK via Noto Serif CJK)."""

from __future__ import annotations

from pathlib import Path

from .core.fonts import EmbeddedFont, collect_codepoints, embed_face


def stage_fonts_pdf(ctx) -> list[EmbeddedFont]:
    cfg = ctx.cfg
    out_dir = cfg.build_dir / "oebps" / "font"
    buckets = collect_codepoints(ctx.flow)
    fonts: list[EmbeddedFont] = []
    for fe in cfg.fonts_embed:
        if fe.script == "cjk":
            chars = set(buckets.get(fe.lang or "zh", set()))
            if fe.lang in (None, "zh"):
                # union all non-latin buckets: han-only runs vs kana runs etc.
                for k, v in buckets.items():
                    if k not in ("latin", "latin-italic", "ar"):
                        chars |= v
        else:
            chars = set(buckets["latin-italic" if fe.style == "italic" else "latin"])
        if not chars:
            ctx.say(f"  fonts: no characters need {fe.family}; skipped")
            continue
        src = Path(fe.file)
        if not src.exists():
            raise SystemExit(f"fonts.embed file missing: {src}")
        f = embed_face(fe.family, src, chars, out_dir, style=fe.style,
                       script=fe.script, lang=fe.lang, do_subset=cfg.fonts_subset)
        fonts.append(f)
    if fonts:
        total = sum(f.path.stat().st_size for f in fonts)
        ctx.say("fonts: embedded " +
                ", ".join(f"{f.family} ({f.path.stat().st_size//1024}KB)" for f in fonts) +
                f"; total {total//1024}KB")
    else:
        ctx.say("fonts: none embedded (reader defaults)")
    ctx.embedded_fonts = fonts
    return fonts
