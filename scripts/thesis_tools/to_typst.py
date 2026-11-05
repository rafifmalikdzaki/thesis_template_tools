"""LaTeX -> Typst conversion.

The converter reads the authoritative LaTeX project, inventories every object
from the raw sources, and only then renders Typst files that use the published
``template.typ`` helper API (``thesis-figure``, ``thesis-table``, ``listing``,
``equation-row``, ``thesis-bibliography``, ``appendix`` and the administrative
page helpers).

Unsupported input is never skipped: every unknown command, environment, table
column type or listing option raises :class:`~thesis_tools.common.ConversionError`
with the file, line and construct.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import latex_model as lm
from .common import (
    ConversionError,
    ToolError,
    balance_brackets,
    escape_typst_markup,
    line_number,
    parse_metadata_tex,
    read_text,
    render_metadata_json,
    typst_string,
)
from .typst_model import REQUIRED_TEMPLATE_HELPERS

# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class ConversionResult:
    files: dict[str, str] = field(default_factory=dict)
    assets: dict[str, Path] = field(default_factory=dict)
    inventory: dict[str, list] = field(default_factory=dict)

    def summary(self) -> str:
        counts: dict[str, int] = {}
        for items in self.inventory.values():
            for item in items:
                counts[item.kind] = counts.get(item.kind, 0) + 1
        parts = [f"{name}={count}" for name, count in sorted(counts.items())]
        return f"{len(self.files)} files, {len(self.assets)} assets, " + ", ".join(parts)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def convert_latex_to_typst(source: Path, target: Path) -> ConversionResult:
    project = lm.LatexProject.discover(source)
    _validate_target(target)
    template_rel = _template_relative_path(target)
    if project.metadata is None or not project.metadata.is_file():
        raise ToolError(
            f"{project.root}: metadata.tex is missing; the LaTeX starter must expose it"
        )
    metadata = parse_metadata_tex(
        read_text(project.metadata), str(project.metadata)
    )
    result = ConversionResult()
    result.files["metadata.json"] = render_metadata_json(metadata)
    label_kinds = _collect_label_kinds(project)

    main_text = lm.read_text(project.main)
    result.files["main.typ"] = _render_main(project, main_text, template_rel)

    for include in project.includes:
        if include.admin is not None:
            continue  # rendered in main.typ by the administrative-page helper
        text = lm.read_text(include.path)
        result.files[_to_typst_path(include.rel)] = _render_content(
            project, include, template_rel, result, label_kinds
        )
    for include in project.extra_content:
        if include.admin is not None:
            continue
        text = lm.read_text(include.path)
        result.files[_to_typst_path(include.rel)] = _render_content(
            project, include, template_rel, result, label_kinds
        )

    for layout_path in (project.preamble, project.layout):
        if layout_path is not None and layout_path.is_file():
            _collect_layout_assets(project, layout_path, result)
    if "main.typ" not in result.files:
        raise ToolError("conversion produced no main.typ")
    return result


def _collect_label_kinds(project: lm.LatexProject) -> dict[str, str]:
    """Map every label to its object kind, from the raw-source inventory."""
    kinds: dict[str, str] = {}
    for include in project.includes + project.extra_content:
        if include.admin is not None:
            continue
        inventory = lm.scan_inventory(read_text(include.path), include.path)
        for item in inventory.items:
            if item.label:
                kinds[item.label] = item.kind
    return kinds


def _collect_layout_assets(
    project: lm.LatexProject, layout_path: Path, result: ConversionResult
) -> None:
    """Copy assets referenced by the layout/administrative pages (e.g. the logo)."""
    text = lm.read_text(layout_path)
    for match in re.finditer(
        r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}",
        lm.strip_comments(text),
    ):
        reference = match.group(1).strip()
        if not reference or "#" in reference:
            # ``#1`` is a macro parameter in the layout definition, not a file.
            continue
        source = project.find_asset(reference)
        target_rel = "assets/" + source.name
        previous = result.assets.get(target_rel)
        if previous is not None and previous.resolve() != source.resolve():
            raise ToolError(
                f"{layout_path}: two different assets would be written to {target_rel}"
            )
        result.assets[target_rel] = source


def _validate_target(target: Path) -> None:
    target = target.resolve()
    if not target.is_dir():
        raise ToolError(f"target directory does not exist: {target}")
    template = target / "template.typ"
    if not template.is_file():
        template = target / "typst" / "template.typ"
    if not template.is_file():
        raise ToolError(
            f"{target}: template.typ is missing; the target must be a Typst thesis "
            "starter (the converter writes the manuscript, not the layout)"
        )
    text = lm.read_text(template)
    missing = [
        name for name in REQUIRED_TEMPLATE_HELPERS
        if not re.search(r"#let\s+" + re.escape(name) + r"\b", text)
    ]
    if missing:
        raise ToolError(
            f"{template}: missing helper(s) {', '.join(missing)}; "
            "the target does not expose the Typst starter interface"
        )


def _template_relative_path(target: Path) -> str:
    target = target.resolve()
    template = target / "template.typ"
    if not template.is_file():
        template = target / "typst" / "template.typ"
    return template.relative_to(target).as_posix()


def _to_typst_path(rel_tex: str) -> str:
    if rel_tex.endswith(".tex"):
        return rel_tex[:-4] + ".typ"
    return rel_tex + ".typ"


# ---------------------------------------------------------------------------
# Main document
# ---------------------------------------------------------------------------


def _render_main(project: lm.LatexProject, text: str, template_rel: str) -> str:
    blocks = lm.LatexScanner(project.main, text).scan()
    lines: list[str] = [
        "// =====================================================================",
        "//  TEMPLATE TESIS — BERKAS INDUK (Typst)",
        "// =====================================================================",
        "//  Generated from the LaTeX master by scripts/convert_latex_to_typst.py.",
        "//  This master only fixes document order and page-numbering transitions.",
        "//  template.typ → layout, object helpers and administrative pages",
        "//  metadata.json → administrative values",
        "// =====================================================================",
        "",
        f'#import "{_relative_import("", template_rel)}": *',
        "",
        "#show: thesis",
        "",
    ]
    chunk: list[str] = []
    for block in blocks:
        if isinstance(block, lm.Comment):
            rendered_comment = _comment(block.text)
            if rendered_comment is not None:
                chunk.append(rendered_comment)
            continue
        if isinstance(block, lm.Structural):
            rendered = _render_main_structural(project, block)
            if rendered is None:
                continue
            chunk.append(rendered)
            continue
        raise ConversionError(
            project.main,
            f"content {type(block).__name__} in the master file",
            getattr(block, "line", None),
        )
    lines.extend(_flush_main_chunks(chunk))
    return "\n".join(lines).rstrip("\n") + "\n"


def _render_main_structural(project: lm.LatexProject, block: lm.Structural) -> str | None:
    command = block.command
    argument = block.argument
    transitions = {
        "thesisfrontmatter": ['#set page(numbering: "i")', "#counter(page).update(1)"],
        "thesismainmatter": ['#set page(numbering: "1")', "#counter(page).update(1)"],
    }
    if command == "thesiscovermatter":
        # The cover helper already renders without a page number.
        return None
    if command in transitions:
        return "\n".join(transitions[command])
    if command in ("appendix", "thesisappendix"):
        return "#appendix()"
    if command in lm.ADMIN_MACROS:
        return f"#{lm.ADMIN_MACROS[command]}()"
    if command == "pagenumbering":
        if argument in ("roman", "Roman"):
            return '#set page(numbering: "i")'
        if argument in ("arabic", "Arabic"):
            return '#set page(numbering: "1")'
        if argument in ("gobble", None):
            return None
        raise ConversionError(project.main, f"\\pagenumbering{{{argument}}}", block.line)
    if command == "setcounter":
        if argument == "page" and block.extra and block.extra.isdigit():
            return f"#counter(page).update({block.extra})"
        raise ConversionError(
            project.main, f"\\setcounter{{{argument}}}{{{block.extra}}}", block.line
        )
    if command in lm.OUTLINE_COMMANDS:
        return _outline_line(lm.OUTLINE_COMMANDS[command])
    if command in ("clearpage", "newpage", "pagebreak", "documentclass", "addcontentsline",
                   "hypersetup", "graphicspath", "maketitle"):
        return None
    if command == "input":
        if argument in ("preamble", "metadata"):
            return None
        raise ConversionError(project.main, f"\\input{{{argument}}} in the master file", block.line)
    if command == "include":
        relative = _include_content(project, argument, block.line)
        if relative.admin is not None:
            return f"#{relative.admin}-page()"
        return f'#include "{_to_typst_path(relative.rel)}"'
    if command == "begin" or command == "end":
        return None
    raise ConversionError(project.main, f"\\{command}", block.line)


def _include_content(project: lm.LatexProject, argument: str | None, line: int) -> lm.Include:
    if argument is None:
        raise ConversionError(project.main, "\\include without an argument", line)
    rel = argument if argument.endswith(".tex") else argument + ".tex"
    for include in project.includes:
        if include.rel == rel:
            return include
    raise ConversionError(project.main, f"\\include{{{argument}}} (unknown content file)", line)


def _outline_line(kind: str) -> str:
    return {
        "contents": '#outline-page("Daftar Isi", target: heading, depth: 2)',
        "figures": '#outline-page("Daftar Gambar", target: figure.where(kind: image), depth: 1)',
        "tables": '#outline-page("Daftar Tabel", target: figure.where(kind: table), depth: 1)',
        "listings": '#outline-page("Daftar Kode Sumber", target: figure.where(kind: raw), depth: 1)',
    }[kind]


def _flush_main_chunks(chunks: list[str]) -> list[str]:
    lines: list[str] = []
    for chunk in chunks:
        if not chunk.strip():
            continue
        lines.extend(chunk.split("\n"))
        lines.append("")
    return lines


def _relative_import(current_file_rel: str, template_rel: str) -> str:
    current_dir = Path(current_file_rel).parent if current_file_rel else Path(".")
    relative = Path(template_rel)
    import os

    value = os.path.relpath(relative, current_dir if str(current_dir) != "." else ".")
    return value.replace("\\", "/")


# ---------------------------------------------------------------------------
# Content files
# ---------------------------------------------------------------------------


def _render_content(
    project: lm.LatexProject,
    include: lm.Include,
    template_rel: str,
    result: ConversionResult,
    label_kinds: dict[str, str],
) -> str:
    text = lm.read_text(include.path)
    inventory = lm.scan_inventory(text, include.path)
    result.inventory[include.rel] = inventory.items
    scanner = lm.LatexScanner(include.path, text)
    blocks = scanner.scan()

    import_line = f'#import "{_relative_import(_to_typst_path(include.rel), template_rel)}": *'
    rendered: list[str] = []
    consumed: dict[str, list] = {"heading": [], "figure": [], "table": [], "listing": [], "equation": []}
    renderer = _RenderContext(project, include, result, consumed, label_kinds)
    for block in blocks:
        output = renderer.render(block)
        if output is None:
            continue
        rendered.append(output)
    _check_inventory(inventory, consumed, include.path)
    body = "\n\n".join(part for part in rendered if part.strip())
    header = f"// Generated from {include.rel} by scripts/convert_latex_to_typst.py.\n"
    return header + import_line + "\n\n" + body + "\n"


def _check_inventory(inventory: lm.Inventory, consumed: dict[str, list], path: Path) -> None:
    expected = {
        kind: inventory.object_key(kind)
        for kind in ("heading", "figure", "table", "listing", "equation")
    }
    actual = {kind: consumed[kind] for kind in expected}
    for kind in expected:
        if expected[kind] != actual[kind]:
            raise ConversionError(
                path,
                f"internal inventory mismatch for {kind}: parsed {expected[kind]!r} "
                f"but rendered {actual[kind]!r}",
            )


class _RenderContext:
    def __init__(
        self,
        project: lm.LatexProject,
        include: lm.Include,
        result: ConversionResult,
        consumed: dict[str, list],
        label_kinds: dict[str, str],
    ) -> None:
        self.project = project
        self.include = include
        self.result = result
        self.consumed = consumed
        self.label_kinds = label_kinds
        self.path = include.path

    # -- inventory --------------------------------------------------------

    def _consume(self, kind: str, label: str | None, level: int = 0) -> None:
        self.consumed[kind].append((label, level))

    # -- dispatch ---------------------------------------------------------

    def render(self, block) -> str | None:
        if isinstance(block, lm.Comment):
            return _comment(block.text)
        if isinstance(block, lm.Heading):
            return self.heading(block)
        if isinstance(block, lm.Paragraph):
            return balance_brackets(self.inline(block.text, block.line))
        if isinstance(block, lm.Figure):
            return self.figure(block.spec)
        if isinstance(block, lm.Table):
            return self.table(block.spec)
        if isinstance(block, lm.Listing):
            return self.listing(block.spec)
        if isinstance(block, lm.Equation):
            return self.equation(block.spec)
        if isinstance(block, lm.ListBlock):
            return self.list_block(block)
        if isinstance(block, lm.Bibliography):
            return self.bibliography(block)
        if isinstance(block, lm.AlignCenter):
            return self.nested("align(center)", block.blocks)
        if isinstance(block, lm.Quote):
            return self.nested("quote(block: true)", block.blocks)
        if isinstance(block, lm.Tabular):
            return self.tabular(block)
        if isinstance(block, lm.Structural):
            return self.structural(block)
        raise ConversionError(self.path, f"block {type(block).__name__}")

    # -- blocks -----------------------------------------------------------

    def heading(self, block: lm.Heading) -> str:
        self._consume("heading", block.label, block.level)
        anchor = f" <{block.label}>" if block.label else ""
        if block.starred:
            options = [f"level: {block.level}", "numbering: none"]
            if block.outlined:
                options.append("outlined: true")
            return (
                f"#heading({', '.join(options)})["
                f"{balance_brackets(self.inline(block.title, block.line))}]{anchor}"
            )
        marker = "=" * block.level
        title = balance_brackets(self.inline(block.title, block.line))
        return f"{marker} {title}{anchor}"

    def figure(self, spec: lm.FigSpec) -> str:
        self._consume("figure", spec.label)
        source = self.project.find_asset(spec.path)
        target_rel = "assets/" + source.name
        previous = self.result.assets.get(target_rel)
        if previous is not None and previous.resolve() != source.resolve():
            raise ConversionError(
                self.path,
                f"two different assets would be written to {target_rel}",
                spec.line,
            )
        self.result.assets[target_rel] = source
        caption = balance_brackets(self.inline(spec.caption, spec.line))
        return (
            "#thesis-figure(\n"
            f"  {typst_string(target_rel)},\n"
            f"  caption: [{caption}],\n"
            f") <{spec.label}>"
        )

    def table(self, spec: lm.TableSpec) -> str:
        self._consume("table", spec.label)
        width = len(spec.columns)
        columns = ", ".join(column.width or "auto" for column in spec.columns)
        align = ", ".join(column.align for column in spec.columns)
        header_cells = [
            "[" + balance_brackets(self.inline(cell, spec.line)) + "]"
            for cell in spec.header[0]
        ]
        body_cells: list[str] = []
        for row in spec.rows:
            for cell in row:
                body_cells.append("[" + balance_brackets(self.inline(cell, spec.line)) + "]")
        lines = [
            "#thesis-table(",
            f"  caption: [{balance_brackets(self.inline(spec.caption, spec.line))}],",
            f"  label: <{spec.label}>,",
            f"  columns: ({columns}),",
            f"  align: ({align}),",
            "  header: (",
        ]
        lines.extend(f"    {cell}," for cell in header_cells)
        lines.append("  ),")
        if spec.rules:
            lines.append("  rules: (" + ", ".join(str(index) for index in spec.rules) + ",),")
        for index in range(0, len(body_cells), width):
            lines.append("  " + ", ".join(body_cells[index:index + width]) + ",")
        lines.append(")")
        table_text = "\n".join(lines)
        if spec.landscape:
            indented = "\n".join("  " + line for line in table_text.split("\n"))
            return "#landscape[\n" + indented + "\n]"
        return table_text

    def listing(self, spec: lm.ListingSpec) -> str:
        self._consume("listing", spec.label)
        language = _typst_language(spec.language, self.path, spec.line)
        body = _dedent(spec.body)
        fence = "```" + (language or "")
        return (
            f"#listing([{balance_brackets(self.inline(spec.caption, spec.line))}])[\n"
            f"{fence}\n{body}\n```\n"
            f"] <{spec.label}>"
        )

    def equation(self, spec: lm.EquationSpec) -> str:
        self._consume("equation", spec.label)
        math = latex_math_to_typst(spec.body, self.path, spec.line)
        anchor = f" <{spec.label}>" if spec.label else ""
        return f"#equation-row[\n  $ {math} ${anchor}\n]"

    def list_block(self, block: lm.ListBlock) -> str:
        marker = "+" if block.ordered else "-"
        lines: list[str] = []
        for item in block.items:
            rendered = balance_brackets(self.inline(item, block.line))
            parts = rendered.split("\n")
            lines.append(f"{marker} {parts[0]}")
            for continuation in parts[1:]:
                lines.append("  " + continuation)
        return "\n".join(lines)

    def bibliography(self, block: lm.Bibliography) -> str:
        rendered = []
        for nested in block.blocks:
            output = self.render(nested)
            if output is not None and output.strip():
                rendered.append(output)
        body = "\n\n".join(rendered)
        indented = "\n".join("  " + line if line else "" for line in body.split("\n"))
        return "#thesis-bibliography[\n" + indented + "\n]"

    def nested(self, call: str, blocks: list) -> str:
        rendered = []
        for block in blocks:
            output = self.render(block)
            if output is not None and output.strip():
                rendered.append(output)
        body = "\n\n".join(rendered)
        indented = "\n".join("  " + line if line else "" for line in body.split("\n"))
        return f"#{call}[\n{indented}\n]"

    def tabular(self, block: lm.Tabular) -> str:
        columns = ", ".join(column.width or "auto" for column in block.columns)
        cells: list[str] = []
        for row in block.rows:
            for cell in row:
                cells.append("[" + balance_brackets(self.inline(cell, block.line)) + "]")
        inner = ", ".join(cells)
        return f"#grid(\n  columns: ({columns}),\n  {inner},\n)"

    def structural(self, block: lm.Structural) -> str | None:
        command = block.command
        if command == "addcontentsline":
            return None
        if command in ("clearpage", "newpage", "pagebreak"):
            return "#pagebreak()"
        if command in lm.ADMIN_MACROS:
            return f"#{lm.ADMIN_MACROS[command]}()"
        if command in ("appendix", "thesisappendix"):
            return "#appendix()"
        if command in lm.PAGE_TRANSITIONS:
            if command == "thesiscovermatter":
                return None
            if command == "thesisfrontmatter":
                return '#set page(numbering: "i")\n#counter(page).update(1)'
            if command == "thesismainmatter":
                return '#set page(numbering: "1")\n#counter(page).update(1)'
            return "#appendix()"
        if command == "pagenumbering":
            if block.argument in ("roman", "Roman"):
                return '#set page(numbering: "i")'
            if block.argument in ("arabic", "Arabic"):
                return '#set page(numbering: "1")'
            if block.argument in ("gobble", None):
                return None
            raise ConversionError(self.path, f"\\pagenumbering{{{block.argument}}}", block.line)
        if command == "setcounter":
            if block.argument == "page" and block.extra and block.extra.isdigit():
                return f"#counter(page).update({block.extra})"
            raise ConversionError(
                self.path, f"\\setcounter{{{block.argument}}}{{{block.extra}}}", block.line
            )
        if command in lm.OUTLINE_COMMANDS:
            return _outline_line(lm.OUTLINE_COMMANDS[command])
        if command in ("include", "input"):
            raise ConversionError(
                self.path,
                f"\\{command}{{{block.argument}}} inside a content file",
                block.line,
            )
        raise ConversionError(self.path, f"\\{command}", block.line)

    # -- inline -----------------------------------------------------------

    def inline(self, text: str, line: int) -> str:
        return render_inline(text, self.path, line, self)


# ---------------------------------------------------------------------------
# Inline LaTeX -> Typst markup
# ---------------------------------------------------------------------------


_TEXT_WRAPPERS = {
    "textbf": ("*", "*"),
    "textit": ("_", "_"),
    "emph": ("_", "_"),
    "textsl": ("_", "_"),
    "textsc": ("#smallcaps[", "]"),
    "underline": ("#underline[", "]"),
    "textsuperscript": ("#super[", "]"),
    "textsubscript": ("#sub[", "]"),
    "text": ("", ""),
    "textrm": ("", ""),
    "textsf": ("", ""),
    "textnormal": ("", ""),
    "mbox": ("", ""),
}
_SIMPLE_REPLACEMENTS = {
    "checkmark": "✓",
    "ldots": "…",
    "dots": "…",
    "textbackslash": "\\\\",
    "textasciitilde": "~",
    "textasciicircum": "^",
    "textless": "<",
    "textgreater": ">",
    "textbar": "|",
    "textunderscore": "_",
    "copyright": "©",
    "textregistered": "®",
    "texttrademark": "™",
    "LaTeX": "LaTeX",
    "TeX": "TeX",
    "slash": "/",
    "S": "§",
    "P": "¶",
}
_LITERAL_ESCAPES = {
    "%": "%",
    "&": "&",
    "_": "\\_",
    "#": "\\#",
    "$": "\\$",
    "{": "\\{",
    "}": "\\}",
    "<": "\\<",
    ">": "\\>",
    " ": " ",
}
_SPACING = {
    "quad": "#h(2em)",
    "qquad": "#h(4em)",
    ",": "#h(0.17em)",
    ";": "#h(0.28em)",
    ":": "#h(0.22em)",
    "!": "",
    " ": " ",
    "\\": "#linebreak()",
    "medskip": "#v(0.6em)\n",
    "smallskip": "#v(0.3em)\n",
    "bigskip": "#v(1em)\n",
    "noindent": "",
    "indent": "",
    "centering": "",
    "hfill": "#h(1fr)",
    "vfill": "#v(1fr)",
    "newline": "#linebreak()",
    "linebreak": "#linebreak()",
    "par": "\n\n",
}


def render_inline(text: str, path: Path, line: int, context: _RenderContext | None = None) -> str:
    """Convert LaTeX text (a paragraph or a cell) to readable Typst markup."""
    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        character = text[index]
        if character == "%":
            end = text.find("\n", index)
            if end < 0:
                index = length
            else:
                out.append(" ")
                index = end + 1
            continue
        if character == "\\":
            command, after = _read_inline_command(text, index, path, line)
            if command == "texttt":
                argument, after = lm.read_brace_group(text, after)
                raw = argument.replace("\\", "\\\\").replace("`", "\\`")
                out.append("`" + raw + "`")
                index = after
                continue
            if command == "verb":
                delimiter = text[after:after + 1]
                if not delimiter or delimiter.isalnum():
                    raise ConversionError(path, "\\verb without a delimiter", line)
                end = text.find(delimiter, after + 1)
                if end < 0:
                    raise ConversionError(path, "unterminated \\verb", line)
                out.append("`" + text[after + 1:end].replace("`", "\\`") + "`")
                index = end + 1
                continue
            if command in _TEXT_WRAPPERS:
                opening, closing = _TEXT_WRAPPERS[command]
                argument, after = lm.read_brace_group(text, after)
                rendered = render_inline(argument, path, line, context)
                out.append(opening + rendered + closing)
                index = after
                continue
            if command in ("ref", "eqref", "autoref", "pageref"):
                argument, after = lm.read_brace_group(text, after)
                if command == "pageref":
                    raise ConversionError(path, "\\pageref", line)
                label = argument.strip()
                kind = context.label_kinds.get(label) if context is not None else None
                if kind in ("figure", "table", "listing"):
                    _drop_reference_noun(out, kind)
                out.append("@" + label)
                index = after
                continue
            if command in ("label",):
                argument, after = lm.read_brace_group(text, after)
                raise ConversionError(
                    path, f"\\label{{{argument}}} not attached to an object or heading", line
                )
            if command == "url":
                argument, after = lm.read_brace_group(text, after)
                value = argument.strip()
                out.append(f"#link({typst_string(value)})[{value}]")
                index = after
                continue
            if command == "href":
                target, after = lm.read_brace_group(text, after)
                label, after = lm.read_brace_group(text, after)
                out.append(
                    f"#link({typst_string(target.strip())})["
                    f"{render_inline(label, path, line, context)}]"
                )
                index = after
                continue
            if command == "footnote":
                argument, after = lm.read_brace_group(text, after)
                out.append(
                    "#footnote[" + render_inline(argument, path, line, context) + "]"
                )
                index = after
                continue
            if command in ("vspace", "hspace"):
                argument, after = lm.read_brace_group(text, after)
                amount = argument.strip()
                out.append(("#v(" if command == "vspace" else "#h(") + amount + ")")
                index = after
                continue
            if command in ("hspace*", "vspace*"):
                argument, after = lm.read_brace_group(text, after)
                out.append("#h(" + argument.strip() + ")")
                index = after
                continue
            if command in _LITERAL_ESCAPES:
                out.append(_LITERAL_ESCAPES[command])
                after_check = after
                index = after_check
                continue
            if command in _SIMPLE_REPLACEMENTS:
                out.append(_SIMPLE_REPLACEMENTS[command])
                index = after
                continue
            if command in _SPACING:
                out.append(_SPACING[command])
                index = after
                continue
            if command in ("clearpage", "newpage", "pagebreak"):
                out.append("#pagebreak()")
                index = after
                continue
            if command in lm.ADMIN_MACROS:
                out.append(f"#{lm.ADMIN_MACROS[command]}()")
                index = after
                continue
            from .common import COMMAND_TO_KEY

            if command in COMMAND_TO_KEY:
                out.append("#meta." + COMMAND_TO_KEY[command])
                index = after
                continue
            raise ConversionError(path, f"LaTeX command \\{command}", line)
        if character == "$":
            end = _find_closing_dollar(text, index)
            math = text[index + 1:end]
            out.append("$" + latex_math_to_typst(math, path, line) + "$")
            index = end + 1
            continue
        if character == "{":
            end = lm.balanced_span(text, index)
            out.append(render_inline(text[index + 1:end - 1], path, line, context))
            index = end
            continue
        if character == "}":
            raise ConversionError(path, "unbalanced closing brace in text", line)
        if character == "~":
            out.append(" ")
            index += 1
            continue
        if character == "-" and text.startswith("---", index):
            out.append("—")
            index += 3
            continue
        if character == "-" and text.startswith("--", index):
            out.append("–")
            index += 2
            continue
        if character == "`" and text.startswith("``", index):
            out.append("“")
            index += 2
            continue
        if character == "'" and text.startswith("''", index):
            out.append("”")
            index += 2
            continue
        if character == "'" and text.startswith("`", index):
            out.append("‘")
            index += 2
            continue
        if character == "'":
            out.append("’")
            index += 1
            continue
        if character == "\n":
            out.append("\n")
            index += 1
            continue
        out.append(escape_typst_markup(character))
        index += 1
    return protect_line_starts("".join(out))


_REFERENCE_NOUNS = {"figure": "Gambar", "table": "Tabel", "listing": "Kode Sumber"}


def _drop_reference_noun(out: list[str], kind: str) -> None:
    """Drop "Gambar"/"Tabel"/"Kode Sumber" before a reference.

    Typst's ``@ref`` renders the supplement ("Tabel 3.1"), so keeping the
    LaTeX noun would print "Tabel Tabel 3.1".
    """
    text = "".join(out)
    noun = _REFERENCE_NOUNS[kind]
    match = re.search(r"(?:^|(?<=\s))" + re.escape(noun) + r"\s+$", text)
    if match is None:
        return
    text = text[:match.start()] + text[match.end():]
    out.clear()
    out.append(text)


def protect_line_starts(text: str) -> str:
    """Escape markup at line starts that Typst would parse as structure."""
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if re.match(r"^(\+|-|=)\s", line) or line.startswith("="):
            lines[index] = "\\" + line
    return "\n".join(lines)


def _read_inline_command(text: str, index: int, path: Path, line: int) -> tuple[str, int]:
    match = re.match(r"\\([A-Za-z@]+\*?|[^A-Za-z])", text[index:])
    if match is None:
        raise ConversionError(path, f"stray backslash in {text[index:index + 20]!r}", line)
    return match.group(1), index + match.end()


def _find_closing_dollar(text: str, index: int) -> int:
    cursor = index + 1
    while cursor < len(text):
        if text[cursor] == "\\":
            cursor += 2
            continue
        if text[cursor] == "$":
            return cursor
        cursor += 1
    raise ToolError("unbalanced inline mathematics")


# ---------------------------------------------------------------------------
# Mathematics
# ---------------------------------------------------------------------------


_MATH_SYMBOLS = {
    "cdot": "dot",
    "times": "times",
    "div": "div",
    "pm": "plus.minus",
    "mp": "minus.plus",
    "le": "<=",
    "leq": "<=",
    "ge": ">=",
    "geq": ">=",
    "ne": "!=",
    "neq": "!=",
    "approx": "approx",
    "equiv": "equiv",
    "sim": "tilde.op",
    "infty": "infinity",
    "partial": "diff",
    "to": "arrow.r",
    "rightarrow": "arrow.r",
    "leftarrow": "arrow.l",
    "Rightarrow": "arrow.r.double",
    "Leftarrow": "arrow.l.double",
    "forall": "forall",
    "exists": "exists",
    "in": "in",
    "notin": "in.not",
    "subset": "subset",
    "cup": "union",
    "cap": "sect",
    "wedge": "and",
    "vee": "or",
    "neg": "not",
    "equiv": "equiv",
    "ldots": "dots",
    "cdots": "dots.c",
    "dots": "dots",
    "quad": "quad",
    "qquad": "wide",
    "alpha": "alpha",
    "beta": "beta",
    "gamma": "gamma",
    "delta": "delta",
    "epsilon": "epsilon",
    "varepsilon": "epsilon.alt",
    "zeta": "zeta",
    "eta": "eta",
    "theta": "theta",
    "lambda": "lambda",
    "mu": "mu",
    "nu": "nu",
    "xi": "xi",
    "pi": "pi",
    "rho": "rho",
    "sigma": "sigma",
    "tau": "tau",
    "phi": "phi",
    "varphi": "phi.alt",
    "chi": "chi",
    "psi": "psi",
    "omega": "omega",
    "Gamma": "Gamma",
    "Delta": "Delta",
    "Theta": "Theta",
    "Lambda": "Lambda",
    "Pi": "Pi",
    "Sigma": "Sigma",
    "Phi": "Phi",
    "Psi": "Psi",
    "Omega": "Omega",
}
_UNARY_MATH_FUNCTIONS = {
    "sqrt": "sqrt",
    "bar": "bar",
    "hat": "hat",
    "tilde": "tilde",
    "vec": "vec",
    "overline": "overline",
    "underline": "underline",
    "overline": "overline",
}
_MATH_TEXT_FUNCTIONS = {"text", "mathrm", "operatorname", "mbox"}
_MATH_BOLD_FUNCTIONS = {"mathbf", "boldsymbol", "bm"}
_MATH_ITALIC_FUNCTIONS = {"mathit"}
_MATH_FUNCTION_NAMES = {
    "log", "ln", "exp", "max", "min", "sin", "cos", "tan", "cot", "sec",
    "csc", "arcsin", "arccos", "arctan", "det", "lim", "sup", "inf", "arg",
}
_MATH_LITERAL_ESCAPES = {
    "%": "%",
    "&": "&",
    "_": "\\_",
    "#": "\\#",
    "$": "\\$",
    "{": "\\{",
    "}": "\\}",
    "<": "\\<",
    ">": "\\>",
    " ": " ",
}
_MATH_SPACING = {",": "thin", ";": "med", ":": "med", "!": "", " ": " "}


def latex_math_to_typst(text: str, path: Path, line: int) -> str:
    return _convert_math(text, path, line).strip()


def _convert_math(text: str, path: Path, line: int) -> str:
    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        character = text[index]
        if character == "\\":
            match = re.match(r"\\([A-Za-z]+|[^A-Za-z])", text[index:])
            if match is None:
                raise ConversionError(path, f"stray backslash in mathematics", line)
            command = match.group(1)
            index += match.end()
            if command in ("frac", "dfrac", "tfrac"):
                numerator, index = lm.read_brace_group(text, index)
                denominator, index = lm.read_brace_group(text, index)
                out.append(
                    f"frac({_convert_math(numerator, path, line)}, "
                    f"{_convert_math(denominator, path, line)})"
                    + _math_separator(text, index)
                )
                continue
            if command in _UNARY_MATH_FUNCTIONS:
                argument, index = lm.read_brace_group(text, index)
                out.append(
                    f"{_UNARY_MATH_FUNCTIONS[command]}({_convert_math(argument, path, line)})"
                    + _math_separator(text, index)
                )
                continue
            if command in _MATH_TEXT_FUNCTIONS:
                argument, index = lm.read_brace_group(text, index)
                out.append('"' + _math_quote(argument) + '"')
                continue
            if command in _MATH_BOLD_FUNCTIONS:
                argument, index = lm.read_brace_group(text, index)
                out.append(f"bold({_convert_math(argument, path, line)})")
                continue
            if command in _MATH_ITALIC_FUNCTIONS:
                argument, index = lm.read_brace_group(text, index)
                out.append(f"italic({_convert_math(argument, path, line)})")
                continue
            if command in ("left", "right"):
                continue
            if command in ("sum", "prod", "int", "iint", "oint"):
                out.append(
                    {"sum": "sum", "prod": "product", "int": "integral",
                     "iint": "integral.double", "oint": "integral.cont"}[command]
                    + _math_separator(text, index)
                )
                continue
            if command in _MATH_SYMBOLS:
                out.append(_MATH_SYMBOLS[command] + _math_separator(text, index))
                continue
            if command in _MATH_SPACING:
                out.append(_MATH_SPACING[command])
                continue
            raise ConversionError(path, f"math command \\{command}", line)
        if character == "{":
            end = lm.balanced_span(text, index)
            out.append(_convert_math(text[index + 1:end - 1], path, line))
            index = end
            continue
        if character in "_^":
            marker = character
            index += 1
            while index < length and text[index] in " \t":
                index += 1
            if index < length and text[index] == "{":
                end = lm.balanced_span(text, index)
                argument = _convert_math(text[index + 1:end - 1], path, line)
                index = end
            elif index < length:
                argument = _convert_math(text[index], path, line)
                index += 1
            else:
                raise ConversionError(path, "dangling subscript/superscript", line)
            if re.fullmatch(r"[A-Za-z0-9]+", argument) or re.fullmatch(r'"[^"]*"', argument):
                out.append(marker + argument)
            else:
                out.append(marker + "(" + argument + ")")
            continue
        if character.isalpha():
            end = index
            while end < length and text[end].isalpha():
                end += 1
            word = text[index:end]
            index = end
            if len(word) == 1 or word in _MATH_FUNCTION_NAMES:
                out.append(word)
            else:
                out.append('"' + word + '"')
            continue
        if character in " \t\n":
            out.append(" ")
            index += 1
            continue
        out.append(character)
        index += 1
    result = re.sub(r"\s+", " ", "".join(out)).strip()
    return result


def _math_separator(source: str, index: int) -> str:
    """A space when the next source character would merge tokens."""
    if index < len(source) and (source[index].isalnum() or source[index] == "\\"):
        return " "
    return ""


def _math_quote(value: str) -> str:
    return value.replace('"', "'")


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------


_KNOWN_LISTING_LANGUAGES = {
    "python": "python",
    "py": "python",
    "c": "c",
    "c++": "cpp",
    "cpp": "cpp",
    "java": "java",
    "javascript": "javascript",
    "js": "javascript",
    "typescript": "typescript",
    "bash": "bash",
    "sh": "bash",
    "sql": "sql",
    "json": "json",
    "yaml": "yaml",
    "xml": "xml",
    "html": "html",
    "css": "css",
    "latex": "latex",
    "tex": "latex",
    "typst": "typst",
    "rust": "rust",
    "go": "go",
    "text": None,
    "": None,
}


def _typst_language(language: str | None, path: Path, line: int) -> str | None:
    if language is None:
        return None
    key = language.strip().lower()
    if key not in _KNOWN_LISTING_LANGUAGES:
        raise ConversionError(path, f"lstlisting language {language!r}", line)
    return _KNOWN_LISTING_LANGUAGES[key]


def _dedent(body: str) -> str:
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    leading = [len(line) - len(line.lstrip(" ")) for line in lines if line.strip()]
    cut = min(leading) if leading else 0
    return "\n".join(line[cut:].rstrip() for line in lines)


def _comment(text: str) -> str | None:
    """Render a LaTeX comment as a Typst comment.

    Editor directives such as ``% !TEX program = pdflatex`` are build support
    for the LaTeX repository and are not carried into the Typst project.
    """
    body = text.strip()
    if body.startswith("%"):
        body = body[1:]
    body = body.strip()
    if body.startswith("!TEX") or body.startswith("!tex"):
        return None
    return "// " + body if body else "//"
