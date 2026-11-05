"""Integration tests against the two real template repositories.

These tests run only when the sibling repositories are present and look
complete; otherwise they skip cleanly (a fresh clone of the tools repository
has no template checkouts).  Builds happen in temporary copies so the real
repositories are never modified.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

import support

import convert_latex_to_typst
import convert_typst_to_latex
from thesis_tools.parity import verify


def _copy_repository(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".git", "*.aux", "*.log"))


@unittest.skipUnless(
    support.real_projects_available(),
    "sibling template repositories are not available",
)
class RealRepositoryTests(support.ToolTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.latex = self.workdir / "latex"
        self.typst = self.workdir / "typst"
        _copy_repository(support.REAL_LATEX, self.latex)
        _copy_repository(support.REAL_TYPST, self.typst)

    def _build_typst(self) -> bool:
        compiler = shutil.which("typst")
        if compiler is None:
            return False
        command = [compiler, "compile"]
        fonts = self.typst / "fonts"
        if fonts.is_dir():
            command.extend(["--font-path", "fonts"])
        command.extend(["main.typ", "main.pdf"])
        process = subprocess.run(
            command, cwd=self.typst, capture_output=True, text=True, timeout=300, check=False
        )
        if process.returncode != 0:
            self.fail(f"typst build failed:\n{process.stdout}\n{process.stderr}")
        return True

    def _build_latex(self) -> bool:
        compiler = shutil.which("latexmk")
        if compiler is None:
            return False
        process = subprocess.run(
            [compiler, "-pdf", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
            cwd=self.latex,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if process.returncode != 0:
            self.fail(f"latexmk build failed:\n{process.stdout[-4000:]}\n{process.stderr[-2000:]}")
        return True

    def test_forward_conversion_runs_and_checks(self) -> None:
        code, out, err = self.run_tool(
            convert_latex_to_typst.main,
            ["--source", str(support.REAL_LATEX), "--target", str(self.typst)],
        )
        self.assertEqual(code, 0, out + err)
        code, out, err = self.run_tool(
            convert_latex_to_typst.main,
            ["--source", str(support.REAL_LATEX), "--target", str(self.typst), "--check"],
        )
        self.assertEqual(code, 0, out + err)
        built = self._build_typst()
        report = verify(support.REAL_LATEX, self.typst)
        self.assertFalse(
            report.failed,
            "converted Typst project failed parity:\n"
            + "\n".join(
                line
                for check in report.checks
                if check.status == "fail"
                for line in [f"[{check.number}] {check.name}: {check.status}"] + check.details
            ),
        )
        if not built:
            self.skipTest("typst compiler unavailable; conversion checked without a build")

    def test_reverse_conversion_runs_and_checks(self) -> None:
        code, out, err = self.run_tool(
            convert_typst_to_latex.main,
            ["--source", str(support.REAL_TYPST), "--target", str(self.latex)],
        )
        self.assertEqual(code, 0, out + err)
        code, out, err = self.run_tool(
            convert_typst_to_latex.main,
            ["--source", str(support.REAL_TYPST), "--target", str(self.latex), "--check"],
        )
        self.assertEqual(code, 0, out + err)
        built = self._build_latex()
        report = verify(self.latex, support.REAL_TYPST)
        self.assertFalse(
            report.failed,
            "converted LaTeX project failed parity:\n"
            + "\n".join(
                line
                for check in report.checks
                if check.status == "fail"
                for line in [f"[{check.number}] {check.name}: {check.status}"] + check.details
            ),
        )
        if not built:
            self.skipTest("latexmk unavailable; conversion checked without a build")

    def test_metadata_sync_is_clean_on_real_repositories(self) -> None:
        import sync_metadata

        code, out, err = self.run_tool(
            sync_metadata.main,
            [
                "--latex",
                str(support.REAL_LATEX),
                "--typst",
                str(support.REAL_TYPST),
                "--check",
            ],
        )
        self.assertEqual(code, 0, out + err)


if __name__ == "__main__":
    unittest.main()
