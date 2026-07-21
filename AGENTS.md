# Repository Guidelines

## Project Structure & Module Organization

Application code lives in `src/pdf2epub/`. The CLI and orchestration modules sit at the package root; PDF extraction is in `extract/`, EPUB generation primitives are in `core/`, and quality gates are in `qa/`. Tests are flat modules under `tests/`, generally mirroring their implementation (`tests/test_nav.py` covers navigation). `books/<slug>/` contains tracked conversion fixtures: source PDFs in `package/`, configuration in `book.yaml`, evidence in `analysis/`, cover art in `assets/`, and final EPUBs in `build/`. Design and QA rationale belong in `specs/`; reusable utilities belong in `scripts/`.

## Build, Test, and Development Commands

Use the repository's Python 3.12 environment under `~/pyenv`:

```bash
bash scripts/bootstrap.sh              # install dependencies and external tooling
~/pyenv/bin/pip install -e .           # install the CLI in editable mode
~/pyenv/bin/pytest -q                  # run the complete unit-test suite
~/pyenv/bin/pytest -q tests/test_nav.py # run one focused test module
~/pyenv/bin/pdf2epub build books/<slug>/book.yaml
~/pyenv/bin/pdf2epub qa books/<slug>/build/<slug>.epub --config books/<slug>/book.yaml
~/pyenv/bin/pdf2epub validate books/<slug>/book.yaml   # config checks without a build
~/pyenv/bin/pdf2epub corpus            # rebuild + QA every tracked config; byte-compare + counter deltas
```

Use `pdf2epub init` to generate analysis and a draft configuration. A completed conversion must report `epubcheck: clean`, `Overall: PASS`, and a clean proofread pass (`pdf2epub proofread` + the proofread-epub skill). Before shipping any change to a global rule (flow join, textfix, emitter), run `pdf2epub corpus`: builds are byte-reproducible, so any byte change in a shipped EPUB is a behavior change that must be explained. After changing pipeline code, re-seed the tracked counter baseline (`corpus --update-baseline`) in the same commit, or later runs will misattribute the drift.

## Coding Style & Naming Conventions

Follow standard Python conventions: four-space indentation, `snake_case` for functions and modules, `PascalCase` for classes, and uppercase constants. Prefer type hints, small deterministic functions, and `pathlib.Path` for filesystem work. Keep imports grouped as standard library, third-party, then local. No formatter or linter is currently configured, so match neighboring code and keep diffs focused. Preserve byte-reproducibility: do not introduce timestamps, randomness, or environment-dependent output.

## Testing Guidelines

Tests use pytest and must be named `test_*.py`; test functions should describe observable behavior. Add or update focused unit tests for pipeline changes. For print-verified per-book fixes, also update `books/<slug>/qa_assertions.yaml` so QA gate 24 catches regressions — the fixture is mandatory per book (gate 24 fails when it is missing; an authored `[]` records "no print-verified fixes yet"). Never rewrite source-book wording to satisfy a test; fixes must be deterministic transformations or explicit configuration.

## Commit & Pull Request Guidelines

Recent commits use concise, imperative subjects, often scoped by subsystem, such as `nav: nest by ancestor depth` or `Add linked index locators`. Keep commits single-purpose and do not add AI-attribution trailers. Pull requests should explain the problem, implementation, affected books or stages, and verification commands. Link relevant issues; include visual QA evidence for rendering changes and call out regenerated EPUBs or configuration changes.

## Security & Content Integrity

Treat archived source PDFs as read-only. Never embed proprietary or PDF-extracted fonts; use OFL system fonts. Surface ambiguous constructs in `build/warnings.md` rather than silently dropping content.
