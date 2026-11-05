# Three-repository architecture

Status: frozen before assembly. This file describes the final layout.
The three repositories are siblings under the same parent directory and are shipped
independently.

## Repositories

Siblings under the same parent directory:

| Repository | Purpose |
| --- | --- |
| `thesis_template_latex/` | Self-contained LaTeX thesis starter, Overleaf-ready package, own CI |
| `thesis_template_typst/` | Self-contained Typst thesis starter, portable/Overleaf package, own CI |
| `thesis_template_tools/` | Shared conversion, metadata synchronisation and parity tooling with its own CI |

Each repository has an independent git history created with a single clean initial
commit. No repository imports code from a sibling at build time; the two template
repositories build with their own toolchain alone. The tools repository operates on
template repositories given as command-line paths.

## Template repository contract

Both template repositories are structurally equivalent:

```text
README.md                 engine-specific guide: quick start, Overleaf upload, editing
build.sh                  builds main.pdf in the repository root
main.<tex|typ>            document master: structural order and numbering only
.latexmkrc                LaTeX repository only: pdflatex/latexmk lock for Overleaf and local
overleaf.txt              import instructions at the archive root, both repositories
<engine-specific layout>  latex/preamble.tex + thesis-layout.sty | typst/template.typ
metadata.<tex|json>       administrative values (hand edited in this repository)
frontmatter/              cover, approval, declaration, abstracts, preface
chapters/bab1..7.<tex|typ>
backmatter/referensi.<tex|typ>
lampiran/lampiran_a.<tex|typ>
assets/                   logo, illustration, vector figure PDFs
examples/tikz/            LaTeX repository only: TikZ sources of those figures
fonts/                    Typst repository only: bundled fonts and licences
docs/EDITING.md           engine-specific editing guide
docs/OVERLEAF.md          exact upload steps and what the package contains
scripts/package_overleaf.sh  LaTeX repository only: builds dist/*_overleaf.zip and verifies it
.github/workflows/ci.yml  build + (LaTeX) package + extracted-package build + artifacts
.gitignore
```

Style isolation is mandatory in both repositories: `thesis-layout.sty` (LaTeX) and
`template.typ` (Typst) own every layout, font, margin, heading, caption and numbering
rule; the master file carries only structural includes and numbering transitions, so a
student editing a chapter cannot break the institutional layout.

Compiler and dependency locking is part of the contract. The LaTeX repository states
pdflatex only and ships `% !TEX program = pdflatex`, a `.latexmkrc` that reproduces the
build script, documented package ordering constraints (hyperref last, xurl after
hyperref, calc for proportional columns, sansmathfonts with nottext) and a documented
`\listfiles` diagnostic. The Typst repository states the required Typst version, bundles
its fonts, and checks the compiler version in its build script. Both repositories ship an
`overleaf.txt` with import instructions.

The LaTeX repository keeps the existing metadata/layout/content separation, Helvetica
typeface, 1.5 spacing, manual Harvard ARU bibliography and object interfaces
(`thesisfigure`, `thesistable`, listings, equations, appendix numbering, administrative
pages). The Typst repository keeps the handwritten `template.typ` interface and bundled
fonts. Both render the same placeholder manuscript: 7 chapters, 2 abstracts, 1 appendix,
6 figures, 11 tables (one multipage with repeated headers, one landscape), 2 listings,
6 display equations.

## Overleaf packaging

LaTeX repository only. The Typst repository is already a self-contained project: it has
no packaging script and no archive wrapper, because separating the repositories removed
the need for one. A user opens the Typst project directory directly in a Typst editor,
or imports the repository into an Overleaf plan that supports Typst projects.

LaTeX packaging contract:

- Script: `scripts/package_overleaf.sh`, executable, runnable from any directory.
- Output: `dist/thesis_template_latex_overleaf.zip` (git-ignored), project files at the
  archive root so `main.tex` is the top-level master.
- Contents: master, preamble, layout, metadata, front matter, chapters, backmatter,
  appendix, assets, README. Exclude build artefacts, compiled PDFs, git metadata, the
  quality scripts and `.github/`.
- Verification: the script extracts the archive into a temporary directory, builds it
  with latexmk, and fails if the extracted build does not produce a PDF. `--no-verify`
  exists for environments without the toolchain.
- CI uploads both the PDF and the zip as artifacts.

Overleaf status: LaTeX projects upload directly on every Overleaf plan. Typst support
depends on the Overleaf plan, but no packaging step is required either way.

## Tools repository contract

```text
README.md
docs/CONVERSION.md        supported constructs, limits, round-trip policy
scripts/sync_metadata.py  keeps metadata.tex and metadata.json in agreement
scripts/convert_latex_to_typst.py
scripts/convert_typst_to_latex.py
scripts/verify_parity.py  object inventory, table payloads, listing bodies, metadata,
                          references, rendered-text agreement
tests/                    fixtures and automated checks for all tools
.github/workflows/ci.yml  runs the test suite on fixtures
.gitignore
```

Command-line interface, all accepting explicit paths so nothing is hard-coded:

```sh
python3 scripts/sync_metadata.py --latex ../thesis_template_latex --typst ../thesis_template_typst [--check]
python3 scripts/convert_latex_to_typst.py --source ../thesis_template_latex --target ../thesis_template_typst [--check]
python3 scripts/convert_typst_to_latex.py --source ../thesis_template_typst --target ../thesis_template_latex [--check]
python3 scripts/verify_parity.py --latex ../thesis_template_latex --typst ../thesis_template_typst [--json]
```

Conversion policy: both directions are best-effort for the constructs used by the
shipped starters and documented as such. Conversion is never claimed to be lossless for
TikZ, merged table cells, raw Typst code, foreign LaTeX packages or bespoke layout.
Unsupported constructs fail with the file and construct named instead of being silently
dropped. `--check` compares regenerated output against the target without writing.

## Verification before delivery

1. `bash build.sh` succeeds in each template repository from a clean checkout; PDFs are
   the expected page counts (LaTeX 34, Typst about 31).
2. The LaTeX `scripts/package_overleaf.sh` builds its zip; extracting it to a temporary
   directory and building it reproduces the in-repo PDF. The zip contains `.latexmkrc`,
   `overleaf.txt` and the project files at the root. The Typst repository needs no
   packaging step and builds directly from its checkout.
2a. `overleaf.txt` exists in both repositories; the LaTeX master starts with the pdflatex
   magic comment; `.latexmkrc` reproduces the documented build; the Typst build script
   reports a clear failure when the Typst version is older than the documented minimum.
3. Tools: metadata sync is idempotent and `--check` detects drift; both converters run on
   the shipped starters; round-trip LaTeX to Typst to LaTeX preserves headings, text,
   figures, tables, listings, equations, labels, references and metadata values within
   documented limits; parity verifier passes on the shipped starters and fails on a
   deliberate mismatch fixture.
4. Each CI workflow parses and its commands exist; no secrets required.
5. No AI attribution in files or commit messages; single clean initial commit per
   repository, no pushes.
