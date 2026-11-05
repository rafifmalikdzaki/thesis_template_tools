# Conversion and verification reference

This document is the contract of the tooling: what both converters support, what
they refuse, what a round trip preserves, and how parity is verified. The
shipped starters are the reference implementation; anything outside the matrix
below fails with the file, line and construct instead of being skipped.

## Repository assumptions

The converters write the manuscript, metadata and referenced assets. They do
**not** write layout, build scripts, fonts, CI configuration or documentation:

| Direction | Target requirement | Written | Never written |
| --- | --- | --- | --- |
| LaTeX -> Typst | `template.typ` exposing `thesis-figure`, `thesis-table`, `listing`, `equation-row`, `thesis-bibliography`, `appendix`, `landscape`, `outline-page`, `cover-page`, `approval-page`, `declaration-page`, `thesis` | `main.typ`, `metadata.json`, `frontmatter/`, `chapters/`, `backmatter/`, `lampiran/`, `assets/` | `template.typ`, `fonts/`, `build.sh`, `docs/`, CI, `README.md`; the LaTeX class, package and preamble are never converted into Typst content |
| Typst -> LaTeX | a LaTeX starter exposing the layout interfaces, either class-based (`thesis.cls` + `thesis-layout.sty`) or legacy (`preamble.tex` + `thesis-layout.sty`) | `main.tex` (with `% !TEX program = pdflatex` and `\documentclass{thesis}`), `metadata.tex`, the canonical `thesis.cls` and `thesis-layout.sty`, engine-neutral `.latexmkrc`, `overleaf.txt`, `frontmatter/`, `chapters/`, `backmatter/`, `lampiran/`, `assets/` | `build.sh`, `docs/`, CI, `README.md`; a legacy `preamble.tex` is left untouched but is no longer read by the emitted class |

### LaTeX output: class-based and engine-agnostic

The Typst -> LaTeX direction emits the class-based project:

* `main.tex` starts with `% !TEX program = pdflatex` and uses
  `\documentclass{thesis}`; it no longer `\input`s a preamble.
* `thesis.cls` (canonical template, `scripts/templates/latex/`) owns the engine
  setup: `\LoadClass[12pt,a4paper]{report}`, `iftex` branches (pdfLaTeX: T1 +
  helvet + sansmathfonts + amsmath/amssymb; XeLaTeX/LuaLaTeX: fontspec with
  filename-based TeX Gyre Heros and Latin Modern Mono, plus unicode-math with
  Latin Modern Math), Indonesian `babel`, `metadata.tex`, the layout package and
  the hyperref document information.
* `thesis-layout.sty` (canonical template) owns geometry, headings, captions,
  object interfaces and the administrative pages, and never reloads an engine
  font package.
