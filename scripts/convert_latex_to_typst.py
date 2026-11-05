#!/usr/bin/env python3
"""Convert the LaTeX thesis starter into the Typst starter's manuscript.

Usage::

    python3 scripts/convert_latex_to_typst.py --source ../thesis_template_latex \\
        --target ../thesis_template_typst [--check]

The converter reads the authoritative LaTeX project, inventories every object
from the raw sources, then renders readable Typst that uses the target
``template.typ`` helper API.  It writes the manuscript (``main.typ``,
``metadata.json``, ``frontmatter/``, ``chapters/``, ``backmatter/``,
``lampiran/``) and copies the referenced assets; it never writes layout files,
build scripts or the LaTeX-only support files (``.latexmkrc``,
``overleaf.txt``).

Unsupported input fails with the file, line and construct instead of being
dropped.  ``--check`` regenerates in memory and compares without writing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from thesis_tools.common import ConversionError, ToolError  # noqa: E402
from thesis_tools.to_typst import convert_latex_to_typst  # noqa: E402
from thesis_tools.writer import apply_result  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a LaTeX thesis project into a Typst thesis project."
    )
    parser.add_argument("--source", required=True, type=Path, help="LaTeX project directory")
    parser.add_argument("--target", required=True, type=Path, help="Typst project directory")
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate in memory and compare with the target without writing",
    )
    args = parser.parse_args(argv)
    try:
        result = convert_latex_to_typst(args.source, args.target)
        print(f"latex->typst: {result.summary()}")
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
