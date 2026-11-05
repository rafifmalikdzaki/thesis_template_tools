\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{thesis}[2026/11/05 Engine-agnostic Indonesian thesis document class]

% =====================================================================
%  THESIS — document class: engine detection, fonts and document setup
% =====================================================================
%  This class makes the template engine-agnostic:
%
%    pdfLaTeX  the optimized default. T1 Type1 fonts, Helvetica-metric
%              text (helvet), sans-serif mathematics (sansmathfonts) and
%              the canonical institutional look and pagination.
%    XeLaTeX   supported. fontspec with filename-based OpenType specs:
%    LuaLaTeX  TeX Gyre Heros text, Latin Modern Mono code and Latin
%              Modern Math mathematics. Pagination may shift slightly.
%
%  The class owns the engine, font, language and mathematics setup, loads
%  metadata.tex, then hands the layout over to thesis-layout.sty. Layout
%  rules belong to the package, not here; manuscript prose belongs to
%  frontmatter/ and chapters/.
%
%  Development diagnostics: uncomment the next line to print every package
%  and class file the build resolves at the end of the log (" *File List*").
%  Attach that manifest when reporting build issues.
% \listfiles
% =====================================================================

\LoadClass[12pt,a4paper]{report}

\RequirePackage{iftex}

% ── Typeface and mathematics per engine ───────────────────────────────
% XeLaTeX/LuaLaTeX: OpenType fonts are bundled under fonts/ and loaded by
% filename with Path=fonts/, so the Unicode build needs neither a system
% tex-gyre package nor font configuration. Mathematics falls back to Latin
% Modern Math, so it differs from the pdfLaTeX sans-serif mathematics and
% pagination may shift slightly.
\newcommand{\thesis@opentypefonts}{%
  \RequirePackage{fontspec}%
  \setmainfont{texgyreheros}[%
    Path=fonts/,%
    Extension=.otf,%
    UprightFont=*-regular,%
    BoldFont=*-bold,%
    ItalicFont=*-italic,%
    BoldItalicFont=*-bolditalic]%
  \setmonofont{lmmono10-regular}[Path=fonts/, Extension=.otf]%
  \RequirePackage{amsmath}%
  \RequirePackage{amssymb}%
  \RequirePackage{unicode-math}%
  \setmathfont{latinmodern-math.otf}[Path=fonts/]
  % Latin Modern Math has no check-mark glyph; the template uses
  % \checkmark in comparison tables. Render it from bundled DejaVu Sans.
  \newfontfamily\thesis@checkmarkfont[Path=fonts/]{DejaVuSans.ttf}
  \AtBeginDocument{\renewcommand{\checkmark}{{\thesis@checkmarkfont\char"2713}}}%
}

\ifPDFTeX
  % pdfLaTeX: classic Type1 fonts. Helvetica is the Arial-compatible
  % typeface; sansmathfonts with the nottext option supplies sans-serif
  % mathematics without replacing the Helvetica text family.
  \RequirePackage[T1]{fontenc}
  \RequirePackage[scaled=1.0]{helvet}
  \renewcommand{\familydefault}{\sfdefault}
  \RequirePackage[nottext]{sansmathfonts}
  \RequirePackage{amsmath}
  \RequirePackage{amssymb}
\else\ifXeTeX
  \thesis@opentypefonts
\else\ifLuaTeX
  \thesis@opentypefonts
\else
  \ClassError{thesis}%
    {Unsupported typesetting engine}%
    {This class supports pdfLaTeX (recommended), XeLaTeX and LuaLaTeX.}%
\fi\fi\fi

% ── Language, metadata and layout ─────────────────────────────────────
\RequirePackage[indonesian]{babel}

\IfFileExists{metadata.tex}{%
  \input{metadata.tex}%
}{%
  \ClassError{thesis}%
    {Required file metadata.tex was not found in the project root}%
    {Create metadata.tex with the \string\Thesis* values; see docs/EDITING.md.}%
}

\RequirePackage{thesis-layout}

\hypersetup{
  pdftitle={\ThesisTitle},
  pdfauthor={\ThesisAuthor},
  pdfsubject={\ThesisType},
  pdfkeywords={\ThesisKeywordsID}
}
