"""Map stage: roles from the pstyle map + overrides; language tagging; RTL census."""

from __future__ import annotations

from .config import PdfBookConfig
from .core.lang import tag_languages
from .core.model import Paragraph
from .core.roles import StyleRule, apply_roles
from .flowbuilder import FlowResult
from .warnqueue import rtl_census


def stage_map(ctx, res: FlowResult) -> None:
    cfg: PdfBookConfig = ctx.cfg
    flow = ctx.flow

    style_map = dict(cfg.pstyle_map)
    style_map.setdefault("__toc__", StyleRule(role="toc-entry"))
    style_map.setdefault("__note__", StyleRule(role="p"))

    unmapped = apply_roles(flow.blocks, style_map, cfg.unmapped_role)
    if unmapped:
        listing = ", ".join(unmapped)
        if cfg.fail_on_unmapped:
            raise SystemExit(f"pstyles not in styles.pstyle_map (fail_on_unmapped): {listing}")
        ctx.say(f"  WARNING: unmapped pstyles -> role '{cfg.unmapped_role}': {listing}")
        flow.warnings.append(f"unmapped pstyles: {listing}")
    for note in flow.notes.values():
        apply_roles(note.paragraphs, style_map, "p")

    # page-scoped role overrides (JP-P2), then line-scoped (flow.overrides)
    for ro in cfg.role_overrides:
        sid = f"p{ro.page:04d}"
        for b in flow.blocks:
            if isinstance(b, Paragraph) and b.src.story_id == sid:
                b.role = ro.role
                if ro.class_ and ro.class_ not in b.classes:
                    b.classes.append(ro.class_)
    for (page, line), role in res.role_overrides_by_line.items():
        sid = f"p{page:04d}"
        for b in flow.blocks:
            if isinstance(b, Paragraph) and b.src.story_id == sid and b.src.psr_index == line:
                b.role = role

    # re-apply drop-cap classes (apply_roles rebuilt Paragraph.classes)
    if res.dropcap_srcs:
        for b in flow.blocks:
            if isinstance(b, Paragraph) and \
                    (b.src.story_id, b.src.psr_index) in res.dropcap_srcs and \
                    "first-dropcap" not in b.classes:
                b.classes.append("first-dropcap")

    census = tag_languages(flow, cfg.cjk_han_only, cfg.lang_overrides)
    ctx.lang_census = census

    # RTL census (shared with the QA warnings gate via warnqueue): runs the
    # PUA substitution deliberately tagged (fmt.lang set, e.g. the honorific
    # ligature as lang=ar) are expected; RTL text in UNTAGGED runs is live
    # foreign text the pipeline cannot lay out yet
    expected, unexpected = rtl_census(flow)
    if expected:
        ctx.say(f"  {expected} RTL char(s) from verified glyph substitutions (expected)")
    if unexpected:
        msg = (f"{unexpected} right-to-left script characters found as live text: "
               "RTL layout is NOT implemented — escalate before shipping")
        flow.warnings.append(msg)
        ctx.say(f"  WARNING: {msg}")

    heads = sum(1 for b in flow.blocks
                if isinstance(b, Paragraph) and b.role in ("h1", "h2", "h3"))
    ctx.say(f"mapped roles (body pstyle: {cfg.body_pstyle}); {heads} headings; "
            f"lang clusters: "
            + (", ".join(f"{k}:{v}" for k, v in sorted(census.items())) or "none"))
