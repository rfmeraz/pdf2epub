# Reliability & engineering-hardening — the trust substrate

Status: **§1–§4 SHIPPED 2026-07-12**; §5 (process limits) deferred (threat-model-conditional),
§6 (maintainability) deferred (gate on characterization tests). Sourced from an external
implementation review (2026-07-12, recorded in NOTES.md) that read the code and ran focused
experiments. These are NOT commercial-parity *features* (see commercial-parity.md) and NOT QA
*gates* (see qa-methodology.md §3) — they are the engineering substrate that makes the
project's own central claims ("validated", "byte-reproducible", "config records reviewed
judgment") true rather than aspirational. Every item below is confirmed against the code with
line cites; read one before re-litigating it.

**Shipped (§1–§4):** shared semantic validator in `load_config(require_complete=)` (FILL-ME-IN
rejection, `schema_version`, structural page-range validation) + `pdf2epub validate`; dead
fields removed, `include_ncx` implemented with stale-`toc.ncx` removal; transactional promotion
where the EPUB is the SINGLE atomic `os.replace` commit and the manifest is an
atomically-written sidecar (all fallible work — epubcheck, input recheck, manifest generate +
write — precedes promotion), plus an immutable `provenance.py` manifest (book.yaml hash of the
EXACT parsed bytes + source-PDF path/hash, snapshotted before processing and rechecked before
promotion; tri-state epubcheck; tool/dep versions; git rev + dirty flag; release epoch) and a
`pdf2epub verify` that checks the EPUB↔manifest hash AND book.yaml/source-PDF drift-or-absence;
`metadata.identifier` (validated UUID/urn; distinct id for the BoK arabic variant) +
`metadata.released` → `dcterms:modified`; hermetic tests (sibling-repo test removed, Chrome
skip env-gated), pytest markers, hashed `requirements.lock`, ruff (E4/E7/E9/F/I), and portable
GitHub Actions CI. Diverged from the sketch where the code forced it (below), and **five rounds
of implementation review (#1–#5) refined the transactional/provenance guarantees**: a
two-rename-with-rollback design was dropped for the single-commit + detected-sidecar model after
the rollback logic proved to add more failure modes than it closed. The residual (a process-kill
between the two same-dir renames) is `verify`-detected, not silently verifiable; true joint
atomicity would need directory indirection, which conflicts with the git-tracked fixed EPUB
path. The `pages.*` folio cross-check shipped OFF (noisy), as sketched.

**Framing.** The pipeline's value proposition is *trustworthiness through independence*:
evidence → recorded judgment → deterministic build → independent QA → proofread. The review
found that several load-bearing promises in that chain are unenforced or leaky. None is a
routine failure in the human-in-the-loop workflow today — they are latent holes that turn a
regression, a stale artifact, or a silently-ignored judgment into a *believable-but-wrong*
result. That is exactly the failure mode the whole architecture exists to prevent.

The genuinely-highest-value review finding — a page-aligned fidelity gate that would catch
reordered/duplicated content the current recall-only coverage cannot — is **not here**; it is
a QA gate, spec'd as [qa-methodology.md §3](qa-methodology.md). This doc is the build/test/
config/provenance infrastructure around it.

---

## §1 Config integrity — placeholders, dead fields, validation  (priority: high; cheap; protects config-as-judgment)

The strongest argument in this whole doc: **book.yaml is the record of reviewed human+agent
judgment**, so a config value that silently does nothing — or a placeholder that ships — is
not a cosmetic bug, it is a judgment believed-recorded but not applied. Three confirmed leaks:

**(a) FILL-ME-IN is unenforced.** `initcmd.py:5` promises "A FILL-ME-IN left in place fails
the build loudly — never silently." No such check exists: a repo-wide grep for `FILL-ME-IN`
in `src/` hits only `initcmd.py` (docstring + the draft-*writing* strings). `config.py`
`load_config` has no placeholder rejection. Concretely, 3 of the 5 tracked
`books/*/book.draft.yaml` load *successfully* with `metadata.title: FILL-ME-IN` and would ship
it as `<dc:title>`; `images.figure_pages[].alt_template: "FILL-ME-IN…"` loads as ordinary alt
text. The only current catch is *incidental* — a `glyphs.pua_map`/`flow.overrides`
`action: FILL-ME-IN` trips the action-enum check (`config.py:592`) with a misleading "action
invalid" message, not the promised placeholder error.

**(b) Seven dead config fields** — parsed into `cfg`, never read by any consumer:
`pages.front/body/back` (`config.py:471-473`), `furniture.bottom_band` (`488`; its sibling
`top_band` *is* consumed at `flowbuilder.py:257`), `images.alt` (`625`), `images.decorative`
(`626`), `output.include_ncx` (`760`). `include_ncx: false` is the sharpest example: the
packager unconditionally writes the NCX (`packager.py:221`), manifests it (`226`), and
hardwires `<spine toc="ncx">` (`127`) — the flag is a no-op. Figure alt/decorative come from
the flow object (`emit_xhtml.py:582`, tracing to `figure_regions`/`figure_pages`), never from
these dicts.

**Design.**
- **Recursive placeholder rejection** at the end of `load_config`: walk the parsed mapping;
  any string equal to (or containing) `FILL-ME-IN` raises `ConfigError` naming the dotted key
  path. Fulfills the initcmd promise; makes drafts fail loudly until finalized.
- **No silent no-op fields.** For each of the seven: either *implement* it (only
  `pages.front/body/back` have a plausible use — front/body/back partitioning is currently
  inferred from folios; wiring these as explicit overrides is real work, defer) or *remove the
  parse + reject the key* via the existing `_check_keys` allow-lists so setting it errors
  rather than lies. Recommended: remove all seven now (none encodes live judgment), reintroduce
  `pages.*` only if/when partitioning override is actually built.
- **`pdf2epub config validate <book.yaml>`** — a standalone subcommand running the full
  loader + required-metadata checks (title/creators/language present and non-placeholder)
  without a build. Add `schema_version:` to book.yaml so the loader can refuse configs from a
  newer/older grammar with a clear message.
- **Do NOT** rewrite the ~770-line hand parser into Pydantic in one pass (the review agrees):
  the manual parser's per-key `_check_keys` + error messages are an asset. Add the three checks
  above incrementally; a generated JSON Schema for editor tooling can come later.

**Integration**: `config.py` (recursive placeholder walk, `schema_version`, remove dead
parses + drop keys from `_check_keys` sets), `cli.py` (`config validate` subcommand),
`initcmd.py` (its promise is now real), tests (a draft with `title: FILL-ME-IN` must fail
load; every removed key must now error).

**Acceptance**: all five `book.draft.yaml` fail load with a FILL-ME-IN error; the five
finalized `book.yaml` still load and build byte-identically; setting any removed field errors;
`config validate` passes on the five finalized configs and fails on the drafts.

---

## §2 Transactional builds + provenance manifest  (priority: medium-high; cheap)

**Problem.** The build is not atomic. `build.py:52-54` deletes `build/oebps/` at the start but
leaves the previous final `.epub` untouched; `packager.py:247-248` writes the zip *directly*
to the final `{slug}.epub` path (no temp, no `os.replace`); `build.py:146-158` runs epubcheck
*after* the file is already written and merely `return 1`s on failure — so a failed epubcheck
leaves an **invalid** EPUB at the canonical path, and a crash in any earlier stage leaves a
**stale** one. Either can be mistaken for the current result. There is no sidecar recording
what produced the file. (The source-PDF sha256 pin already exists at `build.py:61-66` — half
the manifest machinery is present.)

**Design.**
- Build the EPUB into a temp path under `build/` (e.g. `.{slug}.epub.tmp`); run epubcheck on
  it; `os.replace()` to `{slug}.epub` **only** after epubcheck (and any gating step) passes.
  On failure, remove the temp and leave the prior good EPUB in place (or remove it too and
  fail loudly — decide at implementation; the invariant is "the canonical `.epub` is always a
  build that passed epubcheck, or absent").
- Emit `build/{slug}.manifest.json` (byte-reproducible; no wall-clock) recording: source PDF
  sha256 (already computed), book.yaml sha256, `schema_version`, code revision (git describe,
  passed in — no subprocess at import), Python + dependency versions (PyMuPDF/poppler/lxml/
  Pillow/fonttools), external-tool versions (epubcheck, Calibre, Chrome, fonts) when present,
  output EPUB sha256, and the QA verdict + a release epoch (see §3 of this doc — reuse the same
  explicit build epoch, NOT `Date.now()`). This is the provenance the "byte-reproducible"
  claim implies but doesn't currently prove.

**Integration**: `build.py` (temp path, `os.replace`, manifest write after QA),
`core/packager.py` (return temp path), a small `provenance.py` (version probing, reused by the
manifest and by any tool-version logging), NOTES.md verification baselines.

**Acceptance**: a deliberately-broken build (force an epubcheck failure) leaves the prior good
`.epub` and NO new one at the canonical path; a clean build writes the manifest; two clean
builds of the same inputs produce byte-identical `.epub` AND byte-identical manifest.

---

## §3 Package identity & revision metadata  (priority: medium; small; correctness)

**Problem.** Two metadata-correctness bugs (`core/packager.py`):
- **Slug-only UUID fallback** (`58-64`): `uuid.uuid5(NAMESPACE_URL, f"pdf2epub:{cfg.slug}")` —
  two unrelated books that happen to share a slug get *identical* `urn:uuid` identifiers (also
  reused as the NCX `dtb:uid`, `143`). An EPUB identifier must be globally unique and
  persistent across revisions of *the same* book, not across *different* books with the same
  short name.
- **`dcterms:modified` from the print year** (`99-100`): `stamp = f"{cfg.date or '2026'}-01-01…"`
  where `cfg.date` is the *publication* date (also emitted as `<dc:date>`). `dcterms:modified`
  must describe the EPUB *revision*, not the original print date.

**Design.**
- Add an explicit persistent `metadata.identifier:` (a UUID) to book.yaml; `init` generates a
  deterministic one *recorded into config* (so it's stable and reviewable), used when no
  `isbn_epub`. Never derive identity from slug alone.
- Derive `dcterms:modified` from an explicit reproducible **release epoch** — `metadata.
  released:` (a date/timestamp) or `source.git_rev`-tied epoch — NOT the print year and NOT
  wall-clock (byte-reproducibility). Same epoch feeds the §2 manifest.

**Integration**: `config.py` (`metadata.identifier`, `metadata.released`), `initcmd.py`
(generate + record identifier), `core/packager.py:58-64,99-100` (consume both).

**Acceptance**: two books with the same slug but distinct configs get distinct identifiers;
`dcterms:modified` reflects the recorded release epoch; builds stay byte-reproducible.

---

## §4 Hermetic tests + CI  (priority: high; the substrate that keeps §1–§3 from regressing)

**Problem.** The documented `pytest -q` is neither clean nor hermetic:
- `tests/test_lang.py:35` imports the **sibling repo** (`from idml2epub.mapping.styles import
  class_hint`) — a hard cross-repo dependency the CLAUDE.md doctrine ("never edit idml2epub
  from here") otherwise forbids; it fails wherever the sibling isn't checked out.
- `tests/test_cdp.py` skips only when Chrome is *absent* (`find_chrome() is None`) — installed-
  but-unlaunchable Chrome (sandboxed/headless-broken CI) *fails* instead of skipping.
- No CI workflow, no dependency lockfile, no linter, no type-checker, no coverage config exist
  (`pyproject.toml` pins only loose `>=` ranges).

**Design.**
- **Two near-free fixes now** (they're bugs): vendor the tiny `class_hint` logic under test (or
  gate that test behind an explicit `idml2epub`-present marker + skip) so the unit suite has no
  sibling dependency; make `test_cdp` skip on launch failure, not just absence.
- **Pytest markers / tiers**: `unit` (no external programs — default CI), `integration`
  (poppler/PyMuPDF/epubcheck), `browser` (Chrome), `corpus` (real-book builds + QA). Mark
  existing tests; `-m unit` must be hermetic and fast.
- **CI** (GitHub Actions or equivalent): run `unit` on every push; `integration` on a runner
  with the toolchain; `corpus` nightly/manual (slow). Add a lockfile (uv/pip-tools) for
  reproducible installs, a linter (ruff) and a type-checker (mypy, incremental) — the
  byte-reproducibility and provenance claims want a pinned, checked toolchain.

**Integration**: `tests/test_lang.py`, `tests/test_cdp.py`, `pyproject.toml`
(`[tool.pytest.ini_options] markers`, ruff/mypy config), new `.github/workflows/*.yml`, a
lockfile, `scripts/bootstrap.sh` (document the tiers).

**Acceptance**: `pytest -q -m unit` passes with the sibling repo absent and no Chrome; the
existing full suite passes under its tiers; CI is green on a clean checkout.

---

## §5 External-process resource limits  (priority: low; threat-model-conditional)

**Problem (scoped).** Three subprocess sites run unbounded (no `timeout=`, unbounded
`capture_output`): poppler `pdftotext` (`extract/__init__.py:37`), java epubcheck
(`core/qa_epubcheck.py:26-30`), Calibre `ebook-convert` (`kindle.py:56-57`). **Correction to
the review:** the Chrome/CDP render path it also flagged is *already* well-bounded — output to
`DEVNULL`, every CDP op deadline-timed (`cdp.py`), render clipped to 600×≤3000 CSS px
(`visual.py`), force-killed on exit. Leave it alone.

**Why low.** The workflow is "a human drops a *trusted* PDF"; a hostile/malformed PDF wedging
poppler is not today's threat model. This is hardening for an untrusted-input future (batch
service, public intake), not a current-workflow correctness gap.

**Design.** Add `timeout=` (generous, per-tool) and bounded output capture to the three
`subprocess.run` sites, with a clear `SystemExit`/skip on timeout. Consider a page-count/file-
size ceiling at extract when untrusted intake becomes real. Do this *when* the threat model
changes; note it here so it isn't rediscovered.

**Integration**: the three call sites + a shared `_run(cmd, timeout=…)` helper.

---

## §6 Concentration / maintainability  (priority: cross-cutting; gate on characterization tests, not urgent)

The code is thoughtful, heavily commented, and unusually test-rich (provenance headers and
stale-judgment detection are strengths). The risk is *concentration*: `flowbuilder.py` ~1994
lines, the emitter ~800, the config parser ~768, the QA runner's `run_qa` a ~350-line
orchestration function. Future table/RTL/OCR work threading through these risks destabilizing
prose conversion.

**Not a rewrite.** First strengthen characterization tests around the seams, *then* extract
behind stable interfaces: furniture/page preprocessing, footnote detection, semantic-block
classification, paragraph joining, anchor placement, and — highest leverage for the QA work in
qa-methodology.md — **individual QA gates behind a common gate interface** (registry of
`name → callable(ctx) -> (ok, lines)`), which also makes §3's new fidelity gate and future
gates additive. Sequence this *after* §4 (CI + characterization tests give the safety net) and
*alongside* the first big new content feature, never as a standalone big-bang.

## Non-goals

- Rewriting the config parser or flowbuilder wholesale (incremental extraction only).
- Bounding the CDP path (already bounded — see §5).
- A provenance manifest that embeds wall-clock or non-reproducible fields (byte-reproducibility
  is non-negotiable; the manifest uses source hashes + an explicit release epoch).
