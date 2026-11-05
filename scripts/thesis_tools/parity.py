"""Cross-engine parity verification for the two thesis starters.

Checks, in order:

1. metadata agreement between ``metadata.tex`` and ``metadata.json``;
2. object inventory and identifier order (headings, figures, tables, listings,
   display equations, appendix headings);
3. table numeric payloads, from the sources and - when both PDFs are present -
   from the rendered PDFs (``pdftotext``);
4. listing bodies;
5. label existence, reference resolution and cross-engine label sets;
6. normalised rendered-text agreement (PDFs, documented tolerance);
7. administrative-page text (cover, approval, declaration).

The PDF-based checks are skipped cleanly when a project has not been built or
when poppler is not installed; the source-level checks always run.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import latex_model as lm
from . import typst_model as tm
from .common import ToolError, read_text

TEXT_TOLERANCE = 0.005
BANNER_RE = re.compile(r"(?im)^[ \t\f]*Lanjutan\s+Tabel\s+[0-9]+(?:\.[0-9]+)*[ \t]*$")
LABEL_RE = re.compile(r"<([A-Za-z][A-Za-z0-9_.:-]*)>")
NUMERIC_TOKEN_RE = lm.NUMERIC_TOKEN_RE
RENDERED_NUMBERING_PATTERNS = {
    "figure": r"Gambar\s+([0-9]+(?:\.[0-9]+)+)",
    "table": r"Tabel\s+([0-9]+(?:\.[0-9]+)+)",
    "listing": r"Kode\s+Sumber\s+([0-9]+(?:\.[0-9]+)+)",
    "equation": r"\(([0-9]+(?:\.[0-9]+)+|[A-Z]\.[0-9]+)\)",
}
WORD_RE = re.compile(r"[0-9a-z\u00c0-\u024f]+")


class VerifierError(ToolError):
    """Fatal problem: malformed project or missing dependency."""


# ---------------------------------------------------------------------------
# Report plumbing
# ---------------------------------------------------------------------------


@dataclass
class Check:
    number: str
    name: str
    status: str = "ok"
    details: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.status = "fail"
        self.details.append(message)

    def skip(self, message: str) -> None:
        self.status = "skip"
        self.details.append(message)

    def note(self, message: str) -> None:
        self.details.append(message)


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    known_differences: list[dict] = field(default_factory=list)

    def add(self, check: Check) -> Check:
        self.checks.append(check)
        return check

    @property
    def failed(self) -> bool:
        return any(check.status == "fail" for check in self.checks)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def plain_words(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def plain_heading(text: str) -> str:
    text = re.sub(r"\\(?:textbf|textit|emph|text|textrm|MakeUppercase|MakeLowercase)\s*\{", "", text)
    text = re.sub(r"\\[A-Za-z@]+\*?", " ", text)
    text = re.sub(r"[*_`]", "", text)
    text = text.replace("{", " ").replace("}", " ")
    text = text.replace("[", " ").replace("]", " ")
    return collapse(text)


def dedent_lines(body: str) -> list[str]:
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    leading = [len(line) - len(line.lstrip(" ")) for line in lines if line.strip()]
    cut = min(leading) if leading else 0
    return [line[cut:].rstrip() for line in lines]


def normalise_words(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u00ad", "")
    text = (
        text.replace("\ufb00", "ff")
        .replace("\ufb01", "fi")
        .replace("\ufb02", "fl")
        .replace("\ufb03", "ffi")
        .replace("\ufb04", "ffl")
    )
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"\s+", " ", text)
    return WORD_RE.findall(text.lower())


# ---------------------------------------------------------------------------
# Event model and numbering
# ---------------------------------------------------------------------------


@dataclass
class Event:
    kind: str
    level: int = 0
    title: str = ""
    label: str | None = None
    appendix: bool = False
    number: str = ""
    body: str = ""
    spec: object | None = None


def assign_numbers(events: list[Event]) -> list[Event]:
    chapter = 0
    section = 0
    subsection = 0
    appendix_index = 0
    counters = {"figure": 0, "table": 0, "listing": 0, "equation": 0}
    chapter_label = "1"
    for event in events:
        if event.kind == "heading":
            if event.level == 1:
                for key in counters:
                    counters[key] = 0
                if event.appendix:
                    chapter_label = chr(ord("A") + appendix_index)
                    appendix_index += 1
                else:
                    chapter += 1
                    chapter_label = str(chapter)
                section = 0
                subsection = 0
                event.number = chapter_label
            elif event.level == 2:
                section += 1
                subsection = 0
                event.number = f"{chapter_label}.{section}"
            elif event.level == 3:
                subsection += 1
                event.number = f"{chapter_label}.{section}.{subsection}"
            else:
                event.number = chapter_label
        else:
            counters[event.kind] += 1
            event.number = f"{chapter_label}.{counters[event.kind]}"
    return events


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------


def _clean_refs(refs: list[str], labels: list[str]) -> list[str]:
    """Recover labels whose trailing sentence punctuation was consumed.

    Typst reference syntax accepts ``.`` and ``:`` in a label, so ``@tab:x.``
    at the end of a sentence reads as the label ``tab:x.``; the real label is
    recovered when the stripped form is defined.
    """
    known = set(labels)
    cleaned: list[str] = []
    for reference in refs:
        if reference in known:
            cleaned.append(reference)
            continue
        stripped = reference.rstrip(".,;:)]}")
        cleaned.append(stripped if stripped in known else reference)
    return cleaned


def _walk_typst_blocks(blocks, specs: dict, titles: list[str]) -> None:
    """Collect object specs and heading titles, including nested wrappers."""
    for block in blocks:
        if isinstance(block, tm.THeading):
            titles.append(block.title)
        elif isinstance(block, tm.TFigure):
            specs[block.spec.label] = block.spec
        elif isinstance(block, tm.TTable):
            specs[block.spec.label] = block.spec
        elif isinstance(block, tm.TListing):
            specs[block.spec.label] = block.spec
        elif isinstance(block, tm.TEquation):
            if block.spec.label:
                specs[block.spec.label] = block.spec
        elif isinstance(block, (tm.TLandscape, tm.TAlign, tm.TBibliography)):
            _walk_typst_blocks(block.blocks, specs, titles)


class ParityVerifier:
    def __init__(self, latex_root: Path, typst_root: Path, text_tolerance: float = TEXT_TOLERANCE):
        self.latex_root = latex_root.resolve()
        self.typst_root = typst_root.resolve()
        self.text_tolerance = text_tolerance
        self.latex_project = lm.LatexProject.discover(self.latex_root)
        self.typst_project = tm.TypstProject.discover(self.typst_root)
        self.latex_pdf = self.latex_root / "main.pdf"
        self.typst_pdf = self.typst_root / "main.pdf"
        self._pdftotext_available = shutil.which("pdftotext") is not None

    # -- shared ----------------------------------------------------------

    def _latex_events(self) -> list[Event]:
        events: list[Event] = []
        includes = self.latex_project.includes + self.latex_project.extra_content
        for include in includes:
            if include.admin is not None:
                continue
            text = read_text(include.path)
            inventory = lm.scan_inventory(text, include.path)
            scanner = lm.LatexScanner(include.path, text)
            specs = {}
            titles: list[str] = []
            for block in scanner.scan():
                if isinstance(block, lm.Heading):
                    titles.append(block.title)
                elif isinstance(block, lm.Figure):
                    specs[block.spec.label] = block.spec
                elif isinstance(block, lm.Table):
                    specs[block.spec.label] = block.spec
                elif isinstance(block, lm.Listing):
                    specs[block.spec.label] = block.spec
                elif isinstance(block, lm.Equation):
                    if block.spec.label:
                        specs[block.spec.label] = block.spec
            heading_titles = iter(titles)
            for item in inventory.items:
                event = Event(
                    kind=item.kind,
                    level=item.level,
                    label=item.label,
                    appendix=include.appendix,
                )
                if item.kind == "heading":
                    title = plain_heading(next(heading_titles, ""))
                    if item.unnumbered:
                        continue
                    event.title = title
                else:
                    spec = specs.get(item.label)
                    if spec is not None:
                        event.body = getattr(spec, "body", "")
                        event.spec = spec
                events.append(event)
        return assign_numbers(events)

    def _typst_events(self) -> list[Event]:
        events: list[Event] = []
        includes = self.typst_project.includes + self.typst_project.extra_content
        for include in includes:
            text = read_text(include.path)
            inventory = tm.scan_inventory(text, include.path)
            scanner = tm.TypstScanner(include.path, text)
            specs: dict = {}
            titles: list[str] = []
            _walk_typst_blocks(scanner.scan(), specs, titles)
            headings = iter(titles)
            for item in inventory.items:
                event = Event(
                    kind=item.kind,
                    level=item.level,
                    label=item.label,
                    appendix=include.appendix,
                )
                if item.kind == "heading":
                    title = plain_heading(next(headings, ""))
                    if item.unnumbered:
                        continue
                    event.title = title
                else:
                    spec = specs.get(item.label)
                    if spec is not None:
                        event.body = getattr(spec, "body", "")
                        event.spec = spec
                events.append(event)
        return assign_numbers(events)

    # -- PDF -------------------------------------------------------------

    def _pdf_text(self, path: Path) -> str:
        if not self._pdftotext_available:
            raise VerifierError("pdftotext (poppler) is not installed")
        if not path.is_file():
            raise VerifierError(f"{path.name} is missing; build the project first")
        process = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            raise VerifierError(f"pdftotext failed for {path}: {process.stderr.strip()}")
        return process.stdout

    class _PdfUnavailable(Exception):
        pass

    def _pdf_pair(self) -> tuple[str, str] | None:
        try:
            return self._pdf_text(self.latex_pdf), self._pdf_text(self.typst_pdf)
        except VerifierError:
            return None

    # -- checks ----------------------------------------------------------

    def check_metadata(self, report: Report) -> None:
        check = report.add(Check("1", "metadata agreement"))
        try:
            from .common import parse_metadata_tex, load_metadata_json

            latex_meta = self.latex_project.metadata
            typst_meta = self.typst_project.metadata
            if latex_meta is None or not latex_meta.is_file():
                check.fail("the LaTeX project has no metadata.tex")
                return
            if typst_meta is None or not typst_meta.is_file():
                check.fail("the Typst project has no metadata.json")
                return
            latex_values = parse_metadata_tex(read_text(latex_meta), str(latex_meta))
            typst_values = load_metadata_json(typst_meta)
        except ToolError as error:
            check.fail(str(error))
            return
        check.note(f"{len(latex_values)} keys read from both projects")
        differences = 0
        for key in latex_values:
            if latex_values[key] != typst_values.get(key):
                differences += 1
                check.fail(
                    f"value drift for {key!r}: "
                    f"latex={latex_values[key]!r} typst={typst_values.get(key)!r}"
                )
        if differences == 0:
            check.note("all administrative values agree")

    def _inventory(self) -> tuple[dict[str, list], dict[str, list]]:
        def summary(events: list[Event]) -> dict[str, list]:
            result: dict[str, list] = {
                "headings": [],
                "figures": [],
                "tables": [],
                "listings": [],
                "equations": [],
                "appendix_headings": [],
            }
            for event in events:
                if event.kind == "heading":
                    tokens = tuple(plain_words(event.title))
                    result["headings"].append((event.level, event.number, tokens))
                    if event.appendix and event.level == 1:
                        result["appendix_headings"].append((event.number, tokens))
                else:
                    plural = {
                        "figure": "figures",
                        "table": "tables",
                        "listing": "listings",
                        "equation": "equations",
                    }[event.kind]
                    result[plural].append((event.number, event.label))
            return result

        return summary(self._latex_events()), summary(self._typst_events())

    def check_inventory(self, report: Report) -> None:
        check = report.add(Check("2", "object inventory and identifier order"))
        try:
            latex, typst = self._inventory()
        except ToolError as error:
            check.fail(str(error))
            return
        for name in ("headings", "figures", "tables", "listings", "equations", "appendix_headings"):
            if latex[name] == typst[name]:
                check.note(f"{name}: {len(latex[name])} matching in order")
                continue
            check.fail(f"{name}: mismatch (latex={len(latex[name])}, typst={len(typst[name])})")
            limit = min(len(latex[name]), len(typst[name]))
            for index in range(limit):
                if latex[name][index] != typst[name][index]:
                    check.fail(
                        f"  first difference at {name}[{index}]: "
                        f"latex={latex[name][index]!r} typst={typst[name][index]!r}"
                    )
                    break
        counts = {name: len(latex[name]) for name in ("figures", "tables", "listings", "equations")}
        check.note(
            "latex object counts: " + ", ".join(f"{name}={count}" for name, count in counts.items())
        )

        pdf = self._pdf_pair()
        if pdf is None:
            check.note("rendered identifier numbering not checked: PDF/pdftotext unavailable")
            return
        # Outline pages repeat every "Gambar/Tabel ..." number; they are
        # presentation and would double-count the identifiers.
        latex_text = BANNER_RE.sub(" ", selected_pages([page for page in pdf[0].split("\f") if page.strip()])[0])
        typst_text = BANNER_RE.sub(" ", selected_pages([page for page in pdf[1].split("\f") if page.strip()])[0])
        for name, pattern in RENDERED_NUMBERING_PATTERNS.items():
            left = [match.group(1) for match in re.finditer(pattern, latex_text)]
            right = [match.group(1) for match in re.finditer(pattern, typst_text)]
            if left == right:
                check.note(f"rendered {name} numbering: {len(left)} matching in order")
            else:
                check.fail(
                    f"rendered {name} numbering differs: latex={left[:20]!r} typst={right[:20]!r}"
                )

    def check_tables(self, report: Report) -> None:
        check = report.add(Check("3", "table numeric payloads"))
        latex_events = [event for event in self._latex_events() if event.kind == "table"]
        typst_events = [event for event in self._typst_events() if event.kind == "table"]
        if len(latex_events) != len(typst_events):
            check.fail(
                f"table count differs: latex={len(latex_events)} typst={len(typst_events)}"
            )
        failures = 0
        pairs = list(zip(latex_events, typst_events))
        for left, right in pairs:
            latex_payload = _latex_payload(left.spec)
            typst_payload = _typst_payload(right.spec)
            if latex_payload != typst_payload:
                failures += 1
                check.fail(
                    f"Tabel {left.number} source payload differs: "
                    f"latex={latex_payload!r} typst={typst_payload!r}"
                )
        pdf = self._pdf_pair()
        if pdf is None:
            if failures == 0 and len(latex_events) == len(typst_events):
                check.note(
                    f"{len(latex_events)} tables: source payloads identical; "
                    "rendered PDFs unavailable (skipped)"
                )
            return
        for left, _right in pairs:
            payload = _latex_payload(left.spec)
            if not payload:
                continue
            for engine, pdf_text in (("LaTeX", pdf[0]), ("Typst", pdf[1])):
                rendered, notes = table_payload_from_pdf(pdf_text, left.number)
                failure = subsequence_failure(payload, rendered)
                if failure is not None:
                    index, token = failure
                    failures += 1
                    check.fail(
                        f"Tabel {left.number} {engine} PDF payload mismatch: source token "
                        f"{index + 1}/{len(payload)} ({token!r}) missing in rendered order "
                        f"({notes[0]})"
                    )
        if failures == 0 and len(latex_events) == len(typst_events):
            check.note(
                f"{len(latex_events)} tables: source payloads identical and present in "
                "order in both rendered PDFs"
            )

    def check_listings(self, report: Report) -> None:
        check = report.add(Check("4", "listing bodies"))
        latex_events = [event for event in self._latex_events() if event.kind == "listing"]
        typst_events = [event for event in self._typst_events() if event.kind == "listing"]
        if len(latex_events) != len(typst_events):
            check.fail(f"listing count differs: latex={len(latex_events)} typst={len(typst_events)}")
        failures = 0
        for index, (left, right) in enumerate(zip(latex_events, typst_events)):
            latex_body = dedent_lines(left.body)
            typst_body = dedent_lines(right.body)
            if latex_body != typst_body:
                failures += 1
                check.fail(f"listing {index + 1} ({left.label or 'unlabelled'}) body differs")
                for line_index in range(min(len(latex_body), len(typst_body))):
                    if latex_body[line_index] != typst_body[line_index]:
                        check.fail(
                            f"  first difference at line {line_index + 1}: "
                            f"latex={latex_body[line_index]!r} "
                            f"typst={typst_body[line_index]!r}"
                        )
                        break
        if failures == 0 and len(latex_events) == len(typst_events):
            check.note(f"{len(latex_events)} listing bodies match exactly")

    def check_references(self, report: Report) -> None:
        check = report.add(Check("5", "label existence and reference resolution"))
        latex_labels: list[str] = []
        latex_refs: list[str] = []
        typst_labels: list[str] = []
        typst_refs: list[str] = []
        for include in self.latex_project.includes + self.latex_project.extra_content:
            inventory = lm.scan_inventory(read_text(include.path), include.path)
            latex_labels.extend(inventory.labels)
            latex_refs.extend(label for _command, label in inventory.refs)
        for include in self.typst_project.includes + self.typst_project.extra_content:
            inventory = tm.scan_inventory(read_text(include.path), include.path)
            typst_labels.extend(inventory.labels)
            typst_refs.extend(inventory.refs)
        latex_unique = list(dict.fromkeys(latex_labels))
        typst_unique = list(dict.fromkeys(typst_labels))
        latex_refs = _clean_refs(latex_refs, latex_unique)
        typst_refs = _clean_refs(typst_refs, typst_unique)
        missing_latex = sorted(set(latex_refs) - set(latex_unique))
        missing_typst = sorted(set(typst_refs) - set(typst_unique))
        if missing_latex:
            check.fail("latex references undefined labels: " + ", ".join(missing_latex))
        if missing_typst:
            check.fail("typst references undefined labels: " + ", ".join(missing_typst))
        if not missing_latex and not missing_typst:
            check.note(
                f"all references resolve in both sources "
                f"(latex refs={len(latex_refs)}, typst refs={len(typst_refs)})"
            )
        only_latex = [label for label in latex_unique if label not in typst_unique]
        only_typst = [label for label in typst_unique if label not in latex_unique]
        if only_latex or only_typst:
            check.fail(
                "cross-engine label sets differ: "
                f"latex-only={only_latex[:10]!r} typst-only={only_typst[:10]!r}"
            )
        else:
            check.note(f"{len(latex_unique)} labels present in both projects")
        if latex_unique != typst_unique:
            check.note("label order differs between the two sources (sets are equal)")
        pdf = self._pdf_pair()
        if pdf is None:
            check.note("rendered '??' markers not checked: PDF/pdftotext unavailable")
            return
        for name, text in (("latex", pdf[0]), ("typst", pdf[1])):
            unresolved = len(re.findall(r"\?\?", text))
            if unresolved:
                check.fail(f"{name} PDF contains {unresolved} unresolved '??' marker(s)")
        if not re.search(r"\?\?", pdf[0]) and not re.search(r"\?\?", pdf[1]):
            check.note("no unresolved '??' markers in either rendered PDF")

    def check_rendered_text(self, report: Report) -> None:
        check = report.add(Check("6", "normalised rendered-text agreement"))
        pdf = self._pdf_pair()
        if pdf is None:
            check.skip("rendered PDFs or pdftotext unavailable; build both projects to enable")
            return
        latex_pages = [page for page in pdf[0].split("\f") if page.strip()]
        typst_pages = [page for page in pdf[1].split("\f") if page.strip()]
        latex_text, latex_outline = selected_pages(latex_pages)
        typst_text, typst_outline = selected_pages(typst_pages)
        table_numbers = [
            event.number for event in self._latex_events() if event.kind == "table"
        ]
        latex_banners = BANNER_RE.findall(latex_text)
        typst_banners = BANNER_RE.findall(typst_text)
        if latex_banners or typst_banners:
            report.known_differences.append(
                {
                    "id": "longtable-continuation-banner",
                    "latex_occurrences": len(latex_banners),
                    "typst_occurrences": len(typst_banners),
                    "reason": (
                        "The multipage-table continuation banner is a longtable layout "
                        "artefact; repeated column headers are preserved in both engines. "
                        "Excluded from the word multiset."
                    ),
                    "documented_in": "docs/CONVERSION.md",
                }
            )
        latex_text = BANNER_RE.sub(" ", latex_text)
        typst_text = BANNER_RE.sub(" ", typst_text)
        latex_text, latex_removed = strip_table_regions(latex_text, table_numbers)
        typst_text, typst_removed = strip_table_regions(typst_text, table_numbers)
        report.known_differences.append(
            {
                "id": "repeated-table-headers-and-pagination",
                "latex_occurrences": latex_removed,
                "typst_occurrences": typst_removed,
                "reason": (
                    "Column-header rows repeat once per page, so their word counts depend "
                    "on each engine's pagination. Table bodies are excluded from the "
                    "rendered-text multiset and verified by check 3."
                ),
                "documented_in": "docs/CONVERSION.md",
            }
        )
        latex_urls = len(URL_RE.findall(latex_text))
        typst_urls = len(URL_RE.findall(typst_text))
        if latex_urls or typst_urls:
            report.known_differences.append(
                {
                    "id": "reference-url-line-wrapping",
                    "latex_occurrences": latex_urls,
                    "typst_occurrences": typst_urls,
                    "reason": (
                        "Long reference URLs are broken at different points by the two "
                        "layout engines; URI contents are excluded from the word multiset."
                    ),
                    "documented_in": "docs/CONVERSION.md",
                }
            )
        latex_text = URL_RE.sub(" ", latex_text)
        typst_text = URL_RE.sub(" ", typst_text)

        latex_words = [word for word in normalise_words(latex_text) if word.isalpha() and len(word) >= 2]
        typst_words = [word for word in normalise_words(typst_text) if word.isalpha() and len(word) >= 2]
        check.note(f"outline pages excluded: latex={latex_outline}, typst={typst_outline}")
        check.note("comparison scope: alphabetic prose words; numbers are covered by checks 2 and 3")
        latex_counter = Counter(latex_words)
        typst_counter = Counter(typst_words)
        difference = (latex_counter - typst_counter) + (typst_counter - latex_counter)
        total = max(len(latex_words), len(typst_words), 1)
        allowance = max(1, int(total * self.text_tolerance))
        check.note(
            f"words: latex={len(latex_words)}, typst={len(typst_words)}, "
            f"differing={sum(difference.values())} "
            f"({sum(difference.values()) / total:.4%}), tolerance={self.text_tolerance:.2%}"
        )
        if sum(difference.values()) > allowance:
            check.fail("rendered-text multisets differ beyond the documented tolerance")
            check.fail(
                "top unmatched words: "
                + ", ".join(
                    f"{word!r}: latex={latex_counter[word]} typst={typst_counter[word]}"
                    for word, _count in difference.most_common(20)
                )
            )
        else:
            check.note("rendered-text multisets agree within the documented tolerance")

    def check_admin_pages(self, report: Report) -> None:
        check = report.add(Check("7", "administrative-page text"))
        pdf = self._pdf_pair()
        if pdf is None:
            check.skip("rendered PDFs or pdftotext unavailable; build both projects to enable")
            return
        latex_pages = [page for page in pdf[0].split("\f") if page.strip()]
        typst_pages = [page for page in pdf[1].split("\f") if page.strip()]
        for name, anchor, fallback in ADMIN_PAGES:
            if name == "cover":
                latex_index, typst_index = 0, 0
            else:
                latex_index = locate_admin_page(latex_pages, anchor, fallback)
                typst_index = locate_admin_page(typst_pages, anchor, fallback)
            if latex_index is None:
                check.fail(f"{name}: page not found in the LaTeX PDF")
                continue
            if typst_index is None:
                check.fail(f"{name}: page not found in the Typst PDF")
                continue
            latex_words = normalise_words(latex_pages[latex_index])
            typst_words = normalise_words(typst_pages[typst_index])
            latex_counter = Counter(latex_words)
            typst_counter = Counter(typst_words)
            difference = (latex_counter - typst_counter) + (typst_counter - latex_counter)
            if not difference:
                check.note(f"{name}: identical text ({len(latex_words)} words)")
                continue
            check.fail(
                f"{name}: text differs (latex={len(latex_words)} words, "
                f"typst={len(typst_words)} words, differing={sum(difference.values())})"
            )
            check.fail(
                "  unmatched: "
                + ", ".join(
                    f"{word!r}: latex={latex_counter[word]} typst={typst_counter[word]}"
                    for word, _count in difference.most_common(12)
                )
            )

    # -- driver ----------------------------------------------------------

    def run(self) -> Report:
        report = Report()
        self.check_metadata(report)
        self.check_inventory(report)
        self.check_tables(report)
        self.check_listings(report)
        self.check_references(report)
        self.check_rendered_text(report)
        self.check_admin_pages(report)
        return report


# ---------------------------------------------------------------------------
# Source payloads
# ---------------------------------------------------------------------------


def _latex_payload(spec) -> list[str]:
    if spec is None:
        return []
    payload = getattr(spec, "payload", None)
    if payload is not None:
        return list(payload)
    return NUMERIC_TOKEN_RE.findall(lm.plain_latex_text(getattr(spec, "body", "")))


def _typst_payload(spec) -> list[str]:
    if spec is None:
        return []
    rows = getattr(spec, "rows", [])
    tokens: list[str] = []
    for row in rows:
        for cell in row:
            plain = re.sub(r"[*_`]", "", cell)
            plain = re.sub(r"<[^>]*>", " ", plain)
            tokens.extend(NUMERIC_TOKEN_RE.findall(plain))
    return tokens


# ---------------------------------------------------------------------------
# Text / PDF helpers
# ---------------------------------------------------------------------------


URL_RE = re.compile(r"https?://.*?\[Diakses:", re.DOTALL)
TABLE_REGION_END_RE = re.compile(
    r"(?m)^[ \t\f]*(?:"
    r"Tabel[ \t]+[0-9]+(?:\.[0-9]+)*[ \t]+\S"
    r"|Gambar[ \t]+[0-9]+(?:\.[0-9]+)*[ \t]+\S"
    r"|Kode[ \t]+Sumber[ \t]+[0-9]+(?:\.[0-9]+)*[ \t]+\S"
    r"|BAB[ \t]+[0-9A-Z]+[ \t]+\S"
    r"|LAMPIRAN[ \t]+[A-Z]+[ \t]+\S"
    r"|DAFTAR[ \t]+[A-Z]+"
    r")"
)


def selected_pages(pages: list[str]) -> tuple[str, int]:
    outline_start = _first_page_matching(pages, ("daftar isi", "table of contents"))
    if outline_start is None:
        outline_start = _first_page_matching(pages, ("daftar gambar", "daftar tabel"))
    if outline_start is None:
        return "\n".join(pages), 0
    body_start = None
    for index in range(outline_start, len(pages)):
        page = pages[index]
        # Outline entries repeat "BAB 1 ..." with dot leaders; a body page has
        # the chapter heading without them.
        if re.search(r"(?m)^[ \t]*BAB[ \t]+[0-9A-Z]+[ \t]+", page.upper()) and not re.search(
            r"\.(?:\s*\.){2,}", page
        ):
            body_start = index
            break
    end = body_start if body_start is not None else len(pages)
    return "\n".join(pages[:outline_start] + pages[end:]), end - outline_start


def _first_page_matching(pages: list[str], patterns: tuple[str, ...]) -> int | None:
    for index, page in enumerate(pages):
        lowered = page.lower()
        if any(pattern in lowered for pattern in patterns):
            return index
    return None


def table_payload_from_pdf(text: str, number: str) -> tuple[list[str], list[str]]:
    pattern = re.compile(r"(?m)^[ \t\f]*Tabel[ \t]+" + re.escape(number) + r"[ \t]+\S")
    matches = list(pattern.finditer(text))
    notes = [f"caption 'Tabel {number}' occurrences={len(matches)}"]
    if not matches:
        return [], notes
    match = matches[-1]
    region = text[match.end():]
    end_match = TABLE_REGION_END_RE.search(region)
    if end_match:
        region = region[:end_match.start()]
    payload: list[str] = []
    for line in region.splitlines():
        stripped = line.strip()
        if not stripped or BANNER_RE.match(stripped):
            continue
        if re.fullmatch(r"[0-9]+", stripped):
            continue
        payload.extend(NUMERIC_TOKEN_RE.findall(stripped))
    return payload, notes


def subsequence_failure(needle: list[str], haystack: list[str]) -> tuple[int, str] | None:
    iterator = iter(haystack)
    for index, token in enumerate(needle):
        for candidate in iterator:
            if candidate == token:
                break
        else:
            return index, token
    return None


def strip_table_regions(text: str, table_numbers: list[str]) -> tuple[str, int]:
    removed = 0
    spans: list[tuple[int, int]] = []
    for number in table_numbers:
        caption = re.compile(
            r"(?m)^[ \t\f]*Tabel[ \t]+" + re.escape(number) + r"[ \t]+\S"
        )
        matches = list(caption.finditer(text))
        if not matches:
            continue
        start = matches[-1].start()
        region = text[matches[-1].end():]
        end_match = TABLE_REGION_END_RE.search(region)
        end = matches[-1].end() + (end_match.start() if end_match else len(region))
        spans.append((start, end))
        removed += 1
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + "\n" + text[end:]
    return text, removed


# ---------------------------------------------------------------------------
# Administrative pages
# ---------------------------------------------------------------------------


ADMIN_PAGES = (
    ("cover", None, None),
    ("approval", ("lembar pengesahan",), ("menyetujui", "pembimbing")),
    ("declaration", ("pernyataan keaslian",), ("menyatakan bahwa tesis",)),
)


def locate_admin_page(
    pages: list[str], exact: tuple[str, ...] | None, fallback: tuple[str, ...] | None
) -> int | None:
    if exact:
        index = _first_page_matching(pages, exact)
        if index is not None:
            return index
    if fallback:
        for index, page in enumerate(pages):
            lowered = page.lower()
            if all(pattern in lowered for pattern in fallback):
                return index
    return None


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_human(report: Report, latex_root: Path, typst_root: Path) -> str:
    lines = [
        "Cross-engine parity verification",
        f"  LaTeX project: {latex_root}",
        f"  Typst project: {typst_root}",
        "",
    ]
    for check in report.checks:
        marker = {"ok": "PASS", "fail": "FAIL", "skip": "SKIP"}[check.status]
        lines.append(f"[{check.number}/7] {check.name} ... {marker}")
        for detail in check.details:
            if detail:
                lines.append(f"      {detail}")
        lines.append("")
    if report.known_differences:
        lines.append("Known differences (explicitly reported, not ignored):")
        for difference in report.known_differences:
            lines.append(f"  - {difference['id']}: {difference['reason']}")
            lines.append(
                f"    occurrences: latex={difference['latex_occurrences']}, "
                f"typst={difference['typst_occurrences']}; "
                f"documented in {difference['documented_in']}"
            )
        lines.append("")
    passed = sum(1 for check in report.checks if check.status == "ok")
    skipped = sum(1 for check in report.checks if check.status == "skip")
    summary = f"Summary: {passed}/{len(report.checks)} checks passed"
    if skipped:
        summary += f", {skipped} skipped"
    summary += " — PARITY OK" if not report.failed else " — PARITY FAILED"
    lines.append(summary)
    return "\n".join(lines)


def render_json(report: Report) -> str:
    payload = {
        "status": "fail" if report.failed else "ok",
        "checks": [
            {
                "number": check.number,
                "name": check.name,
                "status": check.status,
                "details": check.details,
            }
            for check in report.checks
        ],
        "known_differences": report.known_differences,
        "tolerance": {"rendered_text": TEXT_TOLERANCE},
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def verify(latex_root: Path, typst_root: Path, text_tolerance: float = TEXT_TOLERANCE) -> Report:
    return ParityVerifier(latex_root, typst_root, text_tolerance).run()


def report_text(report: Report, latex_root: Path, typst_root: Path) -> str:
    """Human-readable report (alias used by the command-line script)."""
    return render_human(report, latex_root, typst_root)


def report_json(report: Report) -> str:
    """Machine-readable report (alias used by the command-line script)."""
    return render_json(report)
