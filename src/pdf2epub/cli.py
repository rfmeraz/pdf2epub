"""Command-line interface: init / build / qa."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pdf2epub",
        description="Convert a print-oriented book PDF to a reflowable EPUB 3.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser(
        "init", help="Analyze a PDF; write analysis/ evidence + draft book.yaml"
    )
    p_init.add_argument("pdf_or_folder", type=Path,
                        help="The source PDF, or a package folder containing exactly one PDF")
    p_init.add_argument("--workspace", type=Path, required=True,
                        help="Per-book workspace directory")

    p_build = sub.add_parser("build", help="Deterministic build: book.yaml -> EPUB")
    p_build.add_argument("config", type=Path, help="Path to book.yaml")
    p_build.add_argument("--dump-ir", action="store_true",
                         help="Write intermediate JSON to build/ir/")
    p_build.add_argument(
        "--upto",
        choices=["extract", "flow", "map", "images", "xhtml"],
        help="Stop after the named stage (implies --dump-ir)",
    )
    p_build.add_argument("--no-epubcheck", action="store_true",
                         help="Skip the epubcheck gate")

    p_qa = sub.add_parser("qa", help="QA harness: validate an EPUB against its source PDF")
    p_qa.add_argument("epub", type=Path)
    p_qa.add_argument("--config", type=Path, required=True, help="Path to book.yaml")
    p_qa.add_argument("--reference", type=Path,
                      help="Reference EPUB for the comparison scorecard")

    args = parser.parse_args(argv)

    if args.command == "init":
        from .initcmd import run_init

        return run_init(args.pdf_or_folder, args.workspace)
    if args.command == "build":
        from .build import run_build

        return run_build(
            args.config,
            dump_ir=args.dump_ir or bool(args.upto),
            upto=args.upto,
            epubcheck=not args.no_epubcheck,
        )
    if args.command == "qa":
        from .qa.runner import run_qa

        return run_qa(args.epub, args.config, reference=args.reference)
    return 2


if __name__ == "__main__":
    sys.exit(main())