* `.latexmkrc` is engine-neutral: it defines the `$pdflatex`, `$xelatex` and
  `$lualatex` command lines and deliberately does **not** set `$pdf_mode`; the
  engine is chosen on the latexmk command line (`build.sh --engine=...` or
  Overleaf's compiler setting). No BibTeX, Biber or makeindex pass is configured.
* `overleaf.txt` recommends pdfLaTeX and explains that XeLaTeX/LuaLaTeX are
  selectable in Overleaf.

pdfLaTeX is the recommended engine (institutional Helvetica look, stable
pagination); the XeLaTeX/LuaLaTeX branch uses OpenType fonts by filename from the
TeX distribution, so no system fonts are needed but pagination may shift. Latin
Modern Math has no U+2713, so that branch renders the comparison-table check
mark (\checkmark) from DejaVu Sans; the override is inside the Unicode branch
only and must not be moved to the pdfLaTeX path.

Build/editor support files are handled explicitly:

* LaTeX -> Typst **ignores** the `% !TEX program = pdflatex` magic comment,
  `.latexmkrc`, `overleaf.txt`, `build.sh`, `examples/` and `main.pdf`; none of
  them is copied into the Typst project.
* Typst -> LaTeX **writes** a `% !TEX program = pdflatex` first line, the
  canonical `thesis.cls`/`thesis-layout.sty`, an engine-neutral `.latexmkrc`
  (pdfLaTeX/XeLaTeX/LuaLaTeX commands, no `$pdf_mode`, no BibTeX/index) and a
  root `overleaf.txt` (pdfLaTeX recommended, XeLaTeX/LuaLaTeX selectable), so the
  converted project is immediately buildable and uploadable.

### `--check` semantics

`--check` compares the target repository with what the converter would write
*now*. A hand-maintained starter is not byte-identical to generated output (its
comments, wrapping and table-cell grouping differ), so the first run on an
unconverted target reports the differing files and exits 1. Run the converter
once without `--check`, then `--check` verifies freshness and any later manual
edit is reported as drift. The same rule applies to the fixture-based tests.

## Metadata synchronisation

`sync_metadata.py --latex <repo> --typst <repo> [--check] [--from latex|typst|auto]`

* The contract is 23 fixed keys (`title` … `keywords_en`), stored as
  `\newcommand{\Thesis...}{...}` in `metadata.tex` and as a JSON object in
  `metadata.json`.
* Values are compared as **decoded strings**: LaTeX escaping is applied when
  writing `metadata.tex` and removed when reading it, so `A & B` and
  `A \& B` are the same value. Escapes covered: `\ & % $ # _ { } ~ ^ \`.
* When the files agree, nothing is rewritten — hand formatting is preserved and
  re-running is a no-op. When they disagree, `--from` selects the authority
  (default `latex`; `auto` prefers LaTeX). Missing counterparts are created from
  the existing file.
* `--check` compares values key by key and reports every drifted key; it exits 1
  for missing or disagreeing files and 2 for malformed input. It never writes.
* Unknown keys, non-string/empty/multi-line values and control characters are
  rejected.

## LaTeX -> Typst: supported constructs

| LaTeX | Typst output |
| --- | --- |
| `\chapter`, `\section`, `\subsection` (+ `\label`) | `=`, `==`, `===` headings with a trailing `<label>` |
| `\chapter*{...}` + `\addcontentsline{toc}{chapter}{...}` | `#heading(level: 1, numbering: none, outlined: true)[...]` |
| paragraphs, comments | readable markup, comments as `//` |
| `\textbf`, `\textit`, `\emph`, `\texttt`, `\underline`, `\textsuperscript`, `\textsubscript`, `\textsc` | `*...*`, `_..._`, backticks, `#underline[...]`, `#super[...]`, `#sub[...]`, `#smallcaps[...]` |
| `\ref`, `\eqref`, `\autoref` | `@label` (Typst renders the number, the supplement for objects and `(3.1)` for equations; a preceding "Gambar"/"Tabel"/"Kode Sumber" is dropped to avoid "Tabel Tabel 3.1") |
| `\url`, `\href` | `#link("...")[...]` |
| `\checkmark`, `\ldots`, dashes, typographic quotes | `✓`, `…`, `–`/`—`, `“ ” ’` |
| `\quad`, `\qquad`, `\vspace`, `\hspace`, `\medskip`, `\smallskip`, `\bigskip`, `\noindent` | `#h(...)`, `#v(...)`, paragraph spacing (no indent emitted) |
| `enumerate`, `itemize` | `+` / `-` lists |
| `figure` + `\thesisfigure{\includegraphics{...}}` + caption + label | `#thesis-figure("assets/...", caption: [...]) <label>` |
| `thesistable` + `longtable` (repeated header, `\toprule`/`\midrule`, `\multicolumn` continuation banner) | `#thesis-table(caption:, label:, columns:, align:, header:, rules:, ...cells)`; the repeated header becomes Typst's `table.header` and `\midrule` becomes `rules: (i,)` |
| `multi-page table` | the header is repeated by the `thesis-table` helper on every continuation page |
| `thesistable` + `landscape` + `longtable` | `#landscape[#thesis-table(...)]` |
| `lstlisting[language=..., caption=..., label=...]` | `#listing([caption])[```lang ... ```] <label>` |
| `equation` (+ `\label`), `equation*` | `#equation-row[$ ... $ <label>]`; a documented subset of math commands is translated (`\frac`, `\sqrt`, `\sum`, `\bar`, `\text`, relations, Greek letters, …) |
| `thesisbibliography` | `#thesis-bibliography[...]` |
| `\thesiscoverpage`, `\thesisapprovalpage`, `\thesisdeclarationpage` includes | `#cover-page()`, `#approval-page()`, `#declaration-page()` |
| `\thesiscovermatter`, `\thesisfrontmatter`, `\thesismainmatter`, `\thesisappendix` | `#cover-page()` timing / `#set page(numbering: "i")` + counter / `#set page(numbering: "1")` + counter / `#appendix()`; the macros are recognised in `main.tex` and in included files |
| `\pagenumbering{roman|arabic|gobble}`, `\setcounter{page}{n}` | the equivalent `#set page(numbering: ...)` and `#counter(page).update(n)` |
| `\tableofcontents`, `\listoffigures`, `\listoftables`, `\lstlistoflistings` | `#outline-page(...)` for headings, figures, tables and raw blocks |
| inline `$...$` and display mathematics | `$ ... $` with Typst math syntax |
| assets referenced by content and by the layout (logo) | copied to `assets/` under their original basenames |

The converter inventories every object from the raw LaTeX sources before
rendering, then asserts that the renderer emitted exactly that inventory. A
construct the inventory sees but the renderer misses is a hard error.

## LaTeX -> Typst: unsupported (hard failure with file/line/construct)

* TikZ pictures and every environment outside the supported list (including
  `align`, `cases`, `verbatim`, `minipage`, `wrapfigure`);
* merged table cells (`\multicolumn` inside a data row, `\multirow`),
  `\cline`, table column repetition (`*{n}{...}`), `L/C/R/J` column types and
  width expressions other than a single cm/mm/in/pt length;
* `\includegraphics` options (width/height belong to the layout interface),
  figures without a caption or label, tables/listings/equations whose numbering
  would be lost;
* raw TeX (`\def`, `\newcommand` inside manuscript content), foreign-package
  commands, unknown macros and unknown environments;
* unknown `lstlisting` options and languages outside the mapped set;
* `\cite`, `\bibliography`, BibTeX/BibLaTeX workflows, `\pageref`;
* math commands outside the mapped subset, display math outside an `equation`
  environment, and `\label` without an object or heading.

## Typst -> LaTeX: supported constructs

Headings (`=`, `==`, `===` with trailing labels, `#heading(level:, numbering:, outlined:)[...]`),
paragraphs and inline formatting (`*bold*`, `_italic_`, `` `raw` ``, `#emph`,
`#strong`, `#underline`, `#super`, `#sub`, `#smallcaps`, `#text(weight: "bold")`,
`#link`, `#meta.<key>`, `#v`, `#h`, `#linebreak`, `#pagebreak`), lists (`+`/`-`),
`#thesis-figure`, `#thesis-table` (multipage and inside `#landscape`; label as
`label: <...>` argument or a trailing `<label>`), `#listing` (fenced blocks),
`#equation-row` (a documented math subset), `#thesis-bibliography`, `#grid`
(converted to a `tabular`), `#align(center)` (converted to `center`),
`#appendix()` → `\thesisappendix`, page transitions → `\thesiscovermatter` /
`\thesisfrontmatter` / `\thesismainmatter`, `#include` → `\include`, and the
administrative page calls (which also generate the `frontmatter/` stub files).

Table structure maps back to the starter's `thesistable` + `longtable` shape:
column spec, repeated header (`\endfirsthead`/`\endhead` plus the continuation
banner), `\toprule`/`\midrule`/`\bottomrule`, and landscape wrapping inside the
`thesistable` environment. Listing languages outside the `listings` package
support (`json`, `yaml`, `typst`, `javascript`, …) fall back to unhighlighted
listing text — the body is preserved, only highlighting is lost.

## Typst -> LaTeX: unsupported (hard failure with file/line/construct)

* arbitrary `#let`, `#show`, `#set` rules in manuscript files (layout belongs to
  `template.typ`), unknown function calls, state/counters other than the page
  counter, and raw Typst code outside a listing;
* `grid`/table cells with merged rows or columns, column spans, or non-length
  column widths;
* `#figure`, `#table` and other Typst primitives used directly instead of the
  starter helpers; `#ref`/`#link` forms other than the supported ones;
* math outside the translated subset (matrices, cases, alignment, custom
  functions);
* figure assets that do not exist in the source project.

## Round-trip policy

Round trip (`LaTeX -> Typst -> LaTeX`) preserves **semantics, not bytes**:

* preserved: chapter/section/subsection structure and order, object counts and
  identifiers (figure/table/listing/equation labels and their numbering), table
  column structure, numeric payloads, header rows, rules and landscape flags,
  listing bodies, display-equation labels and math, label/reference sets,
  bibliography entries, administrative metadata values and page transitions;
* normalised, not preserved: paragraph line wrapping, comment layout, blank
  lines, inline spacing commands (`\medskip` → `#v(0.6em)` → `\vspace{0.6em}`),
  typographic quotes/dashes, table cell text that was grouped with braces
  (`{[X]}` renders with literal brackets in LaTeX and as plain text in the
  Typst starter), and math notation (`F_1 = 2 \cdot \frac{...}` becomes
  `$F_1 = 2 dot frac(...)$` and back to equivalent LaTeX);
* expected differences: cross-engine pagination, line breaks, list-of-*
  formatting, the LaTeX-only multipage continuation banner, URL wrapping and the
  page-count shift between pdfLaTeX and the XeLaTeX/LuaLaTeX branch. The parity
  verifier reports these explicitly instead of hiding them.

## Parity verifier

`verify_parity.py --latex <repo> --typst <repo> [--json]` performs seven checks:

1. metadata agreement, key by key, between `metadata.tex` and `metadata.json`;
2. object inventory and identifier order (headings, figures, tables, listings,
   equations, appendix headings) and, when both PDFs exist, the numbering as
   rendered;
3. table numeric payloads — source payloads must be identical, and each payload
   must appear in rendered order in both PDFs;
4. listing bodies (layout indentation and trailing whitespace normalised);
5. label existence, reference resolution and cross-engine label sets;
6. normalised rendered-text agreement: after removing the outline pages,
   continuation banners, table bodies and URLs, the alphabetic prose-word
   multisets must agree within 0.5 % (`--tolerance`); the unmatched words are
   always reported;
7. administrative-page text (cover, approval, declaration).

PDF-based checks are skipped cleanly when `main.pdf` is missing or `pdftotext`
is unavailable; the source checks always run. Exit codes: 0 parity, 1 mismatch,
2 unusable input.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

`tests/fixtures/` holds a reduced LaTeX/Typst starter pair that exercises every
supported construct, plus `tests/fixtures/mismatch_typst/` (an overlay with a
deliberately wrong table payload). Unit tests cover metadata synchronisation and
drift, both converters (including failure with file and construct, and the
build/editor support-file rules), the round trip, and parity pass/fail. The
integration tests run the real conversion and parity on the sibling template
repositories when they exist, copy them to a temporary directory, build them if
the compilers are available, and skip cleanly otherwise.
