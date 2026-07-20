"""corpus runner: discovery, byte semantics, failure continuation, matrix."""


from pdf2epub.corpuscmd import (
    CorpusRow,
    classify_bytes,
    discover_configs,
    render_matrix,
    run_corpus,
)

_MIN = ("schema_version: 1\n"
        "source: {folder: p, pdf: b.pdf}\n"
        "metadata: {title: T, creators: [{name: A}], language: en}\n"
        "output: {slug: %s}\n")


def _mk_corpus(tmp_path, slugs=("alpha", "beta")):
    books = tmp_path / "books"
    for s in slugs:
        ws = books / s
        ws.mkdir(parents=True)
        (ws / "book.yaml").write_text(_MIN % s)
    return books


# ------------------------------------------------------------------ discovery

def test_discovery_sorted_drafts_excluded_variants_included(tmp_path):
    books = _mk_corpus(tmp_path, ("zeta", "alpha"))
    (books / "alpha" / "book.arabic.yaml").write_text(_MIN % "alpha-arabic")
    (books / "alpha" / "book.draft.yaml").write_text("junk")
    (books / "zeta" / "book.draft-new.yaml").write_text("junk")
    got = [str(p.relative_to(books)) for p in discover_configs(books)]
    assert got == ["alpha/book.arabic.yaml", "alpha/book.yaml",
                   "zeta/book.yaml"]


def test_discovery_only_filters_by_dir_or_dir_stem(tmp_path):
    books = _mk_corpus(tmp_path, ("alpha", "beta"))
    (books / "alpha" / "book.arabic.yaml").write_text(_MIN % "alpha-arabic")
    got = [str(p.relative_to(books))
           for p in discover_configs(books, only=["alpha"])]
    assert got == ["alpha/book.arabic.yaml", "alpha/book.yaml"]
    got = [str(p.relative_to(books))
           for p in discover_configs(books, only=["alpha/book.arabic"])]
    assert got == ["alpha/book.arabic.yaml"]


# ------------------------------------------------------------- byte semantics

def test_classify_bytes():
    assert classify_bytes("a", "a", partial=False) == "identical"
    assert classify_bytes("a", "b", partial=False) == "CHANGED"
    assert classify_bytes(None, "b", partial=False) == "NEW"
    # partial build / missing artifact: never grade a stale file
    assert classify_bytes("a", "b", partial=True) == "n/a"
    assert classify_bytes("a", None, partial=False) == "n/a"


# ---------------------------------------------------------------- run_corpus

def _ok_build(epub_bytes=b"EPUB"):
    def build(cfg_path, upto=None, epubcheck=True):
        import yaml
        slug = yaml.safe_load(cfg_path.read_text())["output"]["slug"]
        if upto is None:
            out = cfg_path.parent / "build" / f"{slug}.epub"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(epub_bytes)
        return 0
    return build


def _ok_qa(gates=None):
    calls = []
    def qa(epub, config):
        import json

        import yaml
        calls.append(epub)
        slug = yaml.safe_load(config.read_text())["output"]["slug"]
        gs = gates if gates is not None else [
            {"gate": "1 epubcheck", "ok": True, "detail": []}]
        (epub.parent / f"{slug}.qa.json").write_text(json.dumps(gs))
        return 0 if all(g["ok"] is not False for g in gs) else 1
    qa.calls = calls
    return qa


def test_build_failure_continues_and_run_fails(tmp_path, capsys):
    books = _mk_corpus(tmp_path)
    def build(cfg_path, upto=None, epubcheck=True):
        if "alpha" in str(cfg_path):
            raise RuntimeError("boom")
        return _ok_build()(cfg_path, upto=upto, epubcheck=epubcheck)
    qa = _ok_qa()
    rc = run_corpus(books, build_fn=build, qa_fn=qa)
    out = capsys.readouterr().out
    assert rc == 1
    # alpha failed but beta still built and QA'd (continuation)
    assert len(qa.calls) == 1 and "beta" in str(qa.calls[0])
    assert "build: boom" in out
    assert "1 built" in out and "1 QA PASS" in out


def test_upto_probe_skips_bytes_and_qa(tmp_path, capsys):
    books = _mk_corpus(tmp_path)
    qa = _ok_qa()
    rc = run_corpus(books, upto="flow", build_fn=_ok_build(), qa_fn=qa)
    out = capsys.readouterr().out
    assert rc == 0
    assert qa.calls == []          # a stale artifact is never QA'd
    assert "0 byte-identical" in out and "0 QA PASS" in out


