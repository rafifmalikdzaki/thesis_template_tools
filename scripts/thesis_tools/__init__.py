"""Shared implementation for the thesis-template conversion tooling.

The modules in this package are imported by the thin command-line scripts in
``scripts/`` and by the test suite.  They use the Python standard library only.
"""

__all__ = ["common", "latex_model", "typst_model", "to_typst", "to_latex", "parity"]
