"""Typst -> LaTeX conversion.

The reverse direction is deliberately best-effort: it converts the constructs
the Typst starter actually uses (headings, text, lists, figures, multipage and
landscape tables, listings, display equations, labels, references,
bibliography entries, metadata, appendix and administrative pages) and refuses
anything else with file, line and construct.  See ``docs/CONVERSION.md`` for the
documented limits.

The converter emits the class-based, engine-agnostic LaTeX project: the
manuscript, ``metadata.tex``, the canonical ``thesis.cls`` and
``thesis-layout.sty`` templates, an engine-neutral ``.latexmkrc`` (pdfLaTeX,
XeLaTeX and LuaLaTeX command lines, no ``$pdf_mode``) and ``overleaf.txt``
(pdfLaTeX recommended, XeLaTeX/LuaLaTeX selectable).  The target must be a
LaTeX thesis starter — class-based ``thesis.cls`` or the legacy
``preamble.tex`` layout — because the converter reuses its manuscript
structure and assets, but it writes the canonical class and layout itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import typst_model as tm
from .common import (
    ConversionError,
    ToolError,
    latex_escape,
    read_text,
    render_metadata_tex,
    load_metadata_json,
)
from .to_typst import ConversionResult, _dedent

# Canonical class/package templates: build boilerplate emitted verbatim.
TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "latex"
TEMPLATE_FILES: tuple[str, ...] = ("thesis.cls", "thesis-layout.sty")

# Engine-neutral latexmk configuration: the engine is chosen on the command
# line (-pdf/-xelatex/-lualatex) by build.sh or Overleaf, so no $pdf_mode is
# fixed here.  No BibTeX/Biber and no makeindex pass is needed.
LATEXMKRC = """\
# latexmk configuration for the engine-agnostic thesis project.
#
# The engine is selected on the latexmk command line (-pdf for pdfLaTeX,
# -xelatex, -lualatex) by build.sh or by Overleaf's compiler setting, so this
# file defines the per-engine command strings and does NOT set $pdf_mode.
# pdfLaTeX is the recommended default (Helvetica text, sans-serif
# mathematics via sansmathfonts, stable pagination); XeLaTeX and LuaLaTeX use
# fontspec and Latin Modern Math, so pagination may shift slightly.
#
# thesis.cls owns the engine-specific font setup; metadata.tex is read by the
# class, and the bibliography is manually maintained Harvard text in
# backmatter/referensi.tex. No BibTeX, Biber or makeindex pass is needed.

$pdflatex = 'pdflatex -file-line-error -synctex=1 -interaction=nonstopmode -halt-on-error %O %S';
$xelatex = 'xelatex -file-line-error -synctex=1 -interaction=nonstopmode -halt-on-error %O %S';
$lualatex = 'lualatex -file-line-error -synctex=1 -interaction=nonstopmode -halt-on-error %O %S';

$bibtex_use = 0;  # never run BibTeX: the bibliography is manual text
$makeindex = '';  # no index in this document

@default_files = ('main.tex');
"""

OVERLEAF = """\
Overleaf import instructions
============================

This project is a class-based, engine-agnostic LaTeX project. pdfLaTeX is the
recommended compiler; XeLaTeX and LuaLaTeX are also supported.

1. Zip this repository directory (or upload it as a project folder).
2. In Overleaf choose "New Project -> Upload Project" and select the archive.
3. Open Menu -> Compiler. Select "pdfLaTeX" (recommended). "XeLaTeX" or
   "LuaLaTeX" may be selected instead: thesis.cls then loads fontspec,
   unicode-math and the filename-based TeX Gyre / Latin Modern fonts from the
   TeX distribution, so no system fonts are required. Pagination may shift.
4. The main document is main.tex; Overleaf detects it automatically. If it
   does not, set "Main document" to main.tex in the project settings.
5. Build. No bibliography tool (BibTeX/Biber) and no makeindex pass is
   required: the bibliography is a manually maintained Harvard ARU list.

The build can also be run locally, with an optional engine selection:
  bash build.sh                      # pdfLaTeX (default, recommended)
  bash build.sh --engine=xelatex     # XeLaTeX
  bash build.sh --engine=lualatex    # LuaLaTeX