def test_byte_change_reported_then_strict_fails(tmp_path, capsys):
    books = _mk_corpus(tmp_path, ("alpha",))
    old = books / "alpha" / "build" / "alpha.epub"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"OLD")
    rc = run_corpus(books, no_qa=True, build_fn=_ok_build(b"NEW"),
                    qa_fn=_ok_qa())
    assert rc == 0                 # reported for review, not failed
    assert "CHANGED" in capsys.readouterr().out
    old.write_bytes(b"OLD")
    rc = run_corpus(books, no_qa=True, strict=True,
                    build_fn=_ok_build(b"NEW"), qa_fn=_ok_qa())
    assert rc == 1


def test_identical_rebuild_passes_strict(tmp_path):
    books = _mk_corpus(tmp_path, ("alpha",))
    old = books / "alpha" / "build" / "alpha.epub"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"EPUB")
    rc = run_corpus(books, no_qa=True, strict=True, build_fn=_ok_build(),
                    qa_fn=_ok_qa())
    assert rc == 0


def test_failing_gates_named_in_matrix(tmp_path, capsys):
    books = _mk_corpus(tmp_path, ("alpha",))
    qa = _ok_qa(gates=[{"gate": "2 text coverage", "ok": False, "detail": []},
                       {"gate": "18 visual", "ok": None, "detail": []}])
    rc = run_corpus(books, build_fn=_ok_build(), qa_fn=qa)
    out = capsys.readouterr().out
    assert rc == 1
    assert "2 text coverage" in out          # ok=False named
    assert "18 visual" not in out.split("gates-failing")[1]  # advisory not


def test_json_report_written(tmp_path):
    books = _mk_corpus(tmp_path, ("alpha",))
    dest = tmp_path / "corpus.json"
    rc = run_corpus(books, no_qa=True, build_fn=_ok_build(), qa_fn=_ok_qa(),
                    json_out=dest)
    import json
    rows = json.loads(dest.read_text())["rows"]
    assert rc == 0 and rows[0]["slug"] == "alpha"
    assert rows[0]["bytes"] == "NEW" and rows[0]["qa"] == "n/a"


def test_config_error_is_a_row_not_a_crash(tmp_path, capsys):
    books = _mk_corpus(tmp_path, ("alpha",))
    (books / "alpha" / "book.yaml").write_text("schema_version: 1\nbogus_key: 1\n")
    rc = run_corpus(books, build_fn=_ok_build(), qa_fn=_ok_qa())
    assert rc == 1
    assert "config:" in capsys.readouterr().out


def test_matrix_summary_counts():
    rows = [CorpusRow(config="a", build="ok", bytes_="identical", qa="PASS"),
            CorpusRow(config="b", build="FAIL", detail="build: x")]
    lines = render_matrix(rows)
    assert lines[-2].startswith("corpus: 2 config(s) — 1 built, "
                                "1 byte-identical, 1 QA PASS")
    assert lines[-1] == "  b: build: x"


# ------------------------------------------------------ metrics + baseline

def _metrics_build(after_punct_hits):
    """build_fn that also writes the metrics sidecar the real build writes."""
    def build(cfg_path, upto=None, epubcheck=True):
        import json

        import yaml
        slug = yaml.safe_load(cfg_path.read_text())["output"]["slug"]
        bdir = cfg_path.parent / "build"
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / f"{slug}.epub").write_bytes(b"EPUB")
        (bdir / f"{slug}.build_metrics.json").write_text(json.dumps({
            "pages": 200,
            "extract": {"ligature_pads": 0},
            "flow": {"space-rule-after-punct": after_punct_hits},
            "config": {"flow_overrides": 10, "keep_hyphens": 2,
                       "adjudications": 1},
        }))
        return 0
    return build


