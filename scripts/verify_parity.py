#!/usr/bin/env python3
"""Verify cross-engine parity between a LaTeX and a Typst thesis project.

Usage::

    python3 scripts/verify_parity.py --latex ../thesis_template \\
        --typst ../thesis_template_typst [--json]

Checks metadata agreement, object inventory and identifier order, table numeric
payloads (from sources and, when both PDFs exist, from ``pdftotext``), listing
bodies, label/reference resolution, normalised rendered-text agreement and the
administrative pages.  Rendered checks are skipped cleanly when the projects
have not been built or poppler is unavailable; the source checks always run.

Exit codes: 0 parity, 1 mismatch, 2 unusable input.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from thesis_tools.common import ToolError  # noqa: E402
from thesis_tools.parity import report_json, report_text, verify  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify parity between a LaTeX and a Typst thesis project."
    )
    parser.add_argument("--latex", required=True, type=Path, help="LaTeX project directory")
    parser.add_argument("--typst", required=True, type=Path, help="Typst project directory")
    parser.add_argument(
        "--json", action="store_true", help="print a machine-readable report instead of text"
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.005,
        help="allowed fraction of differing prose words in the rendered PDFs (default 0.005)",
    )
    args = parser.parse_args(argv)
    if not args.latex.is_dir():
        print(f"error: {args.latex} is not a directory", file=sys.stderr)
        return 2
    if not args.typst.is_dir():
        print(f"error: {args.typst} is not a directory", file=sys.stderr)
        return 2
    try:
        report = verify(args.latex, args.typst, args.tolerance)
    except ToolError as error:
        print(f"parity: error: {error}", file=sys.stderr)
        return 2
    print(report_json(report) if args.json else report_text(report, args.latex, args.typst))
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
