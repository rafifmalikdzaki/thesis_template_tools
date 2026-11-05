#!/usr/bin/env python3
"""Convert the Typst thesis starter into the LaTeX starter's manuscript.

Usage::

    python3 scripts/convert_typst_to_latex.py --source ../thesis_template_typst \\
        --target ../thesis_template [--check]

Best-effort reverse conversion of the constructs the Typst starter uses.  The
converter writes the class-based, engine-agnostic LaTeX project: the
manuscript, ``metadata.tex``, the canonical ``thesis.cls`` and
``thesis-layout.sty`` templates, an engine-neutral ``.latexmkrc`` (pdfLaTeX,
XeLaTeX and LuaLaTeX command lines, no ``$pdf_mode``) and ``overleaf.txt``
(pdfLaTeX recommended, XeLaTeX/LuaLaTeX selectable).  The target must be the
LaTeX starter — class-based (``thesis.cls``) or legacy (``preamble.tex``) —
because it supplies the manuscript structure and assets.

Unsupported constructs fail with file, line and construct; ``--check``
regenerates in memory and compares without writing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from thesis_tools.common import ConversionError, ToolError  # noqa: E402
from thesis_tools.to_latex import convert_typst_to_latex  # noqa: E402
from thesis_tools.writer import apply_result  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a Typst thesis project into a LaTeX thesis project."
    )
    parser.add_argument("--source", required=True, type=Path, help="Typst project directory")
    parser.add_argument("--target", required=True, type=Path, help="LaTeX project directory")
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate in memory and compare with the target without writing",
    )
    args = parser.parse_args(argv)
    try:
        result = convert_typst_to_latex(args.source, args.target)
        print(f"typst->latex: {result.summary()}")
        return apply_result(result, args.target, args.check)
    except ConversionError as error:
        print(f"error: {error}", file=sys.stderr)
        print("conversion stopped; the construct above has no supported mapping", file=sys.stderr)
        return 2
    except ToolError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
