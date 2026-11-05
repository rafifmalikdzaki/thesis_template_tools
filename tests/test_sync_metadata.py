"""Metadata synchronisation: idempotency, drift, escaping and validation."""

from __future__ import annotations

import json
import unittest

import support
from thesis_tools.common import (
    KEY_TO_COMMAND,
    latex_escape,
    latex_unescape,
    parse_metadata_tex,
    read_text,
)

import sync_metadata


class SyncMetadataTests(support.ToolTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.latex = self.copy(support.LATEX_FIXTURE, "latex")
        self.typst = self.copy(support.TYPST_FIXTURE, "typst")
        self.arguments = ["--latex", str(self.latex), "--typst", str(self.typst)]

    def test_sync_is_idempotent(self) -> None:
        code, out, _err = self.run_tool(sync_metadata.main, self.arguments)
        self.assertEqual(code, 0, out)
        first_latex = (self.latex / "metadata.tex").read_bytes()
        first_typst = (self.typst / "metadata.json").read_bytes()
        code, out, _err = self.run_tool(sync_metadata.main, self.arguments)
        self.assertEqual(code, 0, out)
        self.assertEqual((self.latex / "metadata.tex").read_bytes(), first_latex)
        self.assertEqual((self.typst / "metadata.json").read_bytes(), first_typst)
        self.assertIn("already in agreement", out)

    def test_check_accepts_agreement(self) -> None:
        code, out, _err = self.run_tool(sync_metadata.main, self.arguments + ["--check"])
        self.assertEqual(code, 0, out)
        self.assertIn("ok", out)

    def test_check_reports_drift(self) -> None:
        path = self.typst / "metadata.json"
        values = json.loads(path.read_text(encoding="utf-8"))
        values["title"] = "[Judul yang diedit]"
        path.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        code, out, _err = self.run_tool(sync_metadata.main, self.arguments + ["--check"])
        self.assertEqual(code, 1)
        self.assertIn("title", out)

    def test_sync_from_typst_updates_latex(self) -> None:
        path = self.typst / "metadata.json"
        values = json.loads(path.read_text(encoding="utf-8"))
        values["author"] = "[Penulis Baru]"
        path.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        code, out, _err = self.run_tool(
            sync_metadata.main, self.arguments + ["--from", "typst"]
        )
        self.assertEqual(code, 0, out)
        latex_values = parse_metadata_tex(
            read_text(self.latex / "metadata.tex"), "metadata.tex"
        )
        self.assertEqual(latex_values["author"], "[Penulis Baru]")
        code, _out, _err = self.run_tool(sync_metadata.main, self.arguments + ["--check"])
        self.assertEqual(code, 0)

    def test_latex_escaping_round_trip(self) -> None:
        path = self.typst / "metadata.json"
        values = json.loads(path.read_text(encoding="utf-8"))
        tricky = r"A & B % C # D _ E { F } ~ G \ H"
        values["title"] = tricky
        path.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        code, _out, err = self.run_tool(sync_metadata.main, self.arguments + ["--from", "typst"])
        self.assertEqual(code, 0, err)
        text = read_text(self.latex / "metadata.tex")
        self.assertIn(r"\&", text)
        self.assertIn(r"\%", text)
        self.assertIn(r"\#", text)
        self.assertIn(r"\_", text)
        self.assertIn(r"\{", text)
        self.assertIn(r"\}", text)
        self.assertIn(r"\textasciitilde{}", text)
        self.assertIn(r"\textbackslash{}", text)
        parsed = parse_metadata_tex(text, "metadata.tex")
        self.assertEqual(parsed["title"], tricky)
        self.assertEqual(latex_unescape(latex_escape(tricky)), tricky)

    def test_missing_counterpart_is_created(self) -> None:
        only_latex = self.workdir / "only-latex"
        only_typst = self.workdir / "only-typst"
        self.latex.rename(only_latex)
        only_typst.mkdir()
        arguments = ["--latex", str(only_latex), "--typst", str(only_typst)]
        code, out, err = self.run_tool(sync_metadata.main, arguments)
        self.assertEqual(code, 0, out + err)
        self.assertTrue((only_typst / "metadata.json").is_file())
        code, out, _err = self.run_tool(sync_metadata.main, arguments + ["--check"])
        self.assertEqual(code, 0, out)

    def test_unknown_key_is_rejected(self) -> None:
        path = self.typst / "metadata.json"
        values = json.loads(path.read_text(encoding="utf-8"))
        values["mystery"] = "x"
        path.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        code, _out, err = self.run_tool(sync_metadata.main, self.arguments)
        self.assertEqual(code, 2)
        self.assertIn("unknown keys", err)

    def test_every_key_has_a_latex_command(self) -> None:
        metadata = read_text(self.latex / "metadata.tex")
        for key in KEY_TO_COMMAND:
            self.assertIn("\\" + KEY_TO_COMMAND[key], metadata)


if __name__ == "__main__":
    unittest.main()
