"""Typst -> LaTeX converter: smoke tests, support files and failures."""

from __future__ import annotations

import unittest

import support

import convert_typst_to_latex
from thesis_tools.common import write_text_atomic


class ConvertToLatexTests(support.ToolTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.typst = self.copy(support.TYPST_FIXTURE, "typst")
        self.latex = self.copy(support.LATEX_FIXTURE, "latex")
        self.arguments = ["--source", str(self.typst), "--target", str(self.latex)]

    def convert(self, check: bool = False):
        arguments = self.arguments + (["--check"] if check else [])
        return self.run_tool(convert_typst_to_latex.main, arguments)

    def test_conversion_smoke(self) -> None:
        code, out, err = self.convert()
        self.assertEqual(code, 0, out + err)
        self.assertIn("typst->latex", out)
        main = (self.latex / "main.tex").read_text(encoding="utf-8")
        self.assertTrue(main.startswith("% !TEX program = pdflatex"))
        self.assertIn("\\documentclass[12pt,a4paper]{report}", main)
        self.assertIn("\\input{preamble}", main)
        self.assertIn("\\thesiscovermatter", main)
        self.assertIn("\\thesisfrontmatter", main)
        self.assertIn("\\thesismainmatter", main)
        self.assertIn("\\thesisappendix", main)
        self.assertIn("\\tableofcontents", main)
        self.assertIn("\\listoffigures", main)
        self.assertIn("\\listoftables", main)
        self.assertIn("\\lstlistoflistings", main)
        self.assertIn("\\thesisappendix", main)
        self.assertIn("\\include{chapters/bab1}", main)

        # Build/editor support files required of the LaTeX repository.
        self.assertTrue((self.latex / ".latexmkrc").is_file())
        self.assertTrue((self.latex / "overleaf.txt").is_file())
        latexmkrc = (self.latex / ".latexmkrc").read_text(encoding="utf-8")
        self.assertIn("$pdf_mode = 1", latexmkrc)
        self.assertIn("$pdflatex", latexmkrc)
        code_lines = [
            line for line in latexmkrc.splitlines() if not line.strip().startswith("#")
        ]
        self.assertNotIn("bibtex", "\n".join(code_lines).lower())
        self.assertIn("pdfLaTeX", (self.latex / "overleaf.txt").read_text(encoding="utf-8"))

        bab1 = (self.latex / "chapters" / "bab1.tex").read_text(encoding="utf-8")
        self.assertIn("\\chapter{Pendahuluan}", bab1)
        self.assertIn("\\section{Latar Belakang}", bab1)
        self.assertIn("\\label{sec:1.1}", bab1)
        self.assertIn("\\begin{figure}[H]", bab1)
        self.assertIn("\\thesisfigure{\\includegraphics{assets/fig-1.pdf}}", bab1)
        self.assertIn("\\begin{lstlisting}[language=Python", bab1)
        self.assertIn("\\begin{equation}", bab1)
        self.assertIn("\\begin{enumerate}", bab1)
        self.assertIn("\\item{}", bab1)

        bab2 = (self.latex / "chapters" / "bab2.tex").read_text(encoding="utf-8")
        self.assertIn("\\begin{thesistable}", bab2)
        self.assertIn("\\begin{longtable}", bab2)
        self.assertIn("\\endfirsthead", bab2)
        self.assertIn("\\endhead", bab2)
        self.assertIn("\\begin{landscape}", bab2)
        self.assertIn("\\midrule", bab2)

        referensi = (self.latex / "backmatter" / "referensi.tex").read_text(encoding="utf-8")
        self.assertIn("\\begin{thesisbibliography}", referensi)
        self.assertIn("\\url{", referensi)
        cover = (self.latex / "frontmatter" / "cover.tex").read_text(encoding="utf-8")
        self.assertIn("\\thesiscoverpage", cover)

    def test_check_is_idempotent_and_detects_drift(self) -> None:
        code, _out, _err = self.convert(check=True)
        self.assertEqual(code, 1)
        code, _out, err = self.convert()
        self.assertEqual(code, 0, err)
        code, out, _err = self.convert(check=True)
        self.assertEqual(code, 0, out)
        write_text_atomic(
            self.latex / "chapters" / "bab2.tex",
            (self.latex / "chapters" / "bab2.tex").read_text(encoding="utf-8") + "% tampered\n",
        )
        code, out, _err = self.convert(check=True)
        self.assertEqual(code, 1)
        self.assertIn("chapters/bab2.tex", out)

    def test_unknown_call_fails_with_file_and_construct(self) -> None:
        path = self.typst / "chapters" / "bab1.typ"
        text = path.read_text(encoding="utf-8")
        text += "\n#mystery-function(3)\n"
        path.write_text(text, encoding="utf-8")
        code, _out, err = self.convert()
        self.assertEqual(code, 2)
        self.assertIn("bab1.typ", err)
        self.assertIn("mystery-function", err)

    def test_target_without_latex_interface_is_rejected(self) -> None:
        empty = self.workdir / "empty-latex"
        empty.mkdir()
        code, _out, err = self.run_tool(
            convert_typst_to_latex.main,
            ["--source", str(self.typst), "--target", str(empty)],
        )
        self.assertEqual(code, 2)
        self.assertIn("preamble.tex", err)

    def test_list_item_starting_with_bracket_keeps_its_text(self) -> None:
        code, _out, err = self.convert()
        self.assertEqual(code, 0, err)
        bab1 = (self.latex / "chapters" / "bab1.tex").read_text(encoding="utf-8")
        self.assertIn("\\item{} Bagaimana [masalah pertama]?", bab1)


if __name__ == "__main__":
    unittest.main()