def test_baseline_seed_then_rule_delta_reported(tmp_path, capsys):
    books = _mk_corpus(tmp_path, ("alpha",))
    rc = run_corpus(books, no_qa=True, build_fn=_metrics_build(5),
                    qa_fn=_ok_qa(), update_baseline=True)
    assert rc == 0
    assert (books / "corpus_baseline.json").exists()
    capsys.readouterr()
    # same inputs, a rule now fires more: the healing/regression signal
    rc = run_corpus(books, no_qa=True, build_fn=_metrics_build(12),
                    qa_fn=_ok_qa())
    out = capsys.readouterr().out
    assert rc == 0
    assert "flow.space-rule-after-punct: 5 -> 12" in out
    assert "10 flow.overrides (5.0/100pp)" in out   # derived scaling line


def test_baseline_incomparable_after_config_edit(tmp_path, capsys):
    books = _mk_corpus(tmp_path, ("alpha",))
    run_corpus(books, no_qa=True, build_fn=_metrics_build(5), qa_fn=_ok_qa(),
               update_baseline=True)
    cfg = books / "alpha" / "book.yaml"
    cfg.write_text(cfg.read_text() + "# a judgment edit\n")
    capsys.readouterr()
    run_corpus(books, no_qa=True, build_fn=_metrics_build(12), qa_fn=_ok_qa())
    out = capsys.readouterr().out
    # a config edit must not read as a rule regression
    assert "not comparable" in out and "5 -> 12" not in out


def test_metrics_without_baseline_prompts_seeding(tmp_path, capsys):
    books = _mk_corpus(tmp_path, ("alpha",))
    rc = run_corpus(books, no_qa=True, build_fn=_metrics_build(5),
                    qa_fn=_ok_qa())
    assert rc == 0
    assert "no baseline entry" in capsys.readouterr().out


# ------------------------------------------------- review #26 regressions

def test_malformed_yaml_is_a_row_not_an_abort(tmp_path, capsys):
    # yaml.safe_load errors are NOT ConfigError — must still continue
    books = _mk_corpus(tmp_path, ("alpha", "beta"))
    (books / "alpha" / "book.yaml").write_text("{{{ not yaml")
    qa = _ok_qa()
    rc = run_corpus(books, build_fn=_ok_build(), qa_fn=qa)
    out = capsys.readouterr().out
    assert rc == 1
    assert "config:" in out
    assert len(qa.calls) == 1 and "beta" in str(qa.calls[0])   # continued


def test_only_subset_baseline_update_merges(tmp_path):
    import json
    books = _mk_corpus(tmp_path, ("alpha", "beta"))
    run_corpus(books, no_qa=True, build_fn=_metrics_build(5), qa_fn=_ok_qa(),
               update_baseline=True)
    run_corpus(books, no_qa=True, only=["alpha"],
               build_fn=_metrics_build(9), qa_fn=_ok_qa(),
               update_baseline=True)
    entries = json.loads((books / "corpus_baseline.json").read_text())["entries"]
    # the un-run config's entry survives; the run one is updated
    assert any("beta" in k for k in entries)
    alpha = next(v for k, v in entries.items() if "alpha" in k)
    assert alpha["metrics"]["flow"]["space-rule-after-punct"] == 9


def test_extract_only_probe_ignores_stale_metrics(tmp_path, capsys):
    import json
    books = _mk_corpus(tmp_path, ("alpha",))
    bdir = books / "alpha" / "build"
    bdir.mkdir(parents=True)
    (bdir / "alpha.build_metrics.json").write_text(json.dumps(
        {"pages": 200, "flow": {"space-rule-after-punct": 99},
         "config": {"flow_overrides": 1}}))
    rc = run_corpus(books, upto="extract", build_fn=_ok_build(),
                    qa_fn=_ok_qa(), update_baseline=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "99" not in out                      # stale counters not reported
    entries = json.loads((books / "corpus_baseline.json").read_text())["entries"]
    assert entries == {}                        # and never seeded as fresh


def test_unpinned_pdf_swap_reads_inputs_changed(tmp_path, capsys):
    # _MIN has no source.sha256 pin: the fingerprint must come from the FILE
    books = _mk_corpus(tmp_path, ("alpha",))
    pdf = books / "alpha" / "p" / "b.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"PDF-v1")
    run_corpus(books, no_qa=True, build_fn=_metrics_build(5), qa_fn=_ok_qa(),
               update_baseline=True)
    pdf.write_bytes(b"PDF-v2-different")
    capsys.readouterr()
    run_corpus(books, no_qa=True, build_fn=_metrics_build(12), qa_fn=_ok_qa())
    out = capsys.readouterr().out
    assert "not comparable" in out and "5 -> 12" not in out
