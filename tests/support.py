"""Shared helpers for the test suite.

Importing this module puts ``scripts/`` on ``sys.path`` so the tests can call
the tool entry points directly (``main([...])``), matching how the tools run
from the command line.
"""

from __future__ import annotations

import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = TOOLS_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LATEX_FIXTURE = FIXTURES / "latex"
TYPST_FIXTURE = FIXTURES / "typst"
MISMATCH_OVERLAY = FIXTURES / "mismatch_typst"

# The two template repositories live next to the tools repository.
REAL_LATEX = TOOLS_ROOT.parent / "thesis_template_latex"
REAL_TYPST = TOOLS_ROOT.parent / "thesis_template_typst"


def real_projects_available() -> bool:
    return (
        (REAL_LATEX / "main.tex").is_file()
        and (REAL_TYPST / "main.typ").is_file()
        and (REAL_TYPST / "template.typ").is_file()
        and (REAL_LATEX / "preamble.tex").is_file()
        and (REAL_LATEX / "thesis-layout.sty").is_file()
    )


class ToolTestCase(unittest.TestCase):
    """Base class managing a temporary directory for each test."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="thesis-tools-test-")
        self.workdir = Path(self._temporary.name)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def copy(self, source: Path, name: str) -> Path:
        destination = self.workdir / name
        shutil.copytree(source, destination)
        return destination

    def overlay(self, source: Path, target: Path) -> None:
        for path in source.rglob("*"):
            if path.is_file():
                relative = path.relative_to(source)
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)

    def run_tool(self, function, arguments: list[str]) -> tuple[int, str, str]:
        """Run a tool entry point, capturing stdout/stderr."""
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = function(arguments)
            except SystemExit as error:  # argparse exits on usage errors
                code = int(error.code or 0)
        return code, stdout.getvalue(), stderr.getvalue()
