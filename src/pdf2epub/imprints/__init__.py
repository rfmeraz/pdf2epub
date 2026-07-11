"""Publisher-/imprint-specific structural transforms.

Most books convert through the generic, publisher-agnostic pipeline. A few
carry back-matter conventions the generic flow cannot model — e.g. World
Wisdom's *Editor's Notes* keyed to original print page numbers with no body
marker. Rather than clutter the core flow with one publisher's quirk, such logic
lives in a per-imprint module here and runs through ONE gated hook
(:func:`apply_imprint`) that the flow builder calls after it has assembled the
typed IR. When ``book.yaml`` sets no ``imprint:`` block the hook is a no-op, so
every other book is untouched.

Each imprint module exposes two functions:
  * ``parse(data: dict) -> options`` — validate and parse the ``imprint:`` block
    (the module owns its own sub-schema; the core only routes the block here);
  * ``apply(res, cfg, doc, say) -> None`` — mutate ``res.flow`` in place, adding
    only markup/link markers (never rewriting words) and appending coded
    ``_Warn``s to ``res.warns`` for anything it cannot confidently resolve.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ImprintSpec:
    name: str
    options: Any  # imprint-module-specific parsed options


def _module(name: str):
    """Resolve an imprint name to its implementation module (or None)."""
    if name == "world-wisdom":
        from . import world_wisdom
        return world_wisdom
    return None


def parse_imprint(data) -> ImprintSpec:
    """Parse the ``imprint:`` block. Raises ConfigError on an unknown imprint or
    an invalid sub-block (validation delegated to the imprint module)."""
    from ..config import ConfigError

    if not isinstance(data, dict):
        raise ConfigError("imprint: must be a mapping")
    name = data.get("name")
    if not name:
        raise ConfigError("imprint.name is required (e.g. 'world-wisdom')")
    mod = _module(name)
    if mod is None:
        raise ConfigError(
            f"imprint.name unknown: {name!r} (known: world-wisdom)")
    return ImprintSpec(name=name, options=mod.parse(data))


def apply_imprint(res, cfg, doc, say=print) -> None:
    """Run the configured imprint's flow transform. No-op when no imprint is
    set (the generic pipeline)."""
    spec = getattr(cfg, "imprint", None)
    if spec is None:
        return
    mod = _module(spec.name)
    if mod is None:  # parse_imprint already validated; defensive
        return
    mod.apply(res, cfg, doc, say)
