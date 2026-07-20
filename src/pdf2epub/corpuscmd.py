"""corpus: rebuild + QA every tracked book config and report the matrix.

Mechanizes the probe-all-configs discipline (NOTES.md: "The corpus is the
test — every rule probed against all configs BEFORE it was written"): one
command rebuilds each tracked config in place, byte-compares the shipped
EPUB (builds are byte-reproducible, so a byte change IS the behavior
change), runs the QA gates, and reports the per-config matrix.

Contracts:
- Membership is the tracked convention: ``books/*/book*.yaml`` minus drafts
  (the same filter CI uses) — no separate corpus list to keep in sync.
- A build or QA failure marks that config and CONTINUES; the run exits
  nonzero at the end (this is what CI gates on).
- ``--upto`` stops the build early: the old EPUB is untouched, so bytes and
  QA report n/a — never compare a stale artifact.
- Byte changes are REPORTED, not failed: at HEAD after an intentional code
  fix a change is the expected cross-book healing signal. ``--strict``
  (local use) exits nonzero on any change. Byte-compare is authoritative
  only on the machine whose fonts built the shipped EPUBs.
- Provenance manifests hash the dirty worktree, so sequential in-place
  rebuilds churn them by order; the EPUB byte-compare is the signal,
  manifest diffs are not.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path


def discover_configs(books_dir: Path, only: list[str] | None = None) -> list[Path]:
    """Tracked corpus membership: sorted books/*/book*.yaml, drafts excluded.
    ``only`` filters by workspace dir name or ``dir/stem``."""
    cfgs = [p for p in sorted(books_dir.glob("*/book*.yaml"))
            if "draft" not in p.name]
    if only:
        want = set(only)
        cfgs = [p for p in cfgs
                if p.parent.name in want or f"{p.parent.name}/{p.stem}" in want]
    return cfgs


