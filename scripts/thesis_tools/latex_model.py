"""Discovery and parsing of the LaTeX thesis starter.

The module offers two independent views of the same sources:

``LatexProject.discover``
    repository layout: master file, metadata, layout files, include order,
    content files and the asset search path;
``scan_inventory``
    a regex-based raw-source inventory of headings, figures, tables, listings,
    equations, labels and references, computed *before* any rendering;
``LatexScanner``
    a block scanner that the LaTeX -> Typst renderer walks.  It re-parses the
    constructs and fails with file, line and construct on anything unknown.

The renderer consumes the inventory after scanning, so a construct that the
raw scan sees but the renderer does not emit is reported instead of dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .common import (
    ConversionError,
    ToolError,
    balanced_span,
    line_number,
    read_text,
    split_top_level,
)

CONTENT_DIRS: tuple[str, ...] = ("frontmatter", "chapters", "backmatter", "lampiran")
ADMIN_MACROS: dict[str, str] = {
    "thesiscoverpage": "cover",
    "thesisapprovalpage": "approval",
    "thesisdeclarationpage": "declaration",
}
PAGE_TRANSITIONS: dict[str, str] = {
    "thesiscovermatter": "cover",
    "thesisfrontmatter": "frontmatter",
    "thesismainmatter": "mainmatter",
    "thesisappendix": "appendix",
}
OUTLINE_COMMANDS: dict[str, str] = {
    "tableofcontents": "contents",
    "listoffigures": "figures",
    "listoftables": "tables",
    "lstlistoflistings": "listings",
}
STRUCTURAL_COMMANDS = (
    "pagenumbering",
    "setcounter",
    "tableofcontents",
    "listoffigures",
    "listoftables",
    "lstlistoflistings",
    "appendix",
    "include",
    "input",
    "clearpage",
    "newpage",
    "pagebreak",
    "thesisfrontmatter",
    "thesismainmatter",
    "thesisappendix",
    "thesiscovermatter",
    "thesiscoverpage",
    "thesisapprovalpage",
    "thesisdeclarationpage",
    "addcontentsline",
    "documentclass",
    "begin",
    "end",
    "hypersetup",
    "graphicspath",
    "maketitle",
)


# ---------------------------------------------------------------------------
# Document model
# ---------------------------------------------------------------------------


@dataclass
class Column:
    align: str  # left | center | right
    width: str | None  # e.g. "5cm"; None means automatic


@dataclass
class FigSpec:
    path: str
    caption: str
    label: str | None
    line: int


@dataclass
class TableSpec:
    caption: str
    label: str | None
    columns: list[Column]
    header: list[list[str]]
    rows: list[list[str]]
    rules: list[int]
    landscape: bool
    line: int
    payload: list[str] = field(default_factory=list)


@dataclass
class ListingSpec:
    caption: str
    label: str | None
    language: str | None
    body: str
    line: int


@dataclass
class EquationSpec:
    body: str
    label: str | None
    starred: bool
    line: int


# Block tokens produced by :class:`LatexScanner`.
@dataclass
class Heading:
    level: int
    title: str
    starred: bool
    label: str | None
    outlined: bool
    line: int


@dataclass
class Figure:
    spec: FigSpec


@dataclass
class Table:
    spec: TableSpec


@dataclass
class Listing:
    spec: ListingSpec


@dataclass
class Equation:
    spec: EquationSpec


@dataclass
class ListBlock:
    ordered: bool
    items: list[str]
    line: int


@dataclass
class Bibliography:
    blocks: list
    line: int


@dataclass
class AlignCenter:
    blocks: list


@dataclass
class Quote:
    blocks: list


@dataclass
class Tabular:
    columns: list[Column]
    rows: list[list[str]]
    line: int


@dataclass
class Paragraph:
    text: str
    line: int


@dataclass
class Comment:
    text: str


@dataclass
class Structural:
    command: str
    argument: str | None
    line: int
    extra: str | None = None


# ---------------------------------------------------------------------------
# Repository discovery
# ---------------------------------------------------------------------------


@dataclass
class Include:
    rel: str  # posix path with .tex, relative to the repository root
    path: Path
    appendix: bool
    admin: str | None = None


@dataclass
class LatexProject:
    root: Path
    main: Path
    metadata: Path | None
    preamble: Path | None
    layout: Path | None
    includes: list[Include]
    extra_content: list[Include]
    assets_dir: Path | None
    graphicspaths: list[str]

    @property
    def content_includes(self) -> list[Include]:
        return self.includes

    @classmethod
    def discover(cls, root: Path) -> "LatexProject":
        root = root.resolve()
        if not root.is_dir():
            raise ToolError(f"LaTeX project directory not found: {root}")
        main = root / "main.tex"
        if not main.is_file():
            raise ToolError(f"{root}: main.tex is missing; not a LaTeX thesis starter")
        metadata = _first_existing(root / "metadata.tex", root / "latex" / "metadata.tex")
        preamble = _first_existing(root / "preamble.tex", root / "latex" / "preamble.tex")
        layout = _first_existing(
            root / "thesis-layout.sty", root / "latex" / "thesis-layout.sty"
        )
        main_text = read_text(main)
        includes, extra_content = _discover_content(root, main_text)
        graphicspaths: list[str] = []
        for candidate in (preamble, layout):
            if candidate is not None and candidate.is_file():
                graphicspaths.extend(parse_graphicspaths(read_text(candidate)))
        assets_dir = root / "assets" if (root / "assets").is_dir() else None
        return cls(
            root=root,
            main=main,
            metadata=metadata,
            preamble=preamble,
            layout=layout,
            includes=includes,
            extra_content=extra_content,
            assets_dir=assets_dir,
            graphicspaths=graphicspaths,
        )

    def find_asset(self, reference: str) -> Path:
        """Resolve an ``\\includegraphics`` reference to a file in the project."""
        reference = reference.strip()
        candidates: list[Path] = []
        candidates.append(self.root / reference)
        if not Path(reference).suffix:
            candidates.extend(
                (self.root / reference).with_suffix(ext) for ext in (".pdf", ".png", ".jpg", ".jpeg")
            )
        for graphicspath in self.graphicspaths:
            base = self.root / graphicspath
            candidates.append(base / reference)
            if not Path(reference).suffix:
                candidates.extend(
                    (base / reference).with_suffix(ext)
                    for ext in (".pdf", ".png", ".jpg", ".jpeg")
                )
        if self.assets_dir is not None:
            base = self.assets_dir
            candidates.append(base / reference)
            candidates.append(base / Path(reference).name)
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise ToolError(
            f"{self.root}: cannot resolve figure asset {reference!r}; "
            "checked the project root, \\graphicspath entries and assets/"
        )


def _first_existing(*paths: Path) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


def _discover_content(root: Path, main_text: str) -> tuple[list[Include], list[Include]]:
    body = strip_comments(main_text)
    start = body.find(r"\begin{document}")
    if start >= 0:
        body = body[start + len(r"\begin{document}"):]
    includes: list[Include] = []
    seen: set[Path] = set()
    appendix = False
    layout_names = {"preamble", "metadata"}
    for match in re.finditer(r"\\(include|input)\s*\{([^}]+)\}", body):
        name = match.group(2).strip()
        if name in layout_names or name.endswith(".sty"):
            continue
        rel = name if name.endswith(".tex") else name + ".tex"
        path = (root / rel).resolve()
        if not path.is_file():
            raise ToolError(f"{root}: master file includes {name!r}, which does not exist")
        if path in seen:
            continue
        seen.add(path)
        admin = _admin_stub(path)
        includes.append(
            Include(rel=rel, path=path, appendix=appendix or rel.startswith("lampiran/"), admin=admin)
        )
    # Track appendix transitions in document order: a second pass over the body.
    position = 0
    flags: list[bool] = []
    for match in re.finditer(r"\\(include|input)\s*\{([^}]+)\}", body):
        name = match.group(2).strip()
        if name in layout_names or name.endswith(".sty"):
            continue
        before = body[position:match.start()]
        if re.search(r"\\(appendix|thesisappendix)\b", before):
            appendix = True
        position = match.end()
        flags.append(appendix)
    for index, flag in enumerate(flags):
        if index < len(includes):
            includes[index].appendix = includes[index].appendix or flag

    extra: list[Include] = []
    for directory in CONTENT_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.tex")):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            rel = resolved.relative_to(root).as_posix()
            extra.append(
                Include(rel=rel, path=resolved, appendix=rel.startswith("lampiran/"), admin=_admin_stub(resolved))
            )
    return includes, extra


def _admin_stub(path: Path) -> str | None:
    try:
        text = strip_comments(read_text(path)).strip()
    except ToolError:
        return None
    compact = re.sub(r"\s+", "", text)
    for macro, name in ADMIN_MACROS.items():
        if compact == "\\" + macro:
            return name
    return None


def parse_graphicspaths(text: str) -> list[str]:
    paths: list[str] = []
    for match in re.finditer(r"\\graphicspath\s*\{", text):
        end = balanced_span(text, match.end() - 1)
        inner = text[match.end():end - 1]
        for group in re.finditer(r"\{([^}]*)\}", inner):
            value = group.group(1).strip()
            if value:
                paths.append(value)
    return paths


# ---------------------------------------------------------------------------
# Low-level LaTeX helpers
# ---------------------------------------------------------------------------


def strip_comments(text: str) -> str:
    """Remove LaTeX comments, preserving line structure and escaped percent."""
    out: list[str] = []
    for line in text.split("\n"):
        index = 0
        cut = len(line)
        while index < len(line):
            if line[index] == "%" and (index == 0 or line[index - 1] != "\\"):
                cut = index
                break
            index += 1
        out.append(line[:cut])
    return "\n".join(out)


def command_at(text: str, index: int) -> tuple[str, int] | None:
    """Return (command, end) for a LaTeX command at ``index``."""
    match = re.match(r"\\([A-Za-z@]+)(\*?)", text[index:])
    if not match:
        return None
    return match.group(1) + match.group(2), index + match.end()


def read_brace_group(text: str, index: int) -> tuple[str, int]:
    """Read a ``{...}`` argument starting at ``index`` (skipping whitespace)."""
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    if index >= len(text) or text[index] != "{":
        raise ToolError(f"expected a brace argument at offset {index}")
    end = balanced_span(text, index)
    return text[index + 1:end - 1], end


def read_optional_group(text: str, index: int) -> tuple[str | None, int]:
    """Read an optional ``[...]`` argument if present."""
    while index < len(text) and text[index] in " \t":
        index += 1
    if index < len(text) and text[index] == "[":
        depth = 0
        cursor = index
        while cursor < len(text):
            if text[cursor] == "[":
                depth += 1
            elif text[cursor] == "]":
                depth -= 1
                if depth == 0:
                    return text[index + 1:cursor], cursor + 1
            cursor += 1
        raise ToolError("unbalanced optional argument")
    return None, index


def find_environment_bounds(text: str, start: int, name: str) -> tuple[int, int]:
    """Return (inner_start, inner_end) for the environment beginning at ``start``."""
    begin = re.compile(r"\\begin\s*\{" + re.escape(name) + r"\}")
    end = re.compile(r"\\end\s*\{" + re.escape(name) + r"\}")
    match = begin.match(text, start)
    if match is None:
        raise ToolError(f"internal error: no \\begin{{{name}}} at offset {start}")
    inner_start = match.end()
    nested = 1
    cursor = inner_start
    while cursor <= len(text):
        end_match = end.search(text, cursor)
        begin_match = begin.search(text, cursor)
        if end_match is None:
            raise ConversionError("<unknown>", f"unterminated {name} environment")
        if begin_match is not None and begin_match.start() < end_match.start():
            nested += 1
            cursor = begin_match.end()
            continue
        nested -= 1
        if nested == 0:
            return inner_start, end_match.start()
        cursor = end_match.end()
    raise ConversionError("<unknown>", f"unterminated {name} environment")


# ---------------------------------------------------------------------------
# Construct parsers
# ---------------------------------------------------------------------------


def parse_caption_and_label(text: str) -> tuple[str, str | None]:
    caption = ""
    label = None
    match = re.search(r"\\caption\s*(?:\[[^\]]*\]\s*)?\{", text)
    if match:
        end = balanced_span(text, match.end() - 1)
        caption = text[match.end():end - 1].strip()
    label_match = re.search(r"\\label\s*\{([^}]+)\}", text)
    if label_match:
        label = label_match.group(1).strip()
    return caption, label


def _remove_span(text: str, start: int, end: int) -> str:
    return text[:start] + " " + text[end:]


def _consume_macro(text: str, name: str, count: int, cursor: int) -> tuple[list[str], int]:
    """Consume ``\\name`` followed by ``count`` brace arguments starting at cursor."""
    match = re.match(r"\\" + re.escape(name) + r"\*?\s*", text[cursor:])
    if not match:
        raise ToolError(f"internal error: expected \\{name} at offset {cursor}")
    index = cursor + match.end()
    arguments: list[str] = []
    for _ in range(count):
        argument, index = read_brace_group(text, index)
        arguments.append(argument)
    return arguments, index


def parse_figure(inner: str, path: Path, line: int) -> FigSpec:
    text = strip_comments(inner)
    graphics = list(
        re.finditer(r"\\includegraphics\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}", text)
    )
    if len(graphics) != 1:
        raise ConversionError(path, "figure without exactly one \\includegraphics", line)
    options = (graphics[0].group(1) or "").strip()
    if options:
        raise ConversionError(
            path,
            f"\\includegraphics options [{options}] (width/height belong to the layout interface)",
            line,
        )
    asset = graphics[0].group(2).strip()
    if not asset:
        raise ConversionError(path, "figure with an empty \\includegraphics path", line)

    remainder = text
    # Remove the parts the figure interface owns.
    for name, count in (("centering", 0), ("thesisfigure", 1), ("caption", 1), ("label", 1)):
        pattern = re.compile(r"\\" + name + r"\b\s*")
        for match in reversed(list(pattern.finditer(remainder))):
            cursor = match.end()
            end = cursor
            for _ in range(count):
                _, end = read_brace_group(remainder, end)
            remainder = _remove_span(remainder, match.start(), end)
    # Remove the includegraphics macro itself.
    match = re.search(r"\\includegraphics\b", remainder)
    if match:
        end = match.end()
        _, end = read_optional_group(remainder, end)
        _, end = read_brace_group(remainder, end)
        remainder = _remove_span(remainder, match.start(), end)
    leftover = re.sub(r"[\s{}]", "", remainder)
    if leftover:
        raise ConversionError(path, f"figure content {leftover[:60]!r} is not supported", line)
    caption, label = parse_caption_and_label(text)
    if label is None:
        raise ConversionError(path, "figure without \\label would be silently unnumbered", line)
    if not caption.strip():
        raise ConversionError(path, f"figure \\label{{{label}}} has no caption", line)
    return FigSpec(path=asset, caption=caption, label=label, line=line)


def parse_columns(spec: str, path: Path, line: int) -> list[Column]:
    cleaned = spec
    # Column modifiers with brace arguments (@{}, !{}, >{}, <{}).
    while True:
        match = re.search(r"[@!><]\{", cleaned)
        if match is None:
            break
        end = balanced_span(cleaned, match.end() - 1)
        cleaned = _remove_span(cleaned, match.start(), end)
    columns: list[Column] = []
    index = 0
    while index < len(cleaned):
        character = cleaned[index]
        if character in " \t\r\n|":
            index += 1
            continue
        if character in "lcr":
            align = {"l": "left", "c": "center", "r": "right"}[character]
            columns.append(Column(align=align, width=None))
            index += 1
            continue
        if character in "pmb":
            cursor = index + 1
            while cursor < len(cleaned) and cleaned[cursor] in " \t":
                cursor += 1
            if cursor >= len(cleaned) or cleaned[cursor] != "{":
                raise ConversionError(path, f"malformed column specification {spec!r}", line)
            end = balanced_span(cleaned, cursor)
            width = parse_width(cleaned[cursor + 1:end - 1], path, line)
            columns.append(Column(align="left", width=width))
            index = end
            continue
        raise ConversionError(
            path, f"column specification token {character!r} in {spec!r}", line
        )
    if not columns:
        raise ConversionError(path, f"empty column specification {spec!r}", line)
    return columns


_WIDTH_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(cm|mm|in|pt)\s*$")


def parse_width(value: str, path: Path, line: int) -> str:
    match = _WIDTH_RE.match(value)
    if not match:
        raise ConversionError(path, f"column width {value!r}", line)
    amount, unit = float(match.group(1)), match.group(2)
    if unit == "mm":
        amount /= 10.0
    elif unit == "in":
        amount *= 2.54
    elif unit == "pt":
        amount /= 28.3465
    text = f"{amount:.3f}".rstrip("0").rstrip(".")
    return text + "cm"


NUMERIC_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])[0-9X]+(?:[.,][0-9X]+)*(?![A-Za-z0-9])")


def _strip_caption_label(fragment: str) -> str:
    r"""Remove \caption and \label macros (and their arguments) from a fragment."""
    while True:
        match = re.search(r"\\(caption|label)\b\s*", fragment)
        if match is None:
            return fragment
        cursor = match.end()
        if match.group(1) == "caption":
            _, cursor = read_optional_group(fragment, cursor)
        _, cursor = read_brace_group(fragment, cursor)
        fragment = _remove_span(fragment, match.start(), cursor)


def _strip_table_frame(fragment: str) -> str:
    for token in (
        r"\toprule",
        r"\midrule",
        r"\bottomrule",
        r"\endfirsthead",
        r"\endhead",
        r"\endfoot",
        r"\endlastfoot",
        r"\end{longtable}",
        r"\hline",
    ):
        fragment = fragment.replace(token, " ")
    return fragment


def _split_rows(fragment: str) -> list[str]:
    rows = split_top_level(fragment, "\\\\")
    cleaned: list[str] = []
    for row in rows:
        # ``\\[2.5cm]`` row spacing is an optional argument after the row
        # separator; strip it only when it really is a dimension.
        row = re.sub(r"^\s*\[\s*[-+0-9.]+\s*(?:cm|mm|in|pt|em|ex|pc)\s*\]", "", row)
        if row.strip():
            cleaned.append(row.strip())
    return cleaned


def _split_cells(row: str) -> list[str]:
    return [cell.strip() for cell in split_top_level(row, "&")]


def _strip_multicolumn(row: str) -> str:
    while True:
        match = re.search(r"\\multicolumn\s*\{", row)
        if not match:
            return row
        _, end = read_brace_group(row, match.end() - 1)
        _, end = read_brace_group(row, end)
        _, end = read_brace_group(row, end)
        row = _remove_span(row, match.start(), end)


def parse_table(inner: str, path: Path, line: int) -> TableSpec:
    text = strip_comments(inner)
    landscape = False
    if r"\begin{landscape}" in text:
        landscape = True
        text = text.replace(r"\begin{landscape}", " ").replace(r"\end{landscape}", " ")
    begin = re.search(r"\\begin\s*\{longtable\}\s*\{", text)
    if begin is None:
        raise ConversionError(path, "thesistable without a longtable", line)
    colspec_end = balanced_span(text, begin.end() - 1)
    colspec = text[begin.end():colspec_end - 1]
    columns = parse_columns(colspec, path, line)
    tail = text[colspec_end:]
    if r"\endfirsthead" not in tail:
        raise ConversionError(path, "longtable without \\endfirsthead header block", line)
    head_end = tail.index(r"\endfirsthead")
    head_block = tail[:head_end]
    rest = tail[head_end + len(r"\endfirsthead"):]
    if r"\endhead" not in rest:
        raise ConversionError(path, "longtable without \\endhead header block", line)
    head2_end = rest.index(r"\endhead")
    repeat_block = rest[:head2_end]
    after_head = rest[head2_end + len(r"\endhead"):]
    if r"\endlastfoot" in after_head:
        body_block = after_head[after_head.index(r"\endlastfoot") + len(r"\endlastfoot"):]
    else:
        body_block = after_head
        body_block = re.sub(r"\\endfoot.*?\\endlastfoot", " ", body_block, flags=re.DOTALL)
    body_block = body_block[: body_block.find(r"\end{longtable}")] if r"\end{longtable}" in body_block else body_block

    caption, label = parse_caption_and_label(head_block)
    if label is None:
        raise ConversionError(path, "table without \\label would be silently unnumbered", line)
    if not caption.strip():
        raise ConversionError(path, f"table \\label{{{label}}} has no caption", line)

    header_rows = []
    for row in _split_rows(_strip_table_frame(_strip_caption_label(head_block))):
        row = _strip_multicolumn(row)
        if row.strip():
            header_rows.append(_split_cells(row))
    repeat_rows = []
    for row in _split_rows(_strip_table_frame(_strip_caption_label(repeat_block))):
        row = _strip_multicolumn(row)
        if row.strip():
            repeat_rows.append(_split_cells(row))
    if not header_rows:
        raise ConversionError(path, f"table \\label{{{label}}} has no header row", line)
    if repeat_rows and repeat_rows != header_rows:
        raise ConversionError(
            path,
            f"table \\label{{{label}}} repeated header differs from the first header",
            line,
        )

    rows: list[list[str]] = []
    rules: list[int] = []
    for fragment in _split_rows(body_block):
        if not fragment.strip():
            continue
        has_midrule = re.search(r"\\midrule\b", fragment) is not None
        fragment = _strip_table_frame(_strip_multicolumn(fragment))
        if not fragment.strip():
            continue
        if has_midrule:
            rules.append(len(rows))
        rows.append(_split_cells(fragment))

    for row in header_rows + rows:
        if len(row) != len(columns):
            raise ConversionError(
                path,
                f"table \\label{{{label}}} row has {len(row)} cells for "
                f"{len(columns)} columns: {row!r}",
                line,
            )
    payload: list[str] = []
    for row in rows:
        for cell in row:
            payload.extend(NUMERIC_TOKEN_RE.findall(plain_latex_text(cell)))
    return TableSpec(
        caption=caption,
        label=label,
        columns=columns,
        header=header_rows,
        rows=rows,
        rules=rules,
        landscape=landscape,
        line=line,
        payload=payload,
    )


def parse_listing(block: str, options: str, path: Path, line: int) -> ListingSpec:
    caption = ""
    label = None
    language: str | None = None
    for option in split_top_level(options, ","):
        option = option.strip()
        if not option:
            continue
        if "=" not in option:
            raise ConversionError(path, f"listing option {option!r}", line)
        key, value = option.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith("{") and value.endswith("}"):
            value = value[1:-1]
        if key == "language":
            language = value.strip() or None
        elif key == "caption":
            caption = value
        elif key == "label":
            label = value.strip()
        else:
            raise ConversionError(path, f"lstlisting option {key!r}", line)
    if label is None:
        raise ConversionError(path, "lstlisting without label would be silently unnumbered", line)
    if not caption.strip():
        raise ConversionError(path, f"listing \\label{{{label}}} has no caption", line)
    return ListingSpec(
        caption=caption, label=label, language=language, body=block, line=line
    )


def parse_equation(inner: str, starred: bool, path: Path, line: int) -> EquationSpec:
    text = strip_comments(inner).strip()
    label_match = re.search(r"\\label\s*\{([^}]+)\}", text)
    if label_match:
        label = label_match.group(1).strip()
        text = _remove_span(text, label_match.start(), label_match.end()).strip()
    else:
        label = None
    if not text:
        raise ConversionError(path, "empty equation", line)
    if starred and label is not None:
        raise ConversionError(path, "\\label on an unnumbered equation* environment", line)
    return EquationSpec(body=text, label=label, starred=starred, line=line)


def parse_tabular(inner: str, path: Path, line: int) -> Tabular:
    begin = re.search(r"\\begin\s*\{tabular\}\s*\{", inner)
    if begin is None:
        raise ConversionError(path, "tabular without a column specification", line)
    end = balanced_span(inner, begin.end() - 1)
    columns = parse_columns(inner[begin.end():end - 1], path, line)
    body = inner[end:]
    if r"\end{tabular}" in body:
        body = body[:body.index(r"\end{tabular}")]
    rows = [cells for cells in (_split_cells(row) for row in _split_rows(strip_comments(body))) if any(c.strip() for c in cells)]
    for row in rows:
        if len(row) > len(columns):
            raise ConversionError(path, "tabular row is wider than its column specification", line)
    return Tabular(columns=columns, rows=rows, line=line)


# ---------------------------------------------------------------------------
# Plain-text reduction (used for payloads and comparisons)
# ---------------------------------------------------------------------------


def plain_latex_text(text: str) -> str:
    text = strip_comments(text)
    text = re.sub(r"\\(?:textbf|textit|emph|texttt|text|textrm|textsf|underline|textsc)\s*\{", "{", text)
    text = re.sub(r"\\[A-Za-z@]+\*?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    text = text.replace("~", " ")
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Block scanner used by the renderer
# ---------------------------------------------------------------------------


ENVIRONMENTS = {
    "figure": "figure",
    "thesistable": "thesistable",
    "lstlisting": "listing",
    "equation": "equation",
    "equation*": "equation",
    "enumerate": "enumerate",
    "itemize": "itemize",
    "thesisbibliography": "bibliography",
    "center": "center",
    "quote": "quote",
    "tabular": "tabular",
}


class LatexScanner:
    """Split a LaTeX content file into block tokens in document order."""

    def __init__(self, path: Path, text: str) -> None:
        self.path = path
        self.text = text

    def scan(self) -> list:
        blocks: list = []
        index = 0
        length = len(self.text)
        while index < length:
            index = self._skip_space(index)
            if index >= length:
                break
            if self.text[index] == "%":
                end = self.text.find("\n", index)
                end = length if end < 0 else end
                blocks.append(Comment(self.text[index:end]))
                index = end
                continue
            begin = re.match(r"\\begin\s*\{([^{}]+)\}", self.text[index:])
            if begin is not None and begin.group(1) in ENVIRONMENTS:
                block, index = self._parse_environment(index, begin.group(1))
                blocks.append(block)
                continue
            if begin is not None and begin.group(1) != "document":
                raise ConversionError(
                    self.path,
                    f"environment {begin.group(1)}",
                    line_number(self.text, index),
                )
            heading = re.match(r"\\(chapter|section|subsection)(\*?)\s*\{", self.text[index:])
            if heading is not None:
                block, index = self._parse_heading(index, heading)
                blocks.append(block)
                continue
            command = re.match(r"\\([A-Za-z@]+)\*?", self.text[index:])
            if command is not None and command.group(1) in STRUCTURAL_COMMANDS:
                if command.group(1) in ("begin", "end"):
                    # \begin{document} / \end{document} and similar wrappers.
                    _, end = read_brace_group(self.text, index + len(command.group(0)))
                    blocks.append(Structural(command.group(1), None, line_number(self.text, index)))
                    index = end
                    continue
                block, index = self._parse_structural(index, command)
                blocks.append(block)
                continue
            block, index = self._parse_paragraph(index)
            blocks.append(block)
        return blocks

    # -- helpers ----------------------------------------------------------

    def _skip_space(self, index: int) -> int:
        length = len(self.text)
        while index < length and self.text[index] in " \t\r\n":
            index += 1
        return index

    def _stop_at_block(self, index: int) -> bool:
        """True when a new block construct starts at ``index`` (line start)."""
        rest = self.text[index:]
        if re.match(r"\\begin\s*\{", rest):
            return True
        if re.match(r"\\(chapter|section|subsection)(\*?)\s*\{", rest):
            return True
        command = re.match(r"\\([A-Za-z@]+)\*?", rest)
        if command is not None and command.group(1) in STRUCTURAL_COMMANDS:
            return True
        return rest.startswith("%")

    def _parse_paragraph(self, index: int) -> tuple[Paragraph, int]:
        start = index
        lines: list[str] = []
        length = len(self.text)
        while index < length:
            end = self.text.find("\n", index)
            end = length if end < 0 else end
            line = self.text[index:end]
            stripped = line.strip()
            if not stripped:
                index = end + 1
                break
            if lines and self._stop_at_block(index):
                break
            if not lines and self._stop_at_block(index) and not stripped.startswith("\\"):
                break
            lines.append(line)
            index = end + 1
        if not lines:
            # A structural command that was not recognised; report it.
            match = re.match(r"\\([A-Za-z@]+)", self.text[start:])
            command = match.group(1) if match else self.text[start:start + 20]
            raise ConversionError(
                self.path,
                f"LaTeX command \\{command}" if match else f"content {command!r}",
                line_number(self.text, start),
            )
        text = "\n".join(lines).rstrip()
        return Paragraph(text, line_number(self.text, start)), index

    def _parse_heading(self, index: int, match: re.Match) -> tuple[Heading, int]:
        level = {"chapter": 1, "section": 2, "subsection": 3}[match.group(1)]
        starred = match.group(2) == "*"
        cursor = index + match.end() - 1
        title, cursor = read_brace_group(self.text, cursor)
        cursor = self._skip_space(cursor)
        label = None
        if self.text.startswith(r"\label", cursor):
            value, after = _consume_macro(self.text, "label", 1, cursor)
            label = value[0].strip()
            cursor = after
        outlined = False
        cursor_ahead = self._skip_space(cursor)
        if self.text.startswith(r"\addcontentsline", cursor_ahead):
            arguments, after = _consume_macro(self.text, "addcontentsline", 3, cursor_ahead)
            outlined = True
            cursor = after
        elif starred:
            outlined = False
        return (
            Heading(
                level=level,
                title=title.strip(),
                starred=starred,
                label=label,
                outlined=outlined,
                line=line_number(self.text, index),
            ),
            cursor,
        )

    def _parse_structural(self, index: int, match: re.Match) -> tuple[Structural, int]:
        command = match.group(1)
        line = line_number(self.text, index)
        cursor = index + match.end()
        argument = None
        extra = None
        argument_counts = {
            "pagenumbering": 1,
            "setcounter": 2,
            "include": 1,
            "input": 1,
            "addcontentsline": 3,
            "documentclass": 1,
            "hypersetup": 1,
            "graphicspath": 1,
        }
        count = argument_counts.get(command, 0)
        arguments: list[str] = []
        for _ in range(count):
            _, cursor = read_optional_group(self.text, cursor)
            value, cursor = read_brace_group(self.text, cursor)
            arguments.append(value)
        if command == "setcounter" and len(arguments) == 2:
            argument, extra = arguments[0].strip(), arguments[1].strip()
        elif command == "addcontentsline" and len(arguments) == 3:
            argument, extra = arguments[1].strip(), arguments[2].strip()
        elif arguments:
            argument = arguments[0].strip()
        return Structural(command, argument, line, extra), cursor

    def _parse_environment(self, index: int, name: str) -> tuple[object, int]:
        inner_start, inner_end = find_environment_bounds(self.text, index, name)
        line = line_number(self.text, index)
        if name == "figure":
            # Placement options such as [H] belong to the environment; the
            # target helper positions the figure itself.
            placement, after = read_optional_group(self.text, inner_start)
            if placement is not None:
                inner_start = after
        inner = self.text[inner_start:inner_end]
        kind = ENVIRONMENTS[name]
        end_match = re.match(r"\\end\s*\{" + re.escape(name) + r"\}", self.text[inner_end:])
        cursor = inner_end + (end_match.end() if end_match else 0)
        if name == "lstlisting":
            # Options follow the \begin{lstlisting} token.
            begin = re.compile(r"\\begin\s*\{lstlisting\}")
            begin_match = begin.match(self.text, index)
            options, cursor = read_optional_group(self.text, begin_match.end())
            if options is None:
                options = ""
            # The body starts after the end of the begin line.
            newline = self.text.find("\n", begin_match.end())
            body_start = newline + 1 if newline >= 0 else begin_match.end()
            end_match = re.search(r"\\end\s*\{lstlisting\}", self.text[body_start:])
            if end_match is None:
                raise ConversionError(self.path, "unterminated lstlisting", line)
            body = self.text[body_start:body_start + end_match.start()]
            cursor = body_start + end_match.end()
            return Listing(parse_listing(body, options, self.path, line)), cursor
        if name == "figure":
            return Figure(parse_figure(inner, self.path, line)), cursor
        if name == "thesistable":
            return Table(parse_table(inner, self.path, line)), cursor
        if name in ("equation", "equation*"):
            return Equation(parse_equation(inner, name.endswith("*"), self.path, line)), cursor
        if name in ("enumerate", "itemize"):
            items = self._parse_items(inner, line)
            return ListBlock(ordered=(name == "enumerate"), items=items, line=line), cursor
        if name in ("center", "quote", "thesisbibliography"):
            nested = LatexScanner(self.path, inner).scan()
            if name == "center":
                return AlignCenter(blocks=nested), cursor
            if name == "quote":
                return Quote(blocks=nested), cursor
            return Bibliography(blocks=nested, line=line), cursor
        if name == "tabular":
            block = parse_tabular(self.text[index:inner_end], self.path, line)
            return block, cursor
        raise ConversionError(self.path, f"environment {name}", line)

    def _parse_items(self, inner: str, line: int) -> list[str]:
        body = strip_comments(inner)
        parts = re.split(r"\\item\b", body)
        if parts and not parts[0].strip():
            parts = parts[1:]
        items: list[str] = []
        for part in parts:
            cleaned = part.strip()
            if not cleaned:
                continue
            items.append(cleaned)
        if not items:
            raise ConversionError(self.path, "list environment without \\item", line)
        return items


# ---------------------------------------------------------------------------
# Independent raw-source inventory
# ---------------------------------------------------------------------------


@dataclass
class InventoryItem:
    kind: str  # heading | figure | table | listing | equation
    label: str | None
    level: int = 0
    line: int = 0
    unnumbered: bool = False


@dataclass
class Inventory:
    items: list[InventoryItem] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    refs: list[tuple[str, str]] = field(default_factory=list)  # (command, label)

    def object_key(self, kind: str) -> list[tuple[str | None, int]]:
        return [(item.label, item.level) for item in self.items if item.kind == kind]


def _find_environments(text: str, name: str) -> list[tuple[int, int, int]]:
    spans: list[tuple[int, int, int]] = []
    pattern = re.compile(r"\\begin\s*\{" + re.escape(name) + r"\}")
    for match in pattern.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        if "%" in text[line_start:match.start()]:
            continue
        depth = 1
        cursor = match.end()
        begin = re.compile(r"\\begin\s*\{" + re.escape(name) + r"\}")
        end = re.compile(r"\\end\s*\{" + re.escape(name) + r"\}")
        while cursor <= len(text):
            begin_match = begin.search(text, cursor)
            end_match = end.search(text, cursor)
            if end_match is None:
                break
            if begin_match is not None and begin_match.start() < end_match.start():
                depth += 1
                cursor = begin_match.end()
                continue
            depth -= 1
            if depth == 0:
                spans.append((match.start(), end_match.end(), match.end()))
                break
            cursor = end_match.end()
    return spans


def scan_inventory(text: str, path: Path) -> Inventory:
    """Raw-source inventory, independent of the renderer."""
    inventory = Inventory()
    stripped = strip_comments(text)
    heading_pattern = re.compile(r"\\(chapter|section|subsection)(\*?)\s*\{")
    for match in heading_pattern.finditer(stripped):
        end = balanced_span(stripped, match.end() - 1)
        level = {"chapter": 1, "section": 2, "subsection": 3}[match.group(1)]
        # A heading label must follow immediately; stop at the next heading or
        # environment so a later \label is not attributed to this heading.
        window = stripped[end:end + 400]
        stop = re.search(r"\\(?:chapter|section|subsection|begin)\b", window)
        if stop is not None:
            window = window[:stop.start()]
        label_match = re.search(r"\\label\s*\{([^}]+)\}", window)
        inventory.items.append(
            InventoryItem(
                "heading",
                label_match.group(1).strip() if label_match else None,
                level=level,
                line=line_number(text, match.start()),
                unnumbered=match.group(2) == "*",
            )
        )
    for start, end, inner_start in _find_environments(text, "figure"):
        inner = text[inner_start:end]
        _, label = parse_caption_and_label(inner)
        inventory.items.append(
            InventoryItem("figure", label, line=line_number(text, start))
        )
    for start, end, inner_start in _find_environments(text, "thesistable"):
        inner = text[inner_start:end]
        _, label = parse_caption_and_label(inner)
        inventory.items.append(
            InventoryItem("table", label, line=line_number(text, start))
        )
    for match in re.finditer(r"\\begin\s*\{lstlisting\}(?:\[(.*?)\])?", stripped, flags=re.DOTALL):
        options = match.group(1) or ""
        label_match = re.search(r"label\s*=\s*\{([^}]+)\}", options)
        inventory.items.append(
            InventoryItem(
                "listing",
                label_match.group(1).strip() if label_match else None,
                line=line_number(text, match.start()),
            )
        )
    for start, end, inner_start in _find_environments(text, "equation"):
        inner = text[inner_start:end]
        label_match = re.search(r"\\label\s*\{([^}]+)\}", inner)
        inventory.items.append(
            InventoryItem(
                "equation",
                label_match.group(1).strip() if label_match else None,
                line=line_number(text, start),
            )
        )
    for label in re.findall(r"\\label\s*\{([^}]+)\}", stripped):
        inventory.labels.append(label.strip())
    for label in re.findall(r"label\s*=\s*\{([^}]+)\}", stripped):
        inventory.labels.append(label.strip())
    for command in ("ref", "eqref", "autoref", "pageref"):
        for label in re.findall(r"\\" + command + r"\s*\{([^}]+)\}", stripped):
            inventory.refs.append((command, label.strip()))
    return inventory


# ---------------------------------------------------------------------------
# Literal escapes used by the renderer
# ---------------------------------------------------------------------------


def unescape_latex_text(text: str) -> str:
    """Turn LaTeX text escapes into plain characters (for titles and captions)."""
    replacements = {
        r"\%": "%",
        r"\&": "&",
        r"\_": "_",
        r"\#": "#",
        r"\$": "$",
        r"\{": "{",
        r"\}": "}",
        r"\textbackslash{}": "\\",
        r"\textasciitilde{}": "~",
        r"\textasciicircum{}": "^",
    }
    for escaped, literal in replacements.items():
        text = text.replace(escaped, literal)
    return text
