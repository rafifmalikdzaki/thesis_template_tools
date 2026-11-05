"""Discovery and parsing of the Typst thesis starter.

Companion of :mod:`thesis_tools.latex_model`.  It discovers the Typst
repository layout, offers an independent raw-source inventory and a block
scanner for the reverse converter (Typst -> LaTeX).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .common import (
    ConversionError,
    ToolError,
    line_number,
    read_text,
)

CONTENT_DIRS: tuple[str, ...] = ("frontmatter", "chapters", "backmatter", "lampiran")
ADMIN_CALLS: dict[str, str] = {
    "cover-page": "cover",
    "approval-page": "approval",
    "declaration-page": "declaration",
}
OUTLINE_CALLS: dict[str, str] = {
    "Daftar Isi": "contents",
    "Daftar Gambar": "figures",
    "Daftar Tabel": "tables",
    "Daftar Kode Sumber": "listings",
}
OBJECT_CALLS = ("thesis-figure", "thesis-table", "listing", "equation-row")
REQUIRED_TEMPLATE_HELPERS = (
    "thesis-figure",
    "thesis-table",
    "listing",
    "equation-row",
    "thesis-bibliography",
    "appendix",
    "landscape",
    "cover-page",
    "approval-page",
    "declaration-page",
    "outline-page",
    "thesis",
)
REQUIRED_LATEX_INTERFACES = (
    r"\thesisfigure",
    r"\newenvironment{thesistable}",
    r"\newenvironment{thesisbibliography}",
    r"\thesiscoverpage",
    r"\thesisapprovalpage",
    r"\thesisdeclarationpage",
)


# ---------------------------------------------------------------------------
# Repository discovery
# ---------------------------------------------------------------------------


@dataclass
class TypstInclude:
    rel: str  # posix path with .typ, relative to the repository root
    path: Path
    appendix: bool


@dataclass
class TypstProject:
    root: Path
    main: Path
    template: Path | None
    metadata: Path | None
    includes: list[TypstInclude]
    extra_content: list[TypstInclude]
    assets_dir: Path | None

    @classmethod
    def discover(cls, root: Path) -> "TypstProject":
        root = root.resolve()
        if not root.is_dir():
            raise ToolError(f"Typst project directory not found: {root}")
        main = root / "main.typ"
        if not main.is_file():
            raise ToolError(f"{root}: main.typ is missing; not a Typst thesis starter")
        template = _first_existing(root / "template.typ", root / "typst" / "template.typ")
        metadata = _first_existing(root / "metadata.json", root / "typst" / "metadata.json")
        text = read_text(main)
        includes: list[TypstInclude] = []
        seen: set[Path] = set()
        appendix = False
        for match in re.finditer(r'#include\s+"([^"]+)"', text):
            prefix = strip_typst_comments(text[:match.start()])
            if re.search(r"#appendix\s*\(", prefix):
                appendix = True
            rel = match.group(1)
            path = (root / rel).resolve()
            if not path.is_file():
                raise ToolError(f"{root}: main.typ includes {rel!r}, which does not exist")
            if path in seen:
                continue
            seen.add(path)
            includes.append(
                TypstInclude(rel=rel, path=path, appendix=appendix or rel.startswith("lampiran/"))
            )
        extra: list[TypstInclude] = []
        for directory in CONTENT_DIRS:
            base = root / directory
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*.typ")):
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                rel = resolved.relative_to(root).as_posix()
                extra.append(
                    TypstInclude(rel=rel, path=resolved, appendix=rel.startswith("lampiran/"))
                )
        assets_dir = root / "assets" if (root / "assets").is_dir() else None
        return cls(
            root=root,
            main=main,
            template=template,
            metadata=metadata,
            includes=includes,
            extra_content=extra,
            assets_dir=assets_dir,
        )

    def validate_interface(self) -> None:
        if self.template is None or not self.template.is_file():
            raise ToolError(
                f"{self.root}: template.typ is missing; the target must be the Typst thesis starter"
            )
        text = read_text(self.template)
        missing = [
            name for name in REQUIRED_TEMPLATE_HELPERS
            if not re.search(r"#let\s+" + re.escape(name) + r"\b", text)
        ]
        if missing:
            raise ToolError(
                f"{self.template}: missing helper(s) {', '.join(missing)}; "
                "the target does not expose the Typst starter interface"
            )


def _first_existing(*paths: Path) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


# ---------------------------------------------------------------------------
# Low-level Typst helpers
# ---------------------------------------------------------------------------


def strip_typst_comments(text: str) -> str:
    out: list[str] = []
    for line in text.split("\n"):
        index = line.find("//")
        if index >= 0:
            line = line[:index]
        out.append(line)
    return "\n".join(out)


def read_balanced(text: str, start: int) -> int:
    """Return the index just after the balanced group opening at ``start``.

    The three Typst delimiter kinds are tracked together, because a content
    block can contain parentheses (``[Proporsi (%)]``) and vice versa.
    """
    closers = {"(": ")", "[": "]", "{": "}"}
    stack: list[str] = []
    index = start
    while index < len(text):
        character = text[index]
        if character == '"':
            index += 1
            while index < len(text):
                if text[index] == "\\":
                    index += 2
                    continue
                if text[index] == '"':
                    index += 1
                    break
                index += 1
            continue
        if text.startswith("```", index):
            end = text.find("```", index + 3)
            index = len(text) if end < 0 else end + 3
            continue
        if text.startswith("//", index) and not text[text.rfind("\n", 0, index) + 1:index].strip():
            end = text.find("\n", index)
            index = len(text) if end < 0 else end + 1
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = len(text) if end < 0 else end + 2
            continue
        if character in closers:
            stack.append(closers[character])
        elif character in (")", "]", "}"):
            if not stack or stack[-1] != character:
                raise ToolError("unbalanced delimiter in Typst source")
            stack.pop()
            if not stack:
                return index + 1
        index += 1
    raise ToolError("unbalanced delimiter in Typst source")


def parse_call(text: str, index: int) -> tuple[str, str, int]:
    """Parse ``#name`` at ``index``.

    Returns ``(name, arguments_text, end)`` where ``arguments_text`` includes
    the outer delimiters of the single argument group when present.
    """
    match = re.match(r"#([A-Za-z][A-Za-z0-9-]*)", text[index:])
    if match is None:
        raise ToolError("internal error: not a Typst call")
    name = match.group(1)
    cursor = index + match.end()
    while cursor < len(text) and text[cursor] in " \t":
        cursor += 1
    if cursor < len(text) and text[cursor] in "([":
        end = read_balanced(text, cursor)
        return name, text[cursor:end], end
    return name, "", cursor


def split_arguments(arguments: str) -> list[str]:
    """Split a Typst argument list on top-level commas."""
    inner = arguments
    if inner and inner[0] in "([":
        inner = inner[1:-1]
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    index = 0
    while index < len(inner):
        character = inner[index]
        if character == '"':
            end = index + 1
            while end < len(inner):
                if inner[end] == "\\":
                    end += 2
                    continue
                if inner[end] == '"':
                    end += 1
                    break
                end += 1
            current.append(inner[index:end])
            index = end
            continue
        if inner.startswith("```", index):
            end = inner.find("```", index + 3)
            end = len(inner) if end < 0 else end + 3
            current.append(inner[index:end])
            index = end
            continue
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        if character == "," and depth == 0:
            parts.append("".join(current))
            current = []
            index += 1
            continue
        current.append(character)
        index += 1
    if current:
        parts.append("".join(current))
    return [part for part in parts if part.strip()]


def parse_arguments(arguments: str) -> tuple[dict[str, str], list[str]]:
    """Split call arguments into named (``key: value``) and positional parts."""
    named: dict[str, str] = {}
    positional: list[str] = []
    for part in split_arguments(arguments):
        stripped = part.strip()
        match = re.match(r"([A-Za-z][A-Za-z0-9-]*)\s*:\s*", stripped)
        if match:
            named[match.group(1)] = stripped[match.end():].strip()
        else:
            positional.append(stripped)
    return named, positional


def content_text(value: str) -> str:
    """Strip a content block ``[...]`` and return its inner source."""
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        return value[1:-1]
    return value


def literal_text(value: str) -> str:
    """Return the text of a content block or a quoted string."""
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return content_text(value)


def trailing_label(text: str, index: int) -> tuple[str | None, int]:
    match = re.match(r"\s*<([A-Za-z][A-Za-z0-9_.:-]*)>", text[index:])
    if not match:
        return None, index
    return match.group(1), index + match.end()


# ---------------------------------------------------------------------------
# Call specifications
# ---------------------------------------------------------------------------


@dataclass
class TypstFigure:
    path: str
    caption: str
    label: str | None
    line: int


@dataclass
class TypstTable:
    caption: str
    columns: list[str] | None  # raw width expressions; None = auto columns
    align: list[str]
    header: list[str]
    rows: list[list[str]]
    rules: list[int]
    landscape: bool
    label: str | None
    line: int


@dataclass
class TypstListing:
    caption: str
    language: str | None
    body: str
    label: str | None
    line: int


@dataclass
class TypstEquation:
    math: str
    label: str | None
    line: int


def parse_figure_call(arguments: str, label: str | None, path: Path, line: int) -> TypstFigure:
    named, positional = parse_arguments(arguments)
    if label is None and "label" in named:
        match = re.search(r"<([A-Za-z][A-Za-z0-9_.:-]*)>", named["label"])
        label = match.group(1) if match else None
    if not positional:
        raise ConversionError(path, "thesis-figure without an asset path", line)
    asset = literal_text(positional[0])
    caption = content_text(named.get("caption", "[]")) if "caption" in named else ""
    if not caption.strip():
        raise ConversionError(path, "thesis-figure without a caption", line)
    if label is None:
        raise ConversionError(path, "thesis-figure without a label", line)
    return TypstFigure(path=asset, caption=caption, label=label, line=line)


def _tuple_items(value: str) -> list[str]:
    value = value.strip()
    if value.startswith("(") and value.endswith(")"):
        return split_arguments(value)
    return [value]


def parse_table_call(arguments: str, label: str | None, path: Path, line: int) -> TypstTable:
    named, positional = parse_arguments(arguments)
    if label is None and "label" in named:
        match = re.search(r"<([A-Za-z][A-Za-z0-9_.:-]*)>", named["label"])
        label = match.group(1) if match else None
    caption = content_text(named.get("caption", ""))
    if not caption.strip():
        raise ConversionError(path, "thesis-table without a caption", line)
    if label is None:
        raise ConversionError(path, "thesis-table without a label", line)
    columns_value = named.get("columns")
    columns: list[str] | None = None
    if columns_value is not None:
        columns = [item.strip() for item in _tuple_items(columns_value)]
        if len(columns) == 1 and columns[0] in ("auto", "none"):
            columns = None
    align_value = named.get("align")
    align = [
        item.strip() for item in _tuple_items(align_value)
    ] if align_value is not None else ["left"]
    header_value = named.get("header")
    header = (_tuple_items(header_value) if header_value is not None else [])
    rules_value = named.get("rules")
    rules: list[int] = []
    if rules_value is not None:
        for item in _tuple_items(rules_value):
            item = item.strip()
            if not item:
                continue
            if not item.isdigit():
                raise ConversionError(path, f"thesis-table rule {item!r}", line)
            rules.append(int(item))
    cells = [content_text(cell) for cell in positional]
    width = len(columns) if columns is not None else None
    if width is None:
        width = max(len(header), 1) if header else 1
    if header and len(header) != width:
        raise ConversionError(path, "thesis-table header width does not match columns", line)
    if cells and width and len(cells) % width != 0:
        raise ConversionError(path, "thesis-table body cell count is not a multiple of columns", line)
    rows = [cells[index:index + width] for index in range(0, len(cells), width)] if width else []
    if not rows:
        raise ConversionError(path, "thesis-table without body rows", line)
    if len(align) not in (1, width):
        raise ConversionError(path, "thesis-table align tuple does not match columns", line)
    return TypstTable(
        caption=caption,
        columns=columns,
        align=align,
        header=header,
        rows=rows,
        rules=rules,
        landscape=False,
        label=label,
        line=line,
    )


def parse_listing_call(arguments: str, label: str | None, path: Path, line: int) -> TypstListing:
    named, positional = parse_arguments(arguments)
    if label is None and "label" in named:
        match = re.search(r"<([A-Za-z][A-Za-z0-9_.:-]*)>", named["label"])
        label = match.group(1) if match else None
    if "caption" in named:
        caption = content_text(named["caption"])
    elif positional:
        caption = content_text(positional[0])
        positional = positional[1:]
    else:
        raise ConversionError(path, "listing without a caption", line)
    body_block = positional[0] if positional else ""
    fence = re.search(r"```([^\n`]*)\n(.*?)```", body_block, flags=re.DOTALL)
    if fence is None:
        raise ConversionError(path, "listing without a fenced code block", line)
    language = fence.group(1).strip() or None
    if label is None:
        raise ConversionError(path, "listing without a label", line)
    return TypstListing(
        caption=caption, language=language, body=fence.group(2), label=label, line=line
    )


def parse_equation_call(body: str, label: str | None, path: Path, line: int) -> TypstEquation:
    match = re.search(r"\$(.+?)\$", body, flags=re.DOTALL)
    if match is None:
        raise ConversionError(path, "equation-row without $ ... $ mathematics", line)
    if label is None:
        # The equation label is attached to the mathematics inside the block:
        #   #equation-row[ $ ... $ <eq:3.1> ]
        inner = re.search(r"<([A-Za-z][A-Za-z0-9_.:-]*)>", body)
        label = inner.group(1) if inner else None
    return TypstEquation(math=match.group(1).strip(), label=label, line=line)


# ---------------------------------------------------------------------------
# Raw-source inventory (independent of the reverse renderer)
# ---------------------------------------------------------------------------

HEADING_RE = re.compile(r"(?m)^(=+)[ \t]+([^\n]*)$")
LABEL_RE = re.compile(r"<([A-Za-z][A-Za-z0-9_.:-]*)>")
REF_RE = re.compile(r"(?<![\w@])@([A-Za-z][A-Za-z0-9_.:-]*)")
LINK_RE = re.compile(r"#(?:ref|link)\(\s*<([A-Za-z][A-Za-z0-9_.:-]*)>\s*\)")
CALL_RE = re.compile(r"#(thesis-figure|thesis-table|listing|equation-row)\s*[\[\(]")
NUMERIC_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])[0-9X]+(?:[.,][0-9X]+)*(?![A-Za-z0-9])")


def mask_typst(text: str) -> str:
    """Blank raw blocks, math and comments so labels/refs inside are ignored."""
    characters = list(text)

    def blank(start: int, end: int) -> None:
        for index in range(start, min(end, len(characters))):
            if characters[index] != "\n":
                characters[index] = " "

    for match in re.finditer(r"```.*?```", text, flags=re.DOTALL):
        blank(match.start(), match.end())
    for match in re.finditer(r"\$[^$]*\$", text, flags=re.DOTALL):
        blank(match.start(), match.end())
    for match in re.finditer(r"//[^\n]*", text):
        blank(match.start(), match.end())
    return "".join(characters)


@dataclass
class TypstInventoryItem:
    kind: str
    label: str | None
    level: int = 0
    line: int = 0
    unnumbered: bool = False


@dataclass
class TypstInventory:
    items: list[TypstInventoryItem] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)


def scan_inventory(text: str, path: Path) -> TypstInventory:
    inventory = TypstInventory()
    masked = mask_typst(text)
    entries: list[tuple[int, TypstInventoryItem]] = []
    for match in HEADING_RE.finditer(masked):
        line = match.group(2)
        label_match = re.search(r"<([A-Za-z][A-Za-z0-9_.:-]*)>\s*$", line)
        label = label_match.group(1) if label_match else None
        entries.append(
            (
                match.start(),
                TypstInventoryItem(
                    "heading",
                    label,
                    level=len(match.group(1)),
                    line=line_number(text, match.start()),
                ),
            )
        )
    heading_call = re.compile(r"#heading\s*\(")
    cursor = 0
    while True:
        call = heading_call.search(text, cursor)
        if call is None:
            break
        end = read_balanced(text, call.end() - 1)
        arguments = text[call.end() - 1:end]
        named, _positional = parse_arguments(arguments)
        level_match = re.search(r"([0-9]+)", named.get("level", "1"))
        level = int(level_match.group(1)) if level_match else 1
        unnumbered = named.get("numbering", "auto").strip() == "none"
        label, _after = trailing_label(text, end)
        entries.append(
            (
                call.start(),
                TypstInventoryItem(
                    "heading",
                    label,
                    level=level,
                    line=line_number(text, call.start()),
                    unnumbered=unnumbered,
                ),
            )
        )
        cursor = end
    index = 0
    while index < len(text):
        match = CALL_RE.search(text, index)
        if match is None:
            break
        name = match.group(1)
        arguments_start = match.end() - 1
        end = read_balanced(text, arguments_start)
        label, after = trailing_label(text, end)
        if label is None:
            inside = LABEL_RE.findall(text[arguments_start:end])
            label = inside[-1] if inside else None
        if name == "listing":
            cursor = after
            while cursor < len(text) and text[cursor] in " \t":
                cursor += 1
            if cursor < len(text) and text[cursor] == "[":
                after = read_balanced(text, cursor)
                label, after = trailing_label(text, after)
        kind = {
            "thesis-figure": "figure",
            "thesis-table": "table",
            "listing": "listing",
            "equation-row": "equation",
        }[name]
        entries.append(
            (
                match.start(),
                TypstInventoryItem(kind, label, line=line_number(text, match.start())),
            )
        )
        index = max(after, match.end())
    inventory.items = [item for _position, item in sorted(entries, key=lambda entry: entry[0])]
    inventory.labels = LABEL_RE.findall(masked)
    raw_refs = REF_RE.findall(masked) + LINK_RE.findall(masked)
    known = set(inventory.labels)
    for reference in raw_refs:
        if reference in known:
            inventory.refs.append(reference)
            continue
        stripped = reference.rstrip(".,;:)]}")
        inventory.refs.append(stripped if stripped in known else reference)
    return inventory


# ---------------------------------------------------------------------------
# Block scanner used by the reverse renderer
# ---------------------------------------------------------------------------


@dataclass
class THeading:
    level: int
    title: str
    label: str | None
    numbered: bool
    outlined: bool
    line: int


@dataclass
class TFigure:
    spec: TypstFigure


@dataclass
class TTable:
    spec: TypstTable


@dataclass
class TListing:
    spec: TypstListing


@dataclass
class TEquation:
    spec: TypstEquation


@dataclass
class TParagraph:
    text: str
    line: int


@dataclass
class TList:
    ordered: bool
    items: list[str]
    line: int


@dataclass
class TBibliography:
    blocks: list
    line: int


@dataclass
class TLandscape:
    blocks: list
    line: int


@dataclass
class TGrid:
    columns: list[str]
    cells: list[str]
    line: int


@dataclass
class TAlign:
    blocks: list
    line: int


@dataclass
class TPageBreak:
    line: int


@dataclass
class TComment:
    text: str


@dataclass
class TStructural:
    """A main-file call such as #include, #appendix, #set, #outline-page."""

    kind: str
    argument: str | None
    line: int
    extra: str | None = None


