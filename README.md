# 🧰 Thesis Template Tools

[![CI](https://github.com/rafifmalikdzaki/thesis_template_tools/actions/workflows/ci.yml/badge.svg)](https://github.com/rafifmalikdzaki/thesis_template_tools/actions/workflows/ci.yml)

Shared conversion, metadata-synchronisation and parity tooling for the two independent
thesis starters. Nothing here is imported at build time: each template repository builds
with its own toolchain alone, and these scripts operate on them through explicit
command-line paths.

## 🧭 The Three Repositories

| Repository | Purpose |
| :--- | :--- |
| [`thesis_template`](https://github.com/rafifmalikdzaki/thesis_template) | Class-based, engine-agnostic LaTeX starter: `thesis.cls` (pdfLaTeX default/recommended, XeLaTeX/LuaLaTeX selectable from bundled `fonts/`) and `thesis-layout.sty` (layout, object interfaces, manual Harvard bibliography) |
| [`thesis_template_typst`](https://github.com/rafifmalikdzaki/thesis_template_typst) | Self-contained Typst starter (`template.typ` helper API, bundled fonts) |
| `thesis_template_tools` | Conversion, metadata synchronisation and parity verification (this repository) |

Both starters render the same placeholder manuscript: 7 chapters, 2 abstracts, 1 appendix,
6 figures, 11 tables (one multipage with repeated headers, one landscape), 2 listings and
6 display equations.

## ✨ What It Does

- **`sync_metadata.py`** — keeps the LaTeX `metadata.tex` and the Typst `metadata.json` in
  agreement, with LaTeX escaping handled correctly. Use `--check` in CI.
- **`convert_latex_to_typst.py`** — turns the LaTeX starter into an equivalent native
  Typst project, using the Typst helper API (`thesis-figure`, `thesis-table`, `listing`,
  `equation-row`, appendix and administrative pages).
- **`convert_typst_to_latex.py`** — the reverse direction, producing the class-based
  LaTeX project: `main.tex` with `% !TEX program = pdflatex` and
  `\documentclass{thesis}`, the canonical `thesis.cls` and `thesis-layout.sty`, the
  bundled `fonts/` directory, an engine-neutral `.latexmkrc` and `overleaf.txt`.
- **`verify_parity.py`** — checks that both projects describe the same manuscript:
  object inventory and numbering, table payloads, listing bodies, labels and references,
  metadata, rendered-text agreement and administrative pages.

## 🚀 Requirements

- Python 3.11 or newer, standard library only.
- Optional: `typst` to build the Typst project, `latexmk` with TeX Live to build the
  LaTeX project, and `pdftotext` (poppler) for rendered-text and rendered-table checks.

Nothing needs installing beyond Python; the scripts take explicit project paths, so they
work from any directory.

## ⚡ Quick Start

```bash
git clone https://github.com/rafifmalikdzaki/thesis_template_tools.git
cd thesis_template_tools
```

```bash
# keep the two metadata files aligned (default authority: LaTeX)
python3 scripts/sync_metadata.py \
    --latex ../thesis_template --typst ../thesis_template_typst
python3 scripts/sync_metadata.py \
    --latex ../thesis_template --typst ../thesis_template_typst --check

# convert one engine into the other
python3 scripts/convert_latex_to_typst.py \
    --source ../thesis_template --target ../thesis_template_typst
python3 scripts/convert_typst_to_latex.py \
    --source ../thesis_template_typst --target ../thesis_template

# verify that both render the same manuscript
python3 scripts/verify_parity.py \
    --latex ../thesis_template --typst ../thesis_template_typst
```

Every command has `--check`: it regenerates in memory and reports drift instead of
writing, which is what CI uses.

## 🔄 Conversion Coverage and Limits

Supported in both directions: headings and sections, paragraphs and inline formatting,
lists, figures with vector assets, multipage tables (with repeating headers), landscape
tables, listings, display equations, labels and references, the bibliography, metadata,
appendices, page-numbering transitions and the administrative pages.

LaTeX output is class-based, engine-agnostic and self-contained: pdfLaTeX is the
recommended default, while XeLaTeX and LuaLaTeX are selectable
(`bash build.sh --engine=xelatex`) through the `iftex` branches in `thesis.cls`. The
converted project carries its own `fonts/` (TeX Gyre Heros, Latin Modern Mono/Math,
DejaVu Sans and their licences), loaded with `Path=fonts/`, so the Unicode build needs no
system `tex-gyre` package. Legacy `preamble.tex` starters are still accepted as
conversion sources and targets; the converter replaces that boilerplate with the
canonical class.

Deliberately unsupported, and failed loudly with the file and construct named instead of
being dropped silently: TikZ diagrams (a LaTeX-only extension), merged table cells, raw
Typst code, foreign LaTeX packages and bespoke layout commands, and any construct the
converter cannot map exactly.

A round trip (LaTeX → Typst → LaTeX) preserves the manuscript semantically — objects,
identifiers, values and text — not byte for byte. The exact matrix and the known
differences are documented in [`docs/CONVERSION.md`](docs/CONVERSION.md).

## 🧪 Tests

```bash
python3 -m unittest discover -s tests -v
```

The suite covers metadata sync and drift detection, both converters, the round trip,
parity verification and a deliberate mismatch fixture. Tests that need the two real
template repositories skip cleanly when they are not checked out as siblings.

## 🤖 CI

On every push and pull request, GitHub Actions runs the test suite on fixtures with
Python 3.12. The real-repository integration tests run locally when the sibling
repositories are present.

## 📚 Documentation

- [`docs/CONVERSION.md`](docs/CONVERSION.md) — supported constructs, failure behaviour,
  round-trip policy and known differences.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how the three repositories relate, the
  metadata contract and the verification criteria.
- [`README` of the LaTeX starter](https://github.com/rafifmalikdzaki/thesis_template#readme)
  and [of the Typst starter](https://github.com/rafifmalikdzaki/thesis_template_typst#readme)
  for the author-facing documentation.

---
*Write once, verify twice. Selamat menulis! 🎓*
