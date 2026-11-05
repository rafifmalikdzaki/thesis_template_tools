# Bundled fonts for the Unicode engines

pdfLaTeX uses the Type1 fonts supplied by TeX Live (`helvet`, `sansmathfonts`)
and needs nothing from this directory. XeLaTeX and LuaLaTeX load the OpenType
fonts below from this directory (`Path=fonts/`), so the Unicode build is
self-contained and does not depend on a `tex-gyre` system package.

The Typst counterpart embeds its fonts so that the PDF is reproducible on a
machine without a TeX distribution.  The font binaries are unmodified copies
from the TeX Live distribution installed on the build machine.

| File | Family | Role | Licence |
| --- | --- | --- | --- |
| `texgyreheros-regular.otf` | TeX Gyre Heros | body text | GUST Font License 1.0 |
| `texgyreheros-bold.otf` | TeX Gyre Heros Bold | body text | GUST Font License 1.0 |
| `texgyreheros-italic.otf` | TeX Gyre Heros Italic | body text | GUST Font License 1.0 |
| `texgyreheros-bolditalic.otf` | TeX Gyre Heros Bold Italic | body text | GUST Font License 1.0 |
| `lmmono10-regular.otf` | Latin Modern Mono 10 | code listings | GUST Font License 1.0 / LPPL 1.3c |
| `DejaVuSans.ttf` | DejaVu Sans | fallback for symbols missing from Heros (the check mark in tables) | Bitstream Vera / DejaVu licence |

TeX Gyre Heros is a metric-compatible clone of Helvetica and therefore matches
the `helvet` setting used by the LaTeX template.  Latin Modern Mono provides a
fixed-width face for code listings.

The GUST Font License is distributed in `GUST-FONT-LICENSE.txt`; it is based on
and refers to the LaTeX Project Public License, whose full text is distributed
in `LPPL-1.3c.txt`.  The DejaVu licence is distributed in
`DEJAVU-LICENSE.txt`.

Mathematics is typeset with Typst's embedded New Computer Modern Math font, so
no additional math font binary is bundled.  Surrounding text remains
Helvetica-metric; only symbols and display equations use the math face.
