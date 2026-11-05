"""Parity verifier: passes on the fixture pair, fails on deliberate mismatches."""

from __future__ import annotations

import unittest

import support

from thesis_tools.common import write_text_atomic
from thesis_tools.parity import verify


class ParityTests(support.ToolTestCase):
    def test_fixture_pair_passes(self) -> None:
        report = verify(support.LATEX_FIXTURE, support.TYPST_FIXTURE)
        self.assertFalse(report.failed, "\n".join(
            detail for check in report.checks for detail in [f"[{check.number}] {check.name}: {check.status}"] + check.details
        ))
        statuses = {check.number: check.status for check in report.checks}
        for number in ("1", "2", "3", "4", "5"):
            self.assertEqual(statuses[number], "ok", number)

    def test_mismatched_table_payload_fails(self) -> None:
        typst = self.copy(support.TYPST_FIXTURE, "typst")
        self.overlay(support.MISMATCH_OVERLAY, typst)
        report = verify(support.LATEX_FIXTURE, typst)
        self.assertTrue(report.failed)
        table_check = next(check for check in report.checks if check.number == "3")
        self.assertEqual(table_check.status, "fail")
        self.assertTrue(any("payload differs" in detail for detail in table_check.details))

    def test_missing_figure_fails(self) -> None:
        typst = self.copy(support.TYPST_FIXTURE, "typst")
        path = typst / "chapters" / "bab1.typ"
        text = path.read_text(encoding="utf-8")
        start = text.index("#thesis-figure(")
        end = text.index(") <fig:1.alur>") + len(") <fig:1.alur>")
        path.write_text(text[:start] + text[end:], encoding="utf-8")
        report = verify(support.LATEX_FIXTURE, typst)
        self.assertTrue(report.failed)
        inventory = next(check for check in report.checks if check.number == "2")
        self.assertEqual(inventory.status, "fail")
        self.assertTrue(any("figures" in detail for detail in inventory.details))

    def test_metadata_drift_fails(self) -> None:
        typst = self.copy(support.TYPST_FIXTURE, "typst")
        path = typst / "metadata.json"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("[Judul Tesis]", "[Judul Lain]"), encoding="utf-8")
        report = verify(support.LATEX_FIXTURE, typst)
        self.assertTrue(report.failed)
        metadata = next(check for check in report.checks if check.number == "1")
        self.assertEqual(metadata.status, "fail")

    def test_listing_body_drift_fails(self) -> None:
        typst = self.copy(support.TYPST_FIXTURE, "typst")
        path = typst / "chapters" / "bab1.typ"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("return x + 1", "return x + 2"), encoding="utf-8")
        report = verify(support.LATEX_FIXTURE, typst)
        self.assertTrue(report.failed)
        listings = next(check for check in report.checks if check.number == "4")
        self.assertEqual(listings.status, "fail")


if __name__ == "__main__":
    unittest.main()
