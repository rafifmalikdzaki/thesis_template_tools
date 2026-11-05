# thesis_template_tools

Shared conversion, metadata-synchronisation and parity tooling for the two
independent thesis starters.

## Three repositories

The tools are one of three sibling repositories under the same parent
directory. No repository imports from another at build time: the two template
repositories build with their own toolchain alone, and this repository operates
on them through explicit command-line paths.

| Repository | Purpose |
| --- | --- |
| `../thesis_template_latex/` | Self-contained LaTeX thesis starter (pdfLaTeX, Helvetica, manual Harvard bibliography, object interfaces in `thesis-layout.sty`) |
| `../thesis_template_typst/` | Self-contained Typst thesis starter (`template.typ` helper API, bundled fonts) |
| `thesis_template_tools/` | Conversion, metadata synchronisation and parity tooling (this repository) |

Both starters render the same placeholder manuscript: 7 chapters, 2 abstracts
(one bilingual abstract file), 1 appendix, 6 figures, 11 tables (one multipage
with repeated headers, one landscape), 2 listings and 6 display equations.

## Requirements

Python 3.11 or newer, standard library only. Optional external tools:

* `typst` — to build the Typst project;
* `latexmk` + a TeX Live installation — to build the LaTeX project;
* `pdftotext` (poppler) — to verify rendered text and rendered table payloads.

Every script takes explicit project paths, so nothing depends on the current
directory.

## Commands

```sh
# keep metadata.tex and metadata.json in agreement (default authority: LaTeX)
python3 scripts/sync_metadata.py --latex ../thesis_template_latex --typst ../thesis_template_typst
python3 scripts/sync_metadata.py --latex ../thesis_template_latex --typst ../thesis_template_typst --check

# LaTeX -> Typst manuscript conversion
python3 scripts/convert_latex_to_typst.py --source ../thesis_template_latex --target ../thesis_template_typst
python3 scripts/convert_latex_to_typst.py --source ../thesis_template_latex --target ../thesis_template_typst --check

# Typst -> LaTeX manuscript conversion (also writes .latexmkrc, overleaf.txt,
# the % !TEX program magic comment and the page-transition macros)
python3 scripts/convert_typst_to_latex.py --source ../thesis_template_typst --target ../thesis_template_latex
python3 scripts/convert_typst_to_latex.py --source ../thesis_template_typst --target ../thesis_template_latex --check

# cross-engine parity verification (add --json for machine-readable output)
python3 scripts/verify_parity.py --latex ../thesis_template_latex --typst ../thesis_template_typst
```

Both converters write only the manuscript they own: `--target` must already be
the corresponding starter, because the layout is owned by the template
repository. The LaTeX -> Typst converter requires `template.typ` in the target;
the Typst -> LaTeX converter requires `preamble.tex` and `thesis-layout.sty`.
Conversion output is deterministic; run it twice and nothing changes.

`--check` regenerates everything in memory and compares it with the target
without writing. It exits 0 when the target is up to date, 1 when files are
missing or stale, and 2 on unusable input. Converters fail with the file, line
and construct on anything they cannot map; they never drop content silently.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

The suite uses the small fixture pair under `tests/fixtures/` (a reduced LaTeX
and Typst starter, plus a deliberate mismatch overlay) and additionally runs
against the two real template repositories when they are present next to this
one; those integration tests copy the projects to a temporary directory and
skip cleanly otherwise. CI runs the same command on Python 3.12.

## Layout

```text
scripts/sync_metadata.py           metadata synchronisation
scripts/convert_latex_to_typst.py  forward converter
scripts/convert_typst_to_latex.py  reverse converter
scripts/verify_parity.py           parity verifier
scripts/thesis_tools/              shared implementation (parsers, renderers, verifier)
tests/                             unittest suite and fixtures
docs/CONVERSION.md                 supported constructs, limits and round-trip policy
.github/workflows/ci.yml           test workflow
```

Read [docs/CONVERSION.md](docs/CONVERSION.md) before relying on conversion:
both directions are best-effort for the constructs the shipped starters use,
and the documented limits (TikZ, merged cells, raw Typst code, foreign LaTeX
packages, layout differences) are intentional.
