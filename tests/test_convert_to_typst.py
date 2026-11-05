"""LaTeX -> Typst converter: smoke tests, support-file handling and failures."""

from __future__ import annotations

import unittest

import support

import convert_latex_to_typst
from thesis_tools.common import write_text_atomic


class ConvertToTypstTests(support.ToolTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.latex = self.copy(support.LATEX_FIXTURE, "latex")
        self.typst = self.copy(support.TYPST_FIXTURE, "typst")
        self.arguments = ["--source", str(self.latex), "--target", str(self.typst)]

    def convert(self, check: bool = False):
        arguments = self.arguments + (["--check"] if check else [])
        return self.run_tool(convert_latex_to_typst.main, arguments)

    def test_conversion_smoke(self) -> None:
        code, out, err = self.convert()
        self.assertEqual(code, 0, out + err)
        self.assertIn("latex->typst", out)
        main = (self.typst / "main.typ").read_text(encoding="utf-8")
        self.assertIn('#import "template.typ": *', main)
        self.assertIn("#show: thesis", main)
        self.assertIn("#cover-page()", main)
        self.assertIn("#approval-page()", main)
        self.assertIn("#declaration-page()", main)
        self.assertIn('#set page(numbering: "i")', main)
        self.assertIn('#set page(numbering: "1")', main)
        self.assertIn("#appendix()", main)
        self.assertIn("#outline-page(\"Daftar Isi\"", main)
        self.assertIn('#include "chapters/bab1.typ"', main)
        # \thesisfrontmatter / \thesismainmatter / \thesisappendix are mapped.
        self.assertIn("#counter(page).update(1)", main)
        self.assertIn("#appendix()", main)
        self.assertTrue((self.typst / "metadata.json").is_file())

        bab1 = (self.typst / "chapters/bab1.typ").read_text(encoding="utf-8")
        self.assertIn("#import \"../template.typ\": *", bab1)
        self.assertIn("== Latar Belakang <sec:1.1>", bab1)
        self.assertIn("#thesis-figure(", bab1)
        self.assertIn("#listing(", bab1)
        self.assertIn("#equation-row[", bab1)
        self.assertIn("+ Bagaimana", bab1)

        bab2 = (self.typst / "chapters/bab2.typ").read_text(encoding="utf-8")
        self.assertIn("#thesis-table(", bab2)
        self.assertIn("label: <tab:1.data>", bab2)
        self.assertIn("#landscape[", bab2)
        self.assertIn("rules: (2,)", bab2)

        referensi = (self.typst / "backmatter/referensi.typ").read_text(encoding="utf-8")
        self.assertIn("#thesis-bibliography[", referensi)
        lampiran = (self.typst / "lampiran/lampiran_a.typ").read_text(encoding="utf-8")
        self.assertIn("= Data Pendukung <lam:a>", lampiran)
        self.assertTrue((self.typst / "assets" / "fig-1.pdf").is_file())

    def test_build_and_editor_support_files_are_not_copied(self) -> None:
        # The LaTeX repository carries support files the Typst project must not
        # inherit; the converter ignores them instead of copying them.
        code, _out, err = self.convert()
        self.assertEqual(code, 0, err)
        self.assertFalse((self.typst / ".latexmkrc").exists())
        self.assertTrue((self.typst / "overleaf.txt").exists())  # pre-existing, untouched
        self.assertNotIn("TEX program", (self.typst / "main.typ").read_text(encoding="utf-8"))
        self.assertFalse((self.typst / "examples").exists())
        # The support files are tolerated on the source side: removing them
        # does not change the conversion result.
        before = (self.typst / "chapters/bab1.typ").read_text(encoding="utf-8")
        (self.latex / ".latexmkrc").unlink()
        (self.latex / "overleaf.txt").unlink()
        code, _out, err = self.convert()
        self.assertEqual(code, 0, err)
        self.assertEqual((self.typst / "chapters/bab1.typ").read_text(encoding="utf-8"), before)

    def test_check_is_idempotent_and_detects_drift(self) -> None:
        code, _out, _err = self.convert(check=True)
        self.assertEqual(code, 1)  # the fixture target still has its own content
        code, _out, err = self.convert()
        self.assertEqual(code, 0, err)
        code, out, _err = self.convert(check=True)
        self.assertEqual(code, 0, out)
        write_text_atomic(
            self.typst / "chapters" / "bab1.typ",
            (self.typst / "chapters" / "bab1.typ").read_text(encoding="utf-8") + "tampered\n",
        )
        code, out, _err = self.convert(check=True)
        self.assertEqual(code, 1)
        self.assertIn("chapters/bab1.typ", out)

    def test_unknown_macro_fails_with_file_and_construct(self) -> None:
        path = self.latex / "chapters" / "bab1.tex"
        text = path.read_text(encoding="utf-8")
        text = text.replace("\\section{Implementasi}", "\\unknownmacro{boom}\n\n\\section{Implementasi}")
        path.write_text(text, encoding="utf-8")
        code, _out, err = self.convert()
        self.assertEqual(code, 2)
        self.assertIn("bab1.tex", err)
        self.assertIn("unknownmacro", err)

    def test_unsupported_environment_fails(self) -> None:
        path = self.latex / "chapters" / "bab2.tex"
        text = path.read_text(encoding="utf-8")
        text += "\n\\begin{tikzpicture}\n\\draw (0,0) -- (1,1);\n\\end{tikzpicture}\n"
        path.write_text(text, encoding="utf-8")
        code, _out, err = self.convert()
        self.assertEqual(code, 2)
        self.assertIn("bab2.tex", err)
        self.assertIn("tikzpicture", err)

    def test_target_without_template_is_rejected(self) -> None:
        empty = self.workdir / "empty-target"
        empty.mkdir()
        code, _out, err = self.run_tool(
            convert_latex_to_typst.main,
            ["--source", str(self.latex), "--target", str(empty)],
        )
        self.assertEqual(code, 2)
        self.assertIn("template.typ", err)

    def test_landscape_table_and_appendix(self) -> None:
        code, _out, err = self.convert()
        self.assertEqual(code, 0, err)
        bab2 = (self.typst / "chapters/bab2.typ").read_text(encoding="utf-8")
        self.assertIn("#landscape[", bab2)
        self.assertIn("label: <tab:2.rekap>", bab2)
        lampiran = (self.typst / "lampiran/lampiran_a.typ").read_text(encoding="utf-8")
        self.assertIn("#thesis-table(", lampiran)
        self.assertIn("label: <tab:lam.a1>", lampiran)
        self.assertIn("$ bar(x) = frac(1, n) sum_(i=1)^n x_i $", lampiran)


if __name__ == "__main__":
    unittest.main()