class TypstScanner:
    """Split a Typst content file into block tokens in document order."""

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
            if self.text.startswith("//", index):
                end = self.text.find("\n", index)
                end = length if end < 0 else end
                blocks.append(TComment(self.text[index:end]))
                index = end
                continue
            line_end = self.text.find("\n", index)
            line_end = length if line_end < 0 else line_end
            line = self.text[index:line_end]
            heading = re.match(r"(=+)\s+(.*)$", line)
            if heading is not None:
                label = None
                title = heading.group(2).strip()
                label_match = re.search(r"<([A-Za-z][A-Za-z0-9_.:-]*)>\s*$", title)
                if label_match:
                    label = label_match.group(1)
                    title = title[:label_match.start()].strip()
                blocks.append(
                    THeading(
                        level=len(heading.group(1)),
                        title=title,
                        label=label,
                        numbered=True,
                        outlined=True,
                        line=line_number(self.text, index),
                    )
                )
                index = line_end
                continue
            if self.text.startswith("#", index):
                block, index = self._parse_call(index)
                blocks.append(block)
                continue
            if re.match(r"^(?:\+|-)\s+", line):
                block, index = self._parse_list(index)
                blocks.append(block)
                continue
            block, index = self._parse_paragraph(index)
            blocks.append(block)
        return blocks

    def _skip_space(self, index: int) -> int:
        length = len(self.text)
        while index < length and self.text[index] in " \t\r\n":
            index += 1
        return index

    def _parse_paragraph(self, index: int) -> tuple[TParagraph, int]:
        start = index
        lines: list[str] = []
        length = len(self.text)
        while index < length:
            end = self.text.find("\n", index)
            end = length if end < 0 else end
            line = self.text[index:end]
            if not line.strip():
                index = end + 1
                break
            if lines and (
                self.text.startswith("#", index)
                or re.match(r"(=+)\s+", line)
                or re.match(r"^(?:\+|-)\s+", line)
                or line.lstrip().startswith("//")
            ):
                break
            lines.append(line)
            index = end + 1
        if not lines:
            raise ConversionError(
                self.path,
                f"content {self.text[start:start + 30]!r}",
                line_number(self.text, start),
            )
        return TParagraph("\n".join(lines).rstrip(), line_number(self.text, start)), index

    def _parse_list(self, index: int) -> tuple[TList, int]:
        ordered = self.text[index] == "+"
        start = index
        items: list[str] = []
        current: list[str] = []
        length = len(self.text)
        while index < length:
            end = self.text.find("\n", index)
            end = length if end < 0 else end
            line = self.text[index:end]
            if not line.strip():
                index = end + 1
                break
            marker = re.match(r"^(\+|-)\s+(.*)$", line)
            if marker is not None:
                if current:
                    items.append("\n".join(current))
                current = [marker.group(2)]
            elif line.startswith((" ", "\t")) and current:
                current.append(line.strip())
            else:
                break
            index = end + 1
        if current:
            items.append("\n".join(current))
        if not items:
            raise ConversionError(self.path, "list without items", line_number(self.text, start))
        return TList(ordered=ordered, items=items, line=line_number(self.text, start)), index

    def _parse_call(self, index: int) -> tuple[object, int]:
        line = line_number(self.text, index)
        if self.text.startswith("#import", index):
            end = self.text.find("\n", index)
            end = len(self.text) if end < 0 else end
            return TStructural("import", self.text[index:end].strip(), line), end
        if self.text.startswith("#include", index):
            match = re.match(r'#include\s+"([^"]+)"', self.text[index:])
            if match is None:
                raise ConversionError(self.path, "malformed #include", line)
            return TStructural("include", match.group(1), line), index + match.end()
        if self.text.startswith("#show", index):
            end = self.text.find("\n", index)
            end = len(self.text) if end < 0 else end
            return TStructural("show", self.text[index:end].strip(), line), end
        if self.text.startswith("#set page", index):
            end = self.text.find("\n", index)
            end = len(self.text) if end < 0 else end
            statement = self.text[index:end].strip()
            numbering = re.search(r'numbering:\s*(?:none|"([^"]*)")', statement)
            return TStructural("page-numbering", numbering.group(1) if numbering and numbering.group(1) else None, line), end
        if self.text.startswith("#counter(page)", index):
            end = self.text.find("\n", index)
            end = len(self.text) if end < 0 else end
            return TStructural("page-counter", self.text[index:end].strip(), line), end
        if self.text.startswith("#set", index):
            end = self.text.find("\n", index)
            end = len(self.text) if end < 0 else end
            return TStructural("set", self.text[index:end].strip(), line), end
        if self.text.startswith("#outline-page", index):
            name, arguments, end = parse_call(self.text, index)
            named, positional = parse_arguments(arguments)
            title = literal_text(positional[0]) if positional else ""
            depth = named.get("depth", "2").strip()
            target = named.get("target", "heading").strip()
            return TStructural("outline", title, line, extra=f"{target}|{depth}"), end
        name, arguments, end = parse_call(self.text, index)
        if name in ADMIN_CALLS:
            return TStructural("admin", ADMIN_CALLS[name], line), end
        if name == "appendix":
            return TStructural("appendix", None, line), end
        if name == "pagebreak":
            return TPageBreak(line), end
        if name == "thesis-figure":
            label, after = trailing_label(self.text, end)
            return TFigure(parse_figure_call(arguments, label, self.path, line)), after
        if name == "thesis-table":
            label, after = trailing_label(self.text, end)
            return TTable(parse_table_call(arguments, label, self.path, line)), after
        if name == "listing":
            label, after = trailing_label(self.text, end)
            cursor = after
            while cursor < len(self.text) and self.text[cursor] in " \t":
                cursor += 1
            second = ""
            if cursor < len(self.text) and self.text[cursor] == "[":
                second_end = read_balanced(self.text, cursor)
                second = self.text[cursor:second_end]
                after = second_end
            label, after = trailing_label(self.text, after)
            combined = arguments
            if second:
                combined = arguments[:-1] + ", " + second + "]" if arguments.startswith("(") else arguments + second
            return TListing(parse_listing_call(combined, label, self.path, line)), after
        if name == "equation-row":
            body = content_text(arguments) if arguments.startswith("[") else ""
            close = read_balanced(self.text, end - len(arguments)) if arguments.startswith("[") else end
            label, after = trailing_label(self.text, close)
            return TEquation(parse_equation_call(body, label, self.path, line)), after
        if name == "landscape":
            body = content_text(arguments)
            inner = TypstScanner(self.path, body).scan()
            return TLandscape(blocks=inner, line=line), end
        if name == "thesis-bibliography":
            body = content_text(arguments)
            inner = TypstScanner(self.path, body).scan()
            return TBibliography(blocks=inner, line=line), end
        if name == "align":
            body = content_text(arguments)
            inner = TypstScanner(self.path, body).scan()
            return TAlign(blocks=inner, line=line), end
        if name == "grid":
            named, positional = parse_arguments(arguments)
            columns = [item.strip() for item in _tuple_items(named.get("columns", "()"))]
            cells = [content_text(cell) for cell in positional]
            if not cells:
                raise ConversionError(self.path, "grid without cells", line)
            return TGrid(columns=columns, cells=cells, line=line), end
        if name == "heading":
            named, positional = parse_arguments(arguments)
            body = content_text(positional[0]) if positional else ""
            level = int(named.get("level", "1").strip())
            numbered = named.get("numbering", "auto").strip() != "none"
            outlined = named.get("outlined", "true").strip() != "false"
            cursor = end
            while cursor < len(self.text) and self.text[cursor] in " \t":
                cursor += 1
            if cursor < len(self.text) and self.text[cursor] == "[":
                body_end = read_balanced(self.text, cursor)
                body = self.text[cursor + 1:body_end - 1]
                end = body_end
            label, after = trailing_label(self.text, end)
            return (
                THeading(
                    level=level,
                    title=body.strip(),
                    label=label,
                    numbered=numbered,
                    outlined=outlined,
                    line=line,
                ),
                after,
            )
        if name in ("v", "h", "linebreak", "text", "link", "emph", "strong", "underline", "super", "sub", "smallcaps", "raw", "footnote"):
            # These are inline helpers; at block position they form a paragraph.
            start = index
            paragraph, cursor = self._paragraph_with_inline(start)
            return paragraph, cursor
        raise ConversionError(self.path, f"Typst call #{name}", line)

    def _paragraph_with_inline(self, start: int) -> tuple[TParagraph, int]:
        index = start
        lines: list[str] = []
        length = len(self.text)
        while index < length:
            end = self.text.find("\n", index)
            end = length if end < 0 else end
            line = self.text[index:end]
            if not line.strip():
                index = end + 1
                break
            lines.append(line)
            index = end + 1
        return TParagraph("\n".join(lines).rstrip(), line_number(self.text, start)), index
