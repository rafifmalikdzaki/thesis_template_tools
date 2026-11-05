"""Typst -> LaTeX converter: smoke tests, support files and failures."""

from __future__ import annotations

import shutil
import subprocess
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
        self.assertIn("\\documentclass{thesis}", main)
        self.assertNotIn("\\input{preamble}", main)
        # Class-based project: the canonical class and layout are emitted.
        self.assertTrue((self.latex / "thesis.cls").is_file())
        self.assertTrue((self.latex / "thesis-layout.sty").is_file())
        thesis_class = (self.latex / "thesis.cls").read_text(encoding="utf-8")
        self.assertIn("\\LoadClass[12pt,a4paper]{report}", thesis_class)
        self.assertIn("\\ifPDFTeX", thesis_class)
        self.assertIn("fontspec", thesis_class)
        self.assertIn("unicode-math", thesis_class)
        self.assertIn("\\input{metadata.tex}", thesis_class)
        self.assertIn("\\RequirePackage{thesis-layout}", thesis_class)
        # Unicode engines load the bundled fonts relative to the project root.
        self.assertIn("Path=fonts/", thesis_class)
        # Unicode engines have no U+2713 in Latin Modern Math; the class must
        # provide the DejaVu Sans check-mark fallback inside the fontspec
        # branch only. Placing it globally would break pdfLaTeX.
        self.assertIn("DejaVuSans.ttf", thesis_class)
        self.assertIn("\\thesis@checkmarkfont", thesis_class)
        self.assertIn('\\char"2713', thesis_class)
        checkmark_at = thesis_class.index("\\thesis@checkmarkfont")
        branch_at = thesis_class.index("\\ifPDFTeX")
        self.assertLess(
            checkmark_at,
            branch_at,
            "the check-mark fallback belongs to the shared Unicode helper, "
            "not the pdfLaTeX branch",
        )
        layout = (self.latex / "thesis-layout.sty").read_text(encoding="utf-8")
        self.assertIn("{geometry}", layout)
        self.assertIn("\\thesiscoverpage", layout)
        # Bundled Unicode fonts and licences travel with the project.
        for relative in (
            "fonts/texgyreheros-regular.otf",
            "fonts/latinmodern-math.otf",
            "fonts/DejaVuSans.ttf",
            "fonts/LPPL-1.3c.txt",
        ):
            self.assertTrue((self.latex / relative).is_file(), relative)
        self.assertNotIn("\\RequirePackage{fontspec}", layout)
        self.assertNotIn("\\usepackage{fontspec}", layout)
        self.assertNotIn("\\usepackage[T1]{fontenc}", layout)
        self.assertIn("\\thesiscovermatter", main)
        self.assertIn("\\thesisfrontmatter", main)
        self.assertIn("\\thesismainmatter", main)
        self.assertIn("\\thesisappendix", main)
        self.assertIn("\\tableofcontents", main)
        self.assertIn("\\listoffigures", main)
        self.assertIn("\\listoftables", main)
        self.assertIn("\\lstlistoflistings", main)
        self.assertIn("\\include{chapters/bab1}", main)

        # Build/editor support files required of the LaTeX repository.
        self.assertTrue((self.latex / ".latexmkrc").is_file())
        self.assertTrue((self.latex / "overleaf.txt").is_file())
        latexmkrc = (self.latex / ".latexmkrc").read_text(encoding="utf-8")
        code_lines = [
            line for line in latexmkrc.splitlines() if not line.strip().startswith("#")
        ]
        code = "\n".join(code_lines)
        self.assertNotIn("$pdf_mode", code)
        self.assertIn("$pdflatex", code)
        self.assertIn("$xelatex", code)
        self.assertIn("$lualatex", code)
        # BibTeX and makeindex are disabled, not invoked.
        self.assertIn("$bibtex_use = 0", code)
        self.assertIn("$makeindex = ''", code)
        self.assertNotIn("bibtex %O", code.lower())
        self.assertNotIn("makeindex %O", code.lower())
        overleaf = (self.latex / "overleaf.txt").read_text(encoding="utf-8")
        self.assertIn("pdfLaTeX", overleaf)
        self.assertIn("XeLaTeX", overleaf)
        self.assertIn("LuaLaTeX", overleaf)

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

    def test_engine_neutral_build_support(self) -> None:
        code, _out, err = self.convert()
        self.assertEqual(code, 0, err)
        latexmkrc = (self.latex / ".latexmkrc").read_text(encoding="utf-8")
        code_lines = [
            line for line in latexmkrc.splitlines() if not line.strip().startswith("#")
        ]
        code_text = "\n".join(code_lines)
        # The engine is selected on the command line, not fixed in the file.
        self.assertNotIn("$pdf_mode", code_text)
        for engine in ("$pdflatex", "$xelatex", "$lualatex"):
            self.assertIn(engine, code_text)
        # No BibTeX/Biber/index pass is configured.
        self.assertIn("$bibtex_use = 0", code_text)
        self.assertIn("$makeindex = ''", code_text)
        self.assertNotIn("bibtex %O", code_text.lower())
        overleaf = (self.latex / "overleaf.txt").read_text(encoding="utf-8")
        self.assertIn("pdfLaTeX", overleaf)
        self.assertIn("XeLaTeX", overleaf)
        self.assertIn("LuaLaTeX", overleaf)
        self.assertIn("recommended", overleaf)

    @unittest.skipUnless(
        shutil.which("latexmk") and shutil.which("pdflatex") and shutil.which("xelatex"),
        "LaTeX toolchain (latexmk/pdflatex/xelatex) is unavailable",
    )
    def test_converted_project_builds_with_pdflatex_and_xelatex(self) -> None:
        code, _out, err = self.convert()
        self.assertEqual(code, 0, err)
        for engine in ("pdflatex", "xelatex"):
            # Switching engines requires a clean auxiliary directory.
            shutil.rmtree(self.latex / "build", ignore_errors=True)
            arguments = ["bash", "build.sh"] if engine == "pdflatex" else [
                "bash",
                "build.sh",
                f"--engine={engine}",
            ]
            process = subprocess.run(
                arguments,
                cwd=self.latex,
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            self.assertEqual(
                process.returncode,
                0,
                f"{engine} build failed:\n{process.stdout[-3000:]}\n{process.stderr[-1500:]}",
            )
            self.assertTrue((self.latex / "main.pdf").is_file())

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
        self.assertIn("thesis-layout.sty", err)

    def test_legacy_preamble_target_is_accepted(self) -> None:
        legacy = self.copy(support.LATEX_LEGACY_FIXTURE, "latex-legacy")
        code, out, err = self.run_tool(
            convert_typst_to_latex.main,
            ["--source", str(self.typst), "--target", str(legacy)],
        )
        self.assertEqual(code, 0, out + err)
        self.assertIn("\\documentclass{thesis}", (legacy / "main.tex").read_text(encoding="utf-8"))
        self.assertTrue((legacy / "thesis.cls").is_file())

    def test_list_item_starting_with_bracket_keeps_its_text(self) -> None:
        code, _out, err = self.convert()
        self.assertEqual(code, 0, err)
        bab1 = (self.latex / "chapters" / "bab1.tex").read_text(encoding="utf-8")
        self.assertIn("\\item{} Bagaimana [masalah pertama]?", bab1)


if __name__ == "__main__":
    unittest.main()