def _sha(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify_bytes(pre: str | None, post: str | None,
                   partial: bool) -> str:
    """identical | CHANGED | NEW | n/a for one config's shipped EPUB."""
    if partial or post is None:
        return "n/a"           # nothing (re)shipped — never grade a stale file
    if pre is None:
        return "NEW"
    return "identical" if pre == post else "CHANGED"


@dataclass
class CorpusRow:
    config: str
    slug: str = "?"
    build: str = "n/a"          # ok | FAIL | n/a
    bytes_: str = "n/a"         # identical | CHANGED | NEW | n/a
    qa: str = "n/a"             # PASS | FAIL | n/a
    failing_gates: list[str] = field(default_factory=list)
    detail: str = ""            # one-line failure reason
    config_sha256: str = ""
    pdf_sha256: str = ""
    metrics: dict | None = None  # <slug>.build_metrics.json, when produced

    def to_dict(self) -> dict:
        return {"config": self.config, "slug": self.slug, "build": self.build,
                "bytes": self.bytes_, "qa": self.qa,
                "failing_gates": self.failing_gates, "detail": self.detail,
                "metrics": self.metrics}


BASELINE_VERSION = 1


def _flat_counters(metrics: dict) -> dict[str, int]:
    """One flat counter namespace per config: extract.* + flow.* keys."""
    out = {}
    for group in ("extract", "flow"):
        for k, v in (metrics.get(group) or {}).items():
            out[f"{group}.{k}"] = v
    return out


def metric_deltas(baseline_entry: dict | None, row: CorpusRow) -> list[str]:
    """Human-readable per-counter changes vs the tracked baseline. Inputs
    (config hash / PDF sha) changing makes counts incomparable — say so
    instead of reporting judgment edits as rule regressions."""
    if row.metrics is None:
        return []
    if baseline_entry is None:
        return ["no baseline entry (run --update-baseline to seed)"]
    if (baseline_entry.get("config_sha256") != row.config_sha256
            or baseline_entry.get("pdf_sha256") != row.pdf_sha256):
        return ["inputs changed since baseline — counters not comparable "
                "(re-seed with --update-baseline)"]
    old = _flat_counters(baseline_entry.get("metrics") or {})
    new = _flat_counters(row.metrics)
    out = []
    for k in sorted(set(old) | set(new)):
        a, b = old.get(k, 0), new.get(k, 0)
        if a != b:
            out.append(f"{k}: {a} -> {b}")
    return out


def derived_scaling(row: CorpusRow) -> str:
    """Cheap operational-scaling line: judgment volume per book size."""
    m = row.metrics or {}
    pages = m.get("pages") or 0
    cfg_m = m.get("config") or {}
    ov = cfg_m.get("flow_overrides", 0)
    per100 = f"{ov / pages * 100:.1f}" if pages else "?"
    return (f"{pages}pp, {ov} flow.overrides ({per100}/100pp), "
            f"{cfg_m.get('keep_hyphens', 0)} keep_hyphens, "
            f"{cfg_m.get('adjudications', 0)} adjudications")


def render_matrix(rows: list[CorpusRow]) -> list[str]:
    heads = ("config", "build", "bytes", "qa", "gates-failing")
    cells = [(r.config, r.build, r.bytes_, r.qa,
              ",".join(r.failing_gates) or "-") for r in rows]
    widths = [max(len(h), *(len(c[i]) for c in cells)) if cells else len(h)
              for i, h in enumerate(heads)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    out = [fmt.format(*heads)]
    out += [fmt.format(*c) for c in cells]
    n = len(rows)
    built = sum(r.build == "ok" for r in rows)
    ident = sum(r.bytes_ == "identical" for r in rows)
    passed = sum(r.qa == "PASS" for r in rows)
    out.append(f"corpus: {n} config(s) — {built} built, "
               f"{ident} byte-identical, {passed} QA PASS")
    for r in rows:
        if r.detail:
            out.append(f"  {r.config}: {r.detail}")
    return out


def baseline_path(books_dir: Path) -> Path:
    return books_dir / "corpus_baseline.json"


def load_baseline(books_dir: Path) -> dict:
    p = baseline_path(books_dir)
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    if data.get("baseline_version") != BASELINE_VERSION:
        return {}
    return data.get("entries", {})


def write_baseline(books_dir: Path, rows: list[CorpusRow]) -> Path:
    entries = {r.config: {"config_sha256": r.config_sha256,
                          "pdf_sha256": r.pdf_sha256,
                          "metrics": r.metrics}
               for r in rows if r.metrics is not None}
    p = baseline_path(books_dir)
    p.write_text(json.dumps({"baseline_version": BASELINE_VERSION,
                             "entries": entries},
                            indent=1, sort_keys=True, ensure_ascii=False)
                 + "\n")
    return p


def run_corpus(books_dir: Path, *, only: list[str] | None = None,
               upto: str | None = None, no_qa: bool = False,
               epubcheck: bool = True, strict: bool = False,
               json_out: Path | None = None, update_baseline: bool = False,
               build_fn=None, qa_fn=None) -> int:
    """Rebuild + QA the corpus; return 0 only if every config builds and
    passes QA (and, with --strict, ships byte-identical)."""
    from .config import ConfigError, load_config
    if build_fn is None:
        from .build import run_build as build_fn
    if qa_fn is None:
        from .qa.runner import run_qa as qa_fn

    cfgs = discover_configs(books_dir, only)
    if not cfgs:
        print(f"corpus: no configs under {books_dir}"
              + (f" matching {only}" if only else ""))
        return 1

    rows: list[CorpusRow] = []
    for cfg_path in cfgs:
        row = CorpusRow(config=str(cfg_path))
        rows.append(row)
        print(f"== {cfg_path} ==", flush=True)
        try:
            cfg = load_config(cfg_path, require_complete=True)
        except ConfigError as e:
            row.build = "FAIL"
            row.detail = f"config: {e}"
            continue
        row.slug = cfg.slug
        row.config_sha256 = cfg.config_sha256
        row.pdf_sha256 = cfg.sha256
        epub = cfg.build_dir / f"{cfg.slug}.epub"
        pre = _sha(epub)
        try:
            rc = build_fn(cfg_path, upto=upto, epubcheck=epubcheck)
        except (Exception, SystemExit) as e:   # one broken book never stops the run
            rc = 1
            row.detail = f"build: {e}"
        if rc != 0:
            row.build = "FAIL"
            row.detail = row.detail or "build: nonzero exit"
            continue                           # never QA/grade a stale artifact
        row.build = "ok"
        row.bytes_ = classify_bytes(pre, _sha(epub), partial=bool(upto))
        mpath = cfg.build_dir / f"{cfg.slug}.build_metrics.json"
        if mpath.exists():
            row.metrics = json.loads(mpath.read_text())
        if upto or no_qa:
            continue
        try:
            qrc = qa_fn(epub, cfg_path)
        except (Exception, SystemExit) as e:
            row.qa = "FAIL"
            row.detail = f"qa: {e}"
            continue
        row.qa = "PASS" if qrc == 0 else "FAIL"
        sidecar = cfg.build_dir / f"{cfg.slug}.qa.json"
        if sidecar.exists():
            gates = json.loads(sidecar.read_text())
            row.failing_gates = [g["gate"] for g in gates if g["ok"] is False]

    lines = render_matrix(rows)
    print()
    for ln in lines:
        print(ln)
    baseline = load_baseline(books_dir)
    printed_head = False
    for r in rows:
        if r.metrics is None:
            continue
        deltas = metric_deltas(baseline.get(r.config), r)
        if not printed_head:
            print("\nmetrics (judgment volume; counter deltas vs baseline):")
            printed_head = True
        print(f"  {r.config}: {derived_scaling(r)}")
        for d in deltas:
            print(f"    {d}")
    if update_baseline:
        print(f"baseline updated: {write_baseline(books_dir, rows)}")
    if json_out is not None:
        json_out.write_text(json.dumps(
            {"rows": [r.to_dict() for r in rows]}, indent=1,
            ensure_ascii=False) + "\n")
        print(f"json: {json_out}")

    failed = any(r.build == "FAIL" or r.qa == "FAIL" for r in rows)
    changed = any(r.bytes_ in ("CHANGED", "NEW") for r in rows)
    if changed and not strict:
        print("byte changes are for review (expected after an intentional "
              "code fix); --strict makes them fail")
    return 1 if failed or (strict and changed) else 0