"""



@dataclass
class ReverseResult(ConversionResult):
    pass


def convert_typst_to_latex(source: Path, target: Path) -> ReverseResult:
    project = tm.TypstProject.discover(source)
    project.validate_interface()
    _validate_target(target)
    if project.metadata is None or not project.metadata.is_file():
        raise ToolError(f"{project.root}: metadata.json is missing")
    metadata = load_metadata_json(project.metadata)
    label_kinds = _collect_label_kinds(project)

    result = ReverseResult()
    result.files["metadata.tex"] = render_metadata_tex(
        metadata, generator="scripts/sync_metadata.py"
    )
    for name in TEMPLATE_FILES:
        result.files[name] = _template(name)
    result.files[".latexmkrc"] = LATEXMKRC
    result.files["overleaf.txt"] = OVERLEAF
    result.files["main.tex"] = _render_main(project, label_kinds, result)

    for include in project.includes + project.extra_content:
        text = read_text(include.path)
        result.files[_to_tex_path(include.rel)] = _render_content(
            project, include, label_kinds, result
        )

    for referenced in _referenced_assets(project, result):
        result.assets["assets/" + referenced.name] = referenced
    return result


def _template(name: str) -> str:
    path = TEMPLATES / name
    if not path.is_file():
        raise ToolError(
            f"canonical LaTeX template is missing: {path}; "
            "the tools repository is incomplete"
        )
    return read_text(path)


def _validate_target(target: Path) -> None:
    """Accept a class-based (thesis.cls) or legacy (preamble.tex) starter."""
    target = target.resolve()
    if not target.is_dir():
        raise ToolError(f"target directory does not exist: {target}")
    class_file = target / "thesis.cls"
    preamble = target / "preamble.tex"
    layout = target / "thesis-layout.sty"
    if not layout.is_file():
        raise ToolError(
            f"{target}: thesis-layout.sty is missing; the target must be the LaTeX "
            "thesis starter (class-based thesis.cls or legacy preamble.tex layout)"
        )
    if not class_file.is_file() and not preamble.is_file():
        raise ToolError(
            f"{target}: neither thesis.cls nor preamble.tex is present; the target "
            "must be the LaTeX thesis starter"
        )
    layout_text = read_text(layout)
    for interface in tm.REQUIRED_LATEX_INTERFACES:
        if interface not in layout_text:
            raise ToolError(
                f"{layout}: missing interface {interface}; "
                "the target does not expose the LaTeX starter interface"
            )


def _to_tex_path(rel_typ: str) -> str:
    if rel_typ.endswith(".typ"):
        return rel_typ[:-4] + ".tex"
    return rel_typ + ".tex"


def _collect_label_kinds(project: tm.TypstProject) -> dict[str, str]:
    kinds: dict[str, str] = {}
    for include in project.includes + project.extra_content:
        inventory = tm.scan_inventory(read_text(include.path), include.path)
        for item in inventory.items:
            if item.label:
                kinds[item.label] = item.kind
    return kinds


def _referenced_assets(project: tm.TypstProject, result: ReverseResult) -> list[Path]:
    assets: dict[str, Path] = {}
    root = project.root
    for relative in result.files:
        if not relative.endswith(".tex"):
            continue
        for match in re.finditer(r"\\includegraphics\s*\{([^}]*)\}", result.files[relative]):
            reference = match.group(1).strip()
            if not reference:
                continue
            candidate = (root / reference)
            if not candidate.is_file():
                candidate = (root / "assets" / Path(reference).name)
            if not candidate.is_file():
                raise ToolError(f"figure asset {reference!r} is missing from {root}")
            assets[candidate.name] = candidate
    return list(assets.values())


# ---------------------------------------------------------------------------
# Main document
# ---------------------------------------------------------------------------


def _render_main(
    project: tm.TypstProject, label_kinds: dict[str, str], result: ReverseResult
) -> str:
    text = read_text(project.main)
    blocks = tm.TypstScanner(project.main, text).scan()
    lines: list[str] = [
        "% !TEX program = pdflatex",
        "% =====================================================================",
        "%  TEMPLATE TESIS — BERKAS INDUK",
        "% =====================================================================",
        "%  Generated from the Typst master by scripts/convert_typst_to_latex.py.",
        "%  The master only fixes document order and page-numbering transitions.",
        "%  thesis.cls → engine, fonts, language, mathematics, metadata",
        "%  thesis-layout.sty → layout and object interfaces",
        "%  metadata.tex → administrative values",
        "%  frontmatter/ → front matter   chapters/ → chapters",
        "%  backmatter/ → bibliography    lampiran/ → appendix (letter numbering)",
        "% =====================================================================",
        "",
        "\\documentclass{thesis}",
        "",
        "\\begin{document}",
        "",
    ]
    for block in blocks:
        if isinstance(block, tm.TComment):
            body = block.text.lstrip("/").strip()
            lines.append(("% " + body) if body else "%")
            continue
        if isinstance(block, tm.TStructural):
            rendered = _main_structural(project, block, result)
            if rendered:
                lines.extend(rendered.split("\n"))
            continue
        if isinstance(block, tm.TPageBreak):
            lines.append("\\clearpage")
            continue
        raise ConversionError(
            project.main,
            f"content {type(block).__name__} in the Typst master",
            getattr(block, "line", None),
        )
    lines.extend(["", "\\end{document}", ""])
    return _join_lines(lines)


def _main_structural(project: tm.TypstProject, block: tm.TStructural, result: ReverseResult) -> str | None:
    kind = block.kind
    if kind in ("import", "show", "set"):
        return None
    if kind == "include":
        relative = block.argument or ""
        return "\\include{" + relative[:-4] + "}" if relative.endswith(".typ") else "\\include{" + relative + "}"
    if kind == "page-numbering":
        project._last_transition = True
        if block.argument is None:
            return "\\thesiscovermatter"
        return "\\thesisfrontmatter" if block.argument == "i" else "\\thesismainmatter"
    if kind == "page-counter":
        match = re.search(r"update\(\s*([0-9]+)\s*\)", block.argument or "")
        if match is None:
            raise ConversionError(project.main, "#counter(page) without a numeric update", block.line)
        if match.group(1) == "1" and getattr(project, "_last_transition", False):
            project._last_transition = False
            return None
        return "\\setcounter{page}{" + match.group(1) + "}"
    if kind == "outline":
        title = block.argument or ""
        command = {
            "Daftar Isi": "\\tableofcontents",
            "Daftar Gambar": "\\listoffigures",
            "Daftar Tabel": "\\listoftables",
            "Daftar Kode Sumber": "\\lstlistoflistings",
        }.get(title)
        if command is None:
            raise ConversionError(project.main, f"outline page {title!r}", block.line)
        return command
    if kind == "appendix":
        return "\\thesisappendix"
    if kind == "admin":
        stub = _ADMIN_STUBS[block.argument]
        relative, macro = stub
        result.files[relative] = macro + "\n"
        if block.argument == "cover":
            # The cover carries no page number, as in the LaTeX starter.
            return "\\thesiscovermatter\n\\include{" + relative[:-4] + "}"
        return "\\include{" + relative[:-4] + "}"
    raise ConversionError(project.main, f"#{kind}", block.line)


_ADMIN_STUBS: dict[str, tuple[str, str]] = {
    "cover": ("frontmatter/cover.tex", "\\thesiscoverpage"),
    "approval": ("frontmatter/lembar_pengesahan.tex", "\\thesisapprovalpage"),
    "declaration": ("frontmatter/pernyataan_keaslian.tex", "\\thesisdeclarationpage"),
}


def _join_lines(lines: list[str]) -> str:
    output: list[str] = []
    for line in lines:
        if not line.strip():
            if output and output[-1] == "":
                continue
            output.append("")
        else:
            output.append(line)
    return "\n".join(output).rstrip("\n") + "\n"


# ---------------------------------------------------------------------------
# Content files
# ---------------------------------------------------------------------------


@dataclass
class _Context:
    project: tm.TypstProject
    include: tm.TypstInclude
    label_kinds: dict[str, str]
    result: ReverseResult
    consumed: dict[str, list] = field(
        default_factory=lambda: {name: [] for name in ("heading", "figure", "table", "listing", "equation")}
    )

    @property
    def path(self) -> Path:
        return self.include.path


def _render_content(
    project: tm.TypstProject,
    include: tm.TypstInclude,
    label_kinds: dict[str, str],
    result: ReverseResult,
) -> str:
    text = read_text(include.path)
    inventory = tm.scan_inventory(text, include.path)
    blocks = tm.TypstScanner(include.path, text).scan()
    context = _Context(project=project, include=include, label_kinds=label_kinds, result=result)
    rendered: list[str] = []
    for block in blocks:
        output = _render_block(context, block)
        if output is not None and output.strip():
            rendered.append(output)
    _check_inventory(inventory, context.consumed, include.path)
    header = f"% Generated from {include.rel} by scripts/convert_typst_to_latex.py.\n"
    return header + "\n\n".join(rendered) + "\n"


def _check_inventory(inventory: tm.TypstInventory, consumed: dict[str, list], path: Path) -> None:
    expected = {
        kind: [(item.label, item.level) for item in inventory.items if item.kind == kind]
        for kind in ("heading", "figure", "table", "listing", "equation")
    }
    for kind in expected:
        if expected[kind] != consumed[kind]:
            raise ConversionError(
                path,
                f"internal inventory mismatch for {kind}: parsed {expected[kind]!r} "
                f"but rendered {consumed[kind]!r}",
            )


def _render_block(context: _Context, block) -> str | None:
    if isinstance(block, tm.TComment):
        body = block.text.lstrip("/").strip()
        return ("% " + body) if body else "%"
    if isinstance(block, tm.THeading):
        return _heading(context, block)
    if isinstance(block, tm.TParagraph):
        return _inline(block.text, context.path, block.line, context)
    if isinstance(block, tm.TFigure):
        return _figure(context, block.spec)
    if isinstance(block, tm.TTable):
        return _table(context, block.spec)
    if isinstance(block, tm.TListing):
        return _listing(context, block.spec)
    if isinstance(block, tm.TEquation):
        return _equation(context, block.spec)
    if isinstance(block, tm.TList):
        marker = "enumerate" if block.ordered else "itemize"
        lines = [f"\\begin{{{marker}}}"]
        for item in block.items:
            rendered = _inline(item, context.path, block.line, context)
            # ``\\item{}`` keeps a leading "[...]" from being parsed as the
            # optional custom label of \item.
            lines.append("  \\item{} " + rendered.replace("\n", "\n        "))
        lines.append(f"\\end{{{marker}}}")
        return "\n".join(lines)
    if isinstance(block, tm.TLandscape):
        content = [nested for nested in block.blocks if not isinstance(nested, tm.TComment)]
        if len(content) == 1 and isinstance(content[0], tm.TTable):
            # The LaTeX starter wraps the longtable from inside thesistable:
            #   \begin{thesistable}\begin{landscape}\begin{longtable}...
            return _table(context, content[0].spec, landscape=True)
        rendered = []
        for nested in block.blocks:
            output = _render_block(context, nested)
            if output is not None and output.strip():
                rendered.append(output)
        body = "\n\n".join(rendered)
        return "\\begin{landscape}\n" + body + "\n\\end{landscape}"
    if isinstance(block, tm.TBibliography):
        rendered = []
        for nested in block.blocks:
            output = _render_block(context, nested)
            if output is not None and output.strip():
                rendered.append(output)
        body = "\n\n".join(rendered)
        return "\\begin{thesisbibliography}\n\n" + body + "\n\n\\end{thesisbibliography}"
    if isinstance(block, tm.TAlign):
        rendered = []
        for nested in block.blocks:
            output = _render_block(context, nested)
            if output is not None and output.strip():
                rendered.append(output)
        body = "\n\n".join(rendered)
        return "\\begin{center}\n" + body + "\n\\end{center}"
    if isinstance(block, tm.TGrid):
        return _grid(context, block)
    if isinstance(block, tm.TPageBreak):
        return "\\clearpage"
    if isinstance(block, tm.TStructural):
        if block.kind in ("import", "set", "show"):
            return None
        if block.kind == "pagebreak":
            return "\\clearpage"
        if block.kind == "appendix":
            return "\\thesisappendix"
        if block.kind == "include":
            relative = block.argument or ""
            return "\\include{" + (relative[:-4] if relative.endswith(".typ") else relative) + "}"
        raise ConversionError(context.path, f"#{block.kind}", block.line)
    raise ConversionError(context.path, f"block {type(block).__name__}")


def _heading(context: _Context, block: tm.THeading) -> str:
    context.consumed["heading"].append((block.label, block.level))
    title = _inline(block.title, context.path, block.line, context)
    if block.numbered:
        command = {1: "chapter", 2: "section", 3: "subsection"}.get(block.level)
        if command is None:
            raise ConversionError(context.path, f"heading level {block.level}", block.line)
        text = f"\\{command}{{{title}}}"
    else:
        command = {1: "chapter", 2: "section", 3: "subsection"}.get(block.level)
        if command is None:
            raise ConversionError(context.path, f"heading level {block.level}", block.line)
        text = f"\\{command}*{{{title}}}"
        if block.outlined:
            text += f"\n\\addcontentsline{{toc}}{{{command}}}{{{title}}}"
    if block.label:
        text += f"\n\\label{{{block.label}}}"
    return text


def _figure(context: _Context, spec: tm.TypstFigure) -> str:
    context.consumed["figure"].append((spec.label, 0))
    caption = _inline(spec.caption, context.path, spec.line, context)
    return (
        "\\begin{figure}[H]\n"
        "  \\centering\n"
        f"  \\thesisfigure{{\\includegraphics{{{spec.path}}}}}\n"
        f"  \\caption{{{caption}}}\n"
        f"  \\label{{{spec.label}}}\n"
        "\\end{figure}"
    )


def _table_columns(spec: tm.TypstTable) -> list[str | None]:
    if spec.columns is None:
        return [None] * len(spec.rows[0])
    return list(spec.columns)


def _table(context: _Context, spec: tm.TypstTable, landscape: bool | None = None) -> str:
    context.consumed["table"].append((spec.label, 0))
    if landscape is not None:
        spec.landscape = landscape
    columns = _table_columns(spec)
    if len(columns) != len(spec.rows[0]):
        raise ConversionError(context.path, "thesis-table column count mismatch", spec.line)
    align = spec.align if len(spec.align) > 1 else spec.align * len(columns)
    parts: list[str] = []
    for index, (width, alignment) in enumerate(zip(columns, align)):
        letter = {"left": "l", "center": "c", "right": "r"}.get(alignment, "l")
        if width in (None, "auto"):
            parts.append(letter)
        elif alignment == "left":
            parts.append(f"p{{{width}}}")
        elif alignment == "center":
            parts.append(f">{{\\centering\\arraybackslash}}p{{{width}}}")
        else:
            parts.append(f">{{\\raggedleft\\arraybackslash}}p{{{width}}}")
    colspec = "@{}" + " ".join(parts) + "@{}"
    width = len(columns)
    caption = _inline(spec.caption, context.path, spec.line, context)
    header_cells = [
        _inline(tm.content_text(cell), context.path, spec.line, context) for cell in spec.header
    ]
    header_row = " & ".join(header_cells) + " \\\\"
    lines = [
        "\\begin{thesistable}",
    ]
    if spec.landscape:
        lines.append("\\begin{landscape}")
    lines.extend(
        [
            f"\\begin{{longtable}}{{{colspec}}}",
            f"  \\caption{{{caption}}}",
            f"  \\label{{{spec.label}}}\\\\",
            "  \\toprule",
            "  " + header_row,
            "  \\midrule",
            "  \\endfirsthead",
            f"  \\multicolumn{{{width}}}{{@{{}}l}}{{\\footnotesize\\itshape Lanjutan Tabel~\\thetable}}\\\\",
            "  \\toprule",
            "  " + header_row,
            "  \\midrule",
            "  \\endhead",
            "  \\bottomrule",
            "  \\endfoot",
            "  \\bottomrule",
            "  \\endlastfoot",
        ]
    )
    for index, row in enumerate(spec.rows):
        if index in spec.rules:
            lines.append("  \\midrule")
        cells = [_inline(cell, context.path, spec.line, context) for cell in row]
        if cells and cells[0].startswith("["):
            # ``\\[2cm]`` row spacing is an optional argument of ``\\``;
            # ``{}`` keeps a cell that starts with "[" from being read as it.
            cells[0] = "{}" + cells[0]
        lines.append("  " + " & ".join(cells) + " \\\\")
    lines.append("\\end{longtable}")
    if spec.landscape:
        lines.append("\\end{landscape}")
    lines.append("\\end{thesistable}")
    return "\n".join(lines)


def _listing(context: _Context, spec: tm.TypstListing) -> str:
    context.consumed["listing"].append((spec.label, 0))
    language = _latex_language(spec.language, context.path, spec.line)
    options = []
    if language is not None:
        options.append(f"language={language}")
    caption = _inline(spec.caption, context.path, spec.line, context)
    options.append(f"caption={{{caption}}}")
    options.append(f"label={{{spec.label}}}")
    body = _dedent(spec.body)
    return (
        "\\begin{lstlisting}[" + ", ".join(options) + "]\n"
        + body
        + "\n\\end{lstlisting}"
    )


def _equation(context: _Context, spec: tm.TypstEquation) -> str:
    context.consumed["equation"].append((spec.label, 0))
    math = typst_math_to_latex(spec.math, context.path, spec.line)
    lines = ["\\begin{equation}", "  " + math]
    if spec.label:
        lines.append(f"  \\label{{{spec.label}}}")
    lines.append("\\end{equation}")
    return "\n".join(lines)


def _grid(context: _Context, block: tm.TGrid) -> str:
    columns = block.columns or ["auto"]
    parts: list[str] = []
    for width in columns:
        parts.append("l" if width == "auto" else f"p{{{width}}}")
    colspec = "@{}" + " ".join(parts) + "@{}"
    width = len(columns)
    lines = [f"\\begin{{tabular}}{{{colspec}}}"]
    for index in range(0, len(block.cells), width):
        row = block.cells[index:index + width]
        cells = [_inline(cell, context.path, block.line, context) for cell in row]
        lines.append(" & ".join(cells) + " \\\\")
    lines.append("\\end{tabular}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Inline Typst -> LaTeX
# ---------------------------------------------------------------------------


def _inline(text: str, path: Path, line: int, context: _Context) -> str:
    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        character = text[index]
        if character == "$":
            end = _closing_dollar(text, index)
            math = typst_math_to_latex(text[index + 1:end], path, line)
            out.append("$" + math + "$")
            index = end + 1
            continue
        if character == "#":
            rendered, index = _inline_call(text, index, path, line, context)
            out.append(rendered)
            continue
        if character == "*" or character == "_":
            end = _find_markup_close(text, index, character)
            body = _inline(text[index + 1:end], path, line, context)
            out.append(("\\textbf{" if character == "*" else "\\emph{") + body + "}")
            index = end + 1
            continue
        if character == "`":
            end = text.find("`", index + 1)
            if end < 0:
                raise ConversionError(path, "unterminated inline raw text", line)
            out.append("\\texttt{" + _latex_escape_text(text[index + 1:end]) + "}")
            index = end + 1
            continue
        if character == "@":
            match = re.match(r"@([A-Za-z][A-Za-z0-9_.:-]*)", text[index:])
            if match is None:
                out.append("@")
                index += 1
                continue
            label = match.group(1)
            if label not in context.label_kinds:
                # Typst ends a reference at punctuation; strip it when the
                # stripped form is the real label ("@tab:3.dataset.").
                stripped = label.rstrip(".,;:)]}")
                if stripped in context.label_kinds:
                    label = stripped
            kind = context.label_kinds.get(label)
            command = "eqref" if kind == "equation" else "ref"
            noun = {"figure": "Gambar", "table": "Tabel", "listing": "Kode Sumber"}.get(kind)
            if noun is not None:
                previous = "".join(out)
                if not re.search(r"(?:^|\s)" + re.escape(noun) + r"\s*$", previous):
                    out.append(noun + "~")
            out.append(f"\\{command}{{{label}}}")
            index += match.end()
            continue
        if character == "\\":
            out.append(_typst_escape_to_latex(text, index, path, line))
            index += 2
            continue
        if text.startswith("---", index):
            out.append("---")
            index += 3
            continue
        out.append(_latex_escape_char(character))
        index += 1
    return "".join(out)


def _inline_call(
    text: str, index: int, path: Path, line: int, context: _Context
) -> tuple[str, int]:
    name, arguments, end = tm.parse_call(text, index)
    if name == "meta":
        match = re.match(r"#meta\.([A-Za-z_][A-Za-z0-9_]*)", text[index:])
        if match is None:
            raise ConversionError(path, "#meta without a field", line)
        from .common import KEY_TO_COMMAND

        field = match.group(1)
        if field not in KEY_TO_COMMAND:
            raise ConversionError(path, f"metadata field {field!r}", line)
        return "\\" + KEY_TO_COMMAND[field], index + match.end()
    if name in ("v", "h"):
        value = arguments.strip()
        if value.startswith("(") and value.endswith(")"):
            value = value[1:-1].strip()
        return ("\\vspace{" if name == "v" else "\\hspace{") + _latex_escape_text(value) + "}", end
    if name == "linebreak":
        # ``{}`` stops LaTeX from reading a following "[" as an optional
        # argument of ``\\`` (common when a line starts with a placeholder).
        return "\\\\{}", end
    if name == "pagebreak":
        return "\\clearpage", end
    if name in ("emph", "strong", "underline", "super", "sub", "smallcaps", "footnote"):
        body = tm.content_text(arguments)
        command = {
            "emph": "emph",
            "strong": "textbf",
            "underline": "underline",
            "super": "textsuperscript",
            "sub": "textsubscript",
            "smallcaps": "textsc",
            "footnote": "footnote",
        }[name]
        return "\\" + command + "{" + _inline(body, path, line, context) + "}", end
    if name == "text":
        named, positional = tm.parse_arguments(arguments)
        weight = named.get("weight", "").strip()
        body = tm.content_text(positional[0]) if positional else ""
        if weight in ('"bold"', '"semibold"'):
            return "\\textbf{" + _inline(body, path, line, context) + "}", end
        if weight in ('"regular"', '""', "none"):
            return _inline(body, path, line, context), end
        raise ConversionError(path, f"#text(weight: {weight})", line)
    if name == "raw":
        named, positional = tm.parse_arguments(arguments)
        body = tm.content_text(positional[0]) if positional else ""
        return "\\texttt{" + _latex_escape_text(body) + "}", end
    if name == "link":
        positional = tm.split_arguments(arguments)
        if not positional:
            raise ConversionError(path, "#link without a target", line)
        target = tm.literal_text(positional[0])
        label = tm.content_text(positional[1]) if len(positional) > 1 else target
        if label.strip() == target.strip():
            return "\\url{" + _latex_escape_url(target) + "}", end
        return (
            "\\href{" + _latex_escape_url(target) + "}{"
            + _inline(label, path, line, context) + "}", end
        )
    raise ConversionError(path, f"Typst call #{name}", line)


def _closing_dollar(text: str, index: int) -> int:
    cursor = index + 1
    while cursor < len(text):
        if text[cursor] == "\\":
            cursor += 2
            continue
        if text[cursor] == "$":
            return cursor
        cursor += 1
    raise ConversionError("<inline>", "unterminated inline mathematics")


def _find_markup_close(text: str, index: int, character: str) -> int:
    cursor = index + 1
    while cursor < len(text):
        if text[cursor] == "\\":
            cursor += 2
            continue
        if text[cursor] == character:
            return cursor
        cursor += 1
    raise ToolError("unterminated Typst markup emphasis")


_TYPST_ESCAPES = {
    "#": ("\\#", True),
    "$": ("\\$", True),
    "_": ("\\_", True),
    "*": ("*", False),
    "<": ("<$>", False),
    ">": ("<$>", False),
    "~": ("\\textasciitilde{}", False),
    "`": ("`", False),
    "\\": ("\\textbackslash{}", False),
    "[": ("[", False),
    "]": ("]", False),
    "@": ("@", False),
    "&": ("\\&", True),
    "%": ("\\%", True),
    "# ": ("\\#", True),
}


def _typst_escape_to_latex(text: str, index: int, path: Path, line: int) -> str:
    character = text[index + 1:index + 2]
    mapping = {
        "#": "\\#",
        "$": "\\$",
        "_": "\\_",
        "*": "*",
        "<": "<",
        ">": ">",
        "~": "\\textasciitilde{}",
        "`": "`",
        "\\": "\\textbackslash{}",
        "[": "[",
        "]": "]",
        "@": "@",
        "&": "\\&",
        "%": "\\%",
        "{": "\\{",
        "}": "\\}",
        " ": " ",
        "-": "-",
    }
    if character in mapping:
        return mapping[character]
    raise ConversionError(path, f"Typst escape \\{character}", line)


def _latex_escape_char(character: str) -> str:
    mapping = {
        "\\": "\\textbackslash{}",
        "#": "\\#",
        "$": "\\$",
        "%": "\\%",
        "&": "\\&",
        "_": "\\_",
        "{": "\\{",
        "}": "\\}",
        "~": "\\textasciitilde{}",
        "^": "\\textasciicircum{}",
        "–": "--",
        "—": "---",
        "’": "'",
        "‘": "`",
        "“": "``",
        "”": "''",
        "…": "\\ldots{}",
        "✓": "\\checkmark",
    }
    return mapping.get(character, character)


def _latex_escape_text(text: str) -> str:
    return "".join(_latex_escape_char(character) for character in text)


def _latex_escape_url(url: str) -> str:
    r"""Return the URL unchanged: ``\url`` treats its argument verbatim."""
    return url


_LATEX_LANGUAGES = {
    "python": "Python",
    "c": "C",
    "cpp": "C++",
    "java": "Java",
    "javascript": None,
    "typescript": None,
    "bash": "bash",
    "sql": "SQL",
    "json": None,
    "yaml": None,
    "xml": "XML",
    "html": "HTML",
    "css": None,
    "latex": "TeX",
    "typst": None,
    "rust": None,
    "go": None,
}


def _latex_language(language: str | None, path: Path, line: int) -> str | None:
    if language is None:
        return None
    key = language.strip().lower()
    # The listings package knows only a subset of languages.  An unknown tag
    # falls back to unhighlighted listing text: the body is preserved and the
    # limitation is documented, unlike a dropped construct.
    return _LATEX_LANGUAGES.get(key)


# ---------------------------------------------------------------------------
# Mathematics: Typst -> LaTeX
# ---------------------------------------------------------------------------


_TYPST_MATH_SYMBOLS = {
    "dot": "\\cdot",
    "times": "\\times",
    "div": "\\div",
    "plus.minus": "\\pm",
    "minus.plus": "\\mp",
    "<=": "\\le",
    ">=": "\\ge",
    "!=": "\\ne",
    "approx": "\\approx",
    "equiv": "\\equiv",
    "infinity": "\\infty",
    "diff": "\\partial",
    "arrow.r": "\\to",
    "arrow.l": "\\leftarrow",
    "arrow.r.double": "\\Rightarrow",
    "arrow.l.double": "\\Leftarrow",
    "forall": "\\forall",
    "exists": "\\exists",
    "in": "\\in",
    "in.not": "\\notin",
    "subset": "\\subset",
    "union": "\\cup",
    "sect": "\\cap",
    "and": "\\wedge",
    "or": "\\vee",
    "not": "\\neg",
    "dots": "\\ldots",
    "dots.c": "\\cdots",
    "quad": "\\quad",
    "wide": "\\qquad",
    "thin": "\\,",
    "med": "\\;",
    "alpha": "\\alpha",
    "beta": "\\beta",
    "gamma": "\\gamma",
    "delta": "\\delta",
    "epsilon": "\\epsilon",
    "epsilon.alt": "\\varepsilon",
    "zeta": "\\zeta",
    "eta": "\\eta",
    "theta": "\\theta",
    "lambda": "\\lambda",
    "mu": "\\mu",
    "nu": "\\nu",
    "xi": "\\xi",
    "pi": "\\pi",
    "rho": "\\rho",
    "sigma": "\\sigma",
    "tau": "\\tau",
    "phi": "\\phi",
    "phi.alt": "\\varphi",
    "chi": "\\chi",
    "psi": "\\psi",
    "omega": "\\omega",
    "Gamma": "\\Gamma",
    "Delta": "\\Delta",
    "Theta": "\\Theta",
    "Lambda": "\\Lambda",
    "Pi": "\\Pi",
    "Sigma": "\\Sigma",
    "Phi": "\\Phi",
    "Psi": "\\Psi",
    "Omega": "\\Omega",
    "sum": "\\sum",
    "product": "\\prod",
    "integral": "\\int",
    "infinity": "\\infty",
}
_TYPST_MATH_FUNCTIONS = {
    "frac": ("\\frac", 2),
    "sqrt": ("\\sqrt", 1),
    "bar": ("\\bar", 1),
    "hat": ("\\hat", 1),
    "tilde": ("\\tilde", 1),
    "vec": ("\\vec", 1),
    "overline": ("\\overline", 1),
    "underline": ("\\underline", 1),
    "bold": ("\\mathbf", 1),
    "italic": ("\\mathit", 1),
}
_TYPST_MATH_TEXT = {"log", "ln", "exp", "max", "min", "sin", "cos", "tan", "det", "lim"}


def typst_math_to_latex(text: str, path: Path, line: int) -> str:
    return _convert_typst_math(text.strip(), path, line).strip()


def _convert_typst_math(text: str, path: Path, line: int) -> str:
    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        if text[index] == '"':
            end = index + 1
            while end < length and text[end] != '"':
                end += 1
            out.append("\\text{" + text[index + 1:end] + "}")
            index = end + 1
            continue
        if text[index] == "(":
            end = tm.read_balanced(text, index)
            out.append("(" + _convert_typst_math(text[index + 1:end - 1], path, line) + ")")
            index = end
            continue
        if text.startswith("<=", index):
            out.append("\\le")
            index += 2
            continue
        if text.startswith(">=", index):
            out.append("\\ge")
            index += 2
            continue
        if text.startswith("!=", index):
            out.append("\\ne")
            index += 2
            continue
        if text[index] in "_^":
            marker = text[index]
            index += 1
            if index < length and text[index] == "(":
                end = tm.read_balanced(text, index)
                argument = _convert_typst_math(text[index + 1:end - 1], path, line)
                index = end
            elif index < length:
                argument = _convert_typst_math(text[index], path, line)
                index += 1
            else:
                raise ConversionError(path, "dangling subscript/superscript in mathematics", line)
            out.append(marker + "{" + argument + "}")
            continue
        match = re.match(r"[A-Za-z]+(?:\.[A-Za-z]+)*", text[index:])
        if match:
            word = match.group(0)
            index += match.end()
            if word in _TYPST_MATH_SYMBOLS:
                out.append(_TYPST_MATH_SYMBOLS[word])
                continue
            if word in _TYPST_MATH_FUNCTIONS:
                command, arity = _TYPST_MATH_FUNCTIONS[word]
                cursor = index
                while cursor < len(text) and text[cursor] in " \t":
                    cursor += 1
                if cursor >= len(text) or text[cursor] != "(":
                    raise ConversionError(
                        path, f"Typst math function {word!r} without arguments", line
                    )
                end = tm.read_balanced(text, cursor)
                parts = tm.split_arguments("(" + text[cursor + 1:end - 1] + ")")
                if len(parts) != arity:
                    raise ConversionError(
                        path, f"Typst math function {word!r} expects {arity} arguments", line
                    )
                rendered = [_convert_typst_math(part.strip(), path, line) for part in parts]
                if arity == 2:
                    out.append(f"{command}{{{rendered[0]}}}{{{rendered[1]}}}")
                else:
                    out.append(f"{command}{{{rendered[0]}}}")
                index = end
                continue
            out.append(word)
            continue
        if text[index] in " \t\n":
            out.append(" ")
            index += 1
            continue
        out.append(text[index])
        index += 1
    return re.sub(r"\s+", " ", "".join(out)).strip()
