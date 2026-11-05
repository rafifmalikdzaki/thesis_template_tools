"""Round trip LaTeX -> Typst -> LaTeX preserves the semantic inventory.

Byte equality is explicitly not the contract (see docs/CONVERSION.md); the
round trip preserves chapters, sections, figures, tables (count, identifiers,
numeric payloads), listings, equations, labels, references and metadata values
within the documented limits.
"""

from __future__ import annotations

import re
import unittest

import support

import convert_latex_to_typst
import convert_typst_to_latex
from thesis_tools import latex_model as lm
from thesis_tools.common import read_text


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", lm.plain_latex_text(text)).strip()


def _cell(text: str) -> str:
    # Placeholder brackets are LaTeX grouping in the sources; the Typst starter
    # stores the cell text without them, so compare the words inside.
    return _plain(text).replace("[", "").replace("]", "").strip()


def latex_inventory(root):
    project = lm.LatexProject.discover(root)
    inventory = {
        "headings": [],
        "figures": [],
        "tables": [],
        "listings": [],
        "equations": [],
        "labels": [],
        "refs": [],
    }
    for include in project.includes + project.extra_content:
        if include.admin is not None:
            continue
        text = read_text(include.path)
        raw = lm.scan_inventory(text, include.path)
        scanner = lm.LatexScanner(include.path, text)
        headings = []
        specs = {}
        for block in scanner.scan():
            if isinstance(block, lm.Heading):
                headings.append(block)
            elif isinstance(block, lm.Figure):
                specs[block.spec.label] = block.spec
            elif isinstance(block, lm.Table):
                specs[block.spec.label] = block.spec
            elif isinstance(block, lm.Listing):
                specs[block.spec.label] = block.spec
            elif isinstance(block, lm.Equation):
                specs[block.spec.label] = block.spec
        heading_iter = iter(headings)
        for item in raw.items:
            if item.kind == "heading":
                heading = next(heading_iter, None)
                if item.unnumbered:
                    continue
                inventory["headings"].append(
                    (item.level, _plain(heading.title if heading else ""))
                )
            elif item.kind == "figure":
                spec = specs[item.label]
                inventory["figures"].append((item.label, _plain(spec.caption)))
            elif item.kind == "table":
                spec = specs[item.label]
                inventory["tables"].append(
                    (
                        item.label,
                        tuple((column.align, column.width) for column in spec.columns),
                        tuple(tuple(_cell(cell) for cell in row) for row in spec.header),
                        tuple(tuple(_cell(cell) for cell in row) for row in spec.rows),
                        tuple(spec.rules),
                        spec.landscape,
                        tuple(spec.payload),
                    )
                )
            elif item.kind == "listing":
                spec = specs[item.label]
                inventory["listings"].append((item.label, _dedent(spec.body)))
            elif item.kind == "equation":
                inventory["equations"].append((item.label,))
        inventory["labels"].extend(raw.labels)
        inventory["refs"].extend(label for _command, label in raw.refs)
    return inventory


def _dedent(body: str) -> list[str]:
    lines = body.replace("\r\n", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    leading = [len(line) - len(line.lstrip(" ")) for line in lines if line.strip()]
    cut = min(leading) if leading else 0
    return [line[cut:].rstrip() for line in lines]


class RoundTripTests(support.ToolTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.latex_source = self.copy(support.LATEX_FIXTURE, "latex-source")
        self.typst_target = self.copy(support.TYPST_FIXTURE, "typst-target")
        self.latex_target = self.copy(support.LATEX_FIXTURE, "latex-target")

    def test_round_trip_preserves_inventory(self) -> None:
        code, out, err = self.run_tool(
            convert_latex_to_typst.main,
            ["--source", str(self.latex_source), "--target", str(self.typst_target)],
        )
        self.assertEqual(code, 0, out + err)
        code, out, err = self.run_tool(
            convert_typst_to_latex.main,
            ["--source", str(self.typst_target), "--target", str(self.latex_target)],
        )
        self.assertEqual(code, 0, out + err)

        original = latex_inventory(self.latex_source)
        round_tripped = latex_inventory(self.latex_target)

        for name in ("headings", "figures", "tables", "listings", "equations"):
            self.assertEqual(
                original[name],
                round_tripped[name],
                f"{name} changed in the round trip",
            )

        self.assertEqual(set(original["labels"]), set(round_tripped["labels"]))
        self.assertEqual(set(original["refs"]), set(round_tripped["refs"]))

        from thesis_tools.common import parse_metadata_tex

        left = parse_metadata_tex(
            read_text(self.latex_source / "metadata.tex"), "source metadata.tex"
        )
        right = parse_metadata_tex(
            read_text(self.latex_target / "metadata.tex"), "target metadata.tex"
        )
        self.assertEqual(left, right)

    def test_round_trip_keeps_numeric_payloads_and_ids(self) -> None:
        code, out, err = self.run_tool(
            convert_latex_to_typst.main,
            ["--source", str(self.latex_source), "--target", str(self.typst_target)],
        )
        self.assertEqual(code, 0, out + err)
        code, out, err = self.run_tool(
            convert_typst_to_latex.main,
            ["--source", str(self.typst_target), "--target", str(self.latex_target)],
        )
        self.assertEqual(code, 0, out + err)
        original = {table[0]: table for table in latex_inventory(self.latex_source)["tables"]}
        round_tripped = {
            table[0]: table for table in latex_inventory(self.latex_target)["tables"]
        }
        self.assertEqual(set(original), set(round_tripped))
        for label in original:
            self.assertEqual(original[label][6], round_tripped[label][6], label)
            self.assertEqual(original[label][5], round_tripped[label][5], label)
            self.assertEqual(original[label][4], round_tripped[label][4], label)

    def test_round_trip_assets_are_copied(self) -> None:
        code, _out, err = self.run_tool(
            convert_latex_to_typst.main,
            ["--source", str(self.latex_source), "--target", str(self.typst_target)],
        )
        self.assertEqual(code, 0, err)
        self.assertTrue((self.typst_target / "assets" / "fig-1.pdf").is_file())
        self.assertTrue((self.typst_target / "assets" / "logo.pdf").is_file())


if __name__ == "__main__":
    unittest.main()
