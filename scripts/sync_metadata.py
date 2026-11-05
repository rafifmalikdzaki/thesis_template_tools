#!/usr/bin/env python3
"""Keep the LaTeX and Typst administrative metadata in agreement.

Usage::

    python3 scripts/sync_metadata.py --latex ../thesis_template \\
        --typst ../thesis_template_typst [--check] [--from latex|typst]

The LaTeX starter stores the values as ``\\newcommand{\\Thesis...}{...}``
definitions in ``metadata.tex``; the Typst starter stores the same values in
``metadata.json``.  The synchroniser reads either file, validates the fixed key
contract, escapes values for LaTeX, and writes both representations.

* When the two files agree, nothing is rewritten (hand formatting is kept), so
  re-running the command is a no-op.
* When they disagree, ``--from`` chooses the authority; the default is the
  LaTeX project.  ``--check`` reports the drift key by key and exits non-zero
  without writing anything.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from thesis_tools.common import (  # noqa: E402
    KEY_ORDER,
    ToolError,
    load_metadata_json,
    parse_metadata_tex,
    read_text,
    render_metadata_json,
    render_metadata_tex,
    write_text_atomic,
)


def _metadata_paths(latex: Path, typst: Path) -> tuple[Path, Path]:
    latex_file = latex / "metadata.tex"
    if not latex_file.is_file() and (latex / "latex" / "metadata.tex").is_file():
        latex_file = latex / "latex" / "metadata.tex"
    typst_file = typst / "metadata.json"
    if not typst_file.is_file() and (typst / "typst" / "metadata.json").is_file():
        typst_file = typst / "typst" / "metadata.json"
    return latex_file, typst_file


def _read_values(latex_file: Path, typst_file: Path) -> tuple[dict | None, dict | None]:
    latex_values = None
    typst_values = None
    if latex_file.is_file():
        latex_values = parse_metadata_tex(read_text(latex_file), str(latex_file))
    if typst_file.is_file():
        typst_values = load_metadata_json(typst_file)
    return latex_values, typst_values


def _differences(left: dict, right: dict) -> list[str]:
    messages: list[str] = []
    for key in KEY_ORDER:
        if left.get(key) != right.get(key):
            messages.append(f"  {key}: latex={left.get(key)!r} typst={right.get(key)!r}")
    return messages


def _write(path: Path, content: str) -> bool:
    if path.is_file():
        try:
            if read_text(path) == content:
                return False
        except ToolError:
            pass
    write_text_atomic(path, content)
    return True


def synchronise(latex_file: Path, typst_file: Path, source: str, check: bool) -> int:
    latex_values, typst_values = _read_values(latex_file, typst_file)
    if latex_values is None and typst_values is None:
        print(
            f"error: neither {latex_file} nor {typst_file} exists; cannot synchronise",
            file=sys.stderr,
        )
        return 2

    if check:
        problems: list[str] = []
        if latex_values is None:
            problems.append(f"missing: {latex_file}")
        if typst_values is None:
            problems.append(f"missing: {typst_file}")
        if latex_values is not None and typst_values is not None:
            differences = _differences(latex_values, typst_values)
            if differences:
                problems.append("metadata values differ:")
                problems.extend(differences)
        if problems:
            print("metadata: FAILED — drift detected")
            for problem in problems:
                print(problem if problem.startswith("  ") else "  " + problem)
            print("run 'python3 scripts/sync_metadata.py' to synchronise")
            return 1
        print(f"metadata: ok — {len(KEY_ORDER)} keys agree in both projects")
        return 0

    if source == "auto":
        # Deterministic default: the LaTeX project is authoritative, unless it
        # is the only missing file.
        source = "latex" if latex_values is not None else "typst"
    canonical: dict[str, str]
    if source == "latex":
        if latex_values is None:
            print(f"error: --from latex but {latex_file} is missing", file=sys.stderr)
            return 2
        canonical = latex_values
    else:
        if typst_values is None:
            print(f"error: --from typst but {typst_file} is missing", file=sys.stderr)
            return 2
        canonical = typst_values

    if latex_values is not None and typst_values is not None and latex_values != typst_values:
        print(f"metadata: values differ; using {source} as the authority")
        for line in _differences(latex_values, typst_values):
            print(line)

    updated = 0
    unchanged = 0
    if latex_values != canonical:
        if _write(latex_file, render_metadata_tex(canonical)):
            updated += 1
            print(f"metadata: updated {latex_file}")
        else:
            unchanged += 1
    else:
        unchanged += 1
    if typst_values != canonical:
        if _write(typst_file, render_metadata_json(canonical)):
            updated += 1
            print(f"metadata: updated {typst_file}")
        else:
            unchanged += 1
    else:
        unchanged += 1
    if updated == 0:
        print(f"metadata: {unchanged} file(s) already in agreement; nothing to write")
    else:
        print(f"metadata: {updated} file(s) updated, {unchanged} unchanged")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Synchronise metadata.tex (LaTeX) and metadata.json (Typst)."
    )
    parser.add_argument("--latex", required=True, type=Path, help="LaTeX project directory")
    parser.add_argument("--typst", required=True, type=Path, help="Typst project directory")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report drift without writing; exit 1 when the files disagree",
    )
    parser.add_argument(
        "--from",
        dest="source",
        choices=("latex", "typst", "auto"),
        default="auto",
        help="authority when the files disagree (default: latex)",
    )
    args = parser.parse_args(argv)
    if not args.latex.is_dir():
        print(f"error: {args.latex} is not a directory", file=sys.stderr)
        return 2
    if not args.typst.is_dir():
        print(f"error: {args.typst} is not a directory", file=sys.stderr)
        return 2
    latex_file, typst_file = _metadata_paths(args.latex, args.typst)
    try:
        return synchronise(latex_file, typst_file, args.source, args.check)
    except ToolError as error:
        print(f"metadata: invalid source: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
