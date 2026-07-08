"""Minimal CSS resolver for the SHIPPED stylesheet (typography QA).

Scope is exactly the machine-generated shape of emit_css.py — tag rules,
single-class rules, `tag.class`, one-level descendants (`blockquote p`),
comma groups — nothing more. Selectors this pipeline never emits (or whose
targets QA never queries) are skipped whole: pseudo-elements/classes,
attribute selectors, combinators, @-rules. QA reads the EPUB's own
css/styles.css bytes through this, NOT the in-memory catalog: the point is
to grade the shipped artifact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_ATRULE_RE = re.compile(r"@[a-zA-Z-]+[^{}]*\{[^{}]*\}", re.S)
_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
_SIMPLE_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9]*)?((?:\.[A-Za-z0-9_-]+)*)$")
_SKIP_MARKS = ("::", ":", "[", ">", "+", "~")


@dataclass(slots=True)
class CssRule:
    ancestor: tuple[str | None, frozenset[str]] | None  # ("blockquote", {}) etc.
    tag: str | None                                     # None for bare ".class"
    classes: frozenset[str]                             # of the subject selector
    props: dict[str, str]
    order: int

    def specificity(self) -> tuple[int, int, int]:
        n_cls = len(self.classes)
        n_type = 1 if self.tag else 0
        if self.ancestor:
            atag, acls = self.ancestor
            n_cls += len(acls)
            n_type += 1 if atag else 0
        return (n_cls, n_type, self.order)

    def source(self) -> str:
        """Where a winning declaration came from: 'tag' or 'class:<name>'."""
        if self.classes:
            return "class:" + min(self.classes)
        return "tag"


def _parse_simple(sel: str) -> tuple[str | None, frozenset[str]] | None:
    m = _SIMPLE_RE.match(sel)
    if not m or (not m.group(1) and not m.group(2)):
        return None
    classes = frozenset(c for c in m.group(2).split(".") if c)
    return (m.group(1) or None, classes)


def parse_stylesheet(text: str) -> list[CssRule]:
    text = _COMMENT_RE.sub(" ", text)
    text = _ATRULE_RE.sub(" ", text)
    rules: list[CssRule] = []
    order = 0
    for m in _RULE_RE.finditer(text):
        props: dict[str, str] = {}
        for decl in m.group(2).split(";"):
            key, _, val = decl.partition(":")
            if key.strip() and val.strip():
                props[key.strip().lower()] = val.strip()
        if not props:
            continue
        for sel in m.group(1).split(","):
            sel = sel.strip()
            if not sel or any(mark in sel for mark in _SKIP_MARKS):
                continue
            parts = sel.split()
            if len(parts) > 2:
                continue
            parsed = [_parse_simple(p) for p in parts]
            if any(p is None for p in parsed):
                continue
            subject = parsed[-1]
            ancestor = parsed[0] if len(parsed) == 2 else None
            rules.append(CssRule(ancestor=ancestor, tag=subject[0],
                                 classes=subject[1], props=dict(props),
                                 order=order))
            order += 1
    return rules


def _matches(rule: CssRule, tag: str, classes: set[str],
             ancestors: tuple[tuple[str, set[str]], ...]) -> bool:
    if rule.tag is not None and rule.tag != tag:
        return False
    if not rule.classes <= classes:
        return False
    if rule.ancestor is not None:
        atag, acls = rule.ancestor
        return any((atag is None or atag == t) and acls <= c
                   for t, c in ancestors)
    return True


def resolve_block(rules: list[CssRule], tag: str, classes: set[str],
                  ancestors: tuple[tuple[str, set[str]], ...] = ()
                  ) -> dict[str, tuple[str, str]]:
    """Effective declarations for one element: prop -> (value, source)."""
    winners: dict[str, tuple[tuple[int, int, int], str, str]] = {}
    for rule in rules:
        if not _matches(rule, tag, classes, ancestors):
            continue
        spec = rule.specificity()
        for prop, val in rule.props.items():
            cur = winners.get(prop)
            if cur is None or spec >= cur[0]:
                winners[prop] = (spec, val, rule.source())
    return {p: (v, s) for p, (_, v, s) in winners.items()}


def _em(value: str) -> float | None:
    if value.endswith("em"):
        try:
            return float(value[:-2])
        except ValueError:
            return None
    return None


def effective_font_size_em(rules: list[CssRule], tag: str, classes: set[str],
                           ancestors: tuple[tuple[str, set[str]], ...] = ()
                           ) -> float:
    """Block font size in em of the body text, ancestor ems multiplied in.

    Only em values exist in the generated CSS; anything else counts 1.0.
    """
    em = 1.0
    for atag, acls in ancestors:
        got = resolve_block(rules, atag, acls).get("font-size")
        if got:
            em *= _em(got[0]) or 1.0
    got = resolve_block(rules, tag, classes, ancestors).get("font-size")
    if got:
        em *= _em(got[0]) or 1.0
    return em
