"""Small shared primitives: errors, text helpers and the metadata contract.

Nothing here depends on a particular template repository layout; the two
``*_model`` modules own repository discovery and the parsers.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ToolError(Exception):
    """Fatal, user-facing error in any tool."""


class ConversionError(ToolError):
    """An input construct that cannot be converted is reported, never dropped.

    The message always names the file and (when known) the line and the
    construct, because a conversion tool that silently drops content is worse
    than one that refuses to run.
    """

    def __init__(self, path: Path | str, construct: str, line: int | None = None) -> None:
        self.path = Path(path)
        self.construct = construct
        self.line = line
        location = f"{self.path}:{line}" if line else str(self.path)
        super().__init__(f"{location}: unsupported {construct}")

    def as_dict(self) -> dict:
        return {
            "file": str(self.path),
            "line": self.line,
            "construct": self.construct,
            "message": str(self),
        }


class DriftError(ToolError):
    """The target of a ``--check`` run does not match the regenerated output."""


# ---------------------------------------------------------------------------
# Small text helpers
# ---------------------------------------------------------------------------


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise ToolError(f"cannot read {path}: {error}") from error


def line_number(text: str, offset: int) -> int:
    """Return the 1-based line number of ``offset`` in ``text``."""
    return text.count("\n", 0, max(0, offset)) + 1


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def balanced_span(text: str, start: int) -> int:
    """Return the index just after the balanced group opening at ``start``.

    Handles nested LaTeX braces and skips escaped characters and comments.
    """
    if start >= len(text) or text[start] != "{":
        raise ToolError(f"internal error: no group at offset {start}")
    depth = 0
    index = start
    while index < len(text):
        character = text[index]
        if character == "\\" and index + 1 < len(text):
            index += 2
            continue
        if character == "%" and (index == 0 or text[index - 1] != "\\"):
            end = text.find("\n", index)
            index = len(text) if end < 0 else end + 1
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    raise ToolError("unbalanced braces in LaTeX source")


def split_top_level(text: str, separator: str) -> list[str]:
    """Split on ``separator`` outside braces, math and comments.

    Used for table rows (``\\\\``) and cells (``&``).
    """
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\\":
            if text.startswith(separator, index):
                if depth == 0:
                    parts.append("".join(current))
                    current = []
                    index += len(separator)
                    continue
            current.append(text[index])
            index += 1
            if index < len(text) and text[index - 1] == "\\":
                # keep escaped pairs together, e.g. \% or \&
                current.append(text[index])
                index += 1
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth = max(0, depth - 1)
        if character == separator and depth == 0:
            parts.append("".join(current))
            current = []
            index += 1
            continue
        current.append(character)
        index += 1
    parts.append("".join(current))
    return parts


def natural_key(value: str | Path) -> list:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", str(value))]


def relative_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary, path)
        os.chmod(path, 0o644)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def copy_bytes_atomic(source: Path, target: Path) -> bool:
    """Copy ``source`` to ``target``; return True when the bytes changed."""
    data = source.read_bytes()
    if target.is_file():
        try:
            if target.read_bytes() == data:
                return False
        except OSError:
            pass
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.replace(temporary, target)
        os.chmod(target, 0o644)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return True


# ---------------------------------------------------------------------------
# Metadata contract
# ---------------------------------------------------------------------------

# Fixed key order.  Both metadata.tex (LaTeX) and metadata.json (Typst) use the
# same keys; the LaTeX file maps them to the \Thesis* interface commands.
KEY_ORDER: tuple[str, ...] = (
    "title",
    "title_en",
    "type",
    "author",
    "nim",
    "program",
    "department",
    "faculty",
    "university",
    "city",
    "year",
    "degree",
    "exam_date",
    "supervisor_one",
    "supervisor_one_nip",
    "supervisor_two",
    "supervisor_two_nip",
    "head_of_program",
    "head_of_program_nip",
    "head_of_department",
    "head_of_department_nip",
    "keywords_id",
    "keywords_en",
)

KEY_TO_COMMAND: dict[str, str] = {
    "title": "ThesisTitle",
    "title_en": "ThesisTitleEn",
    "type": "ThesisType",
    "author": "ThesisAuthor",
    "nim": "ThesisNIM",
    "program": "ThesisProgram",
    "department": "ThesisDepartment",
    "faculty": "ThesisFaculty",
    "university": "ThesisUniversity",
    "city": "ThesisCity",
    "year": "ThesisYear",
    "degree": "ThesisDegree",
    "exam_date": "ThesisExamDate",
    "supervisor_one": "ThesisSupervisorOne",
    "supervisor_one_nip": "ThesisSupervisorOneNIP",
    "supervisor_two": "ThesisSupervisorTwo",
    "supervisor_two_nip": "ThesisSupervisorTwoNIP",
    "head_of_program": "ThesisHeadOfProgram",
    "head_of_program_nip": "ThesisHeadOfProgramNIP",
    "head_of_department": "ThesisHeadOfDepartment",
    "head_of_department_nip": "ThesisHeadOfDepartmentNIP",
    "keywords_id": "ThesisKeywordsID",
    "keywords_en": "ThesisKeywordsEN",
}
COMMAND_TO_KEY: dict[str, str] = {command: key for key, command in KEY_TO_COMMAND.items()}

LATEX_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Manuscript identity", ("title", "title_en", "type", "author", "nim")),
    (
        "Academic affiliation",
        ("program", "department", "faculty", "university", "city", "year", "degree"),
    ),
    (
        "Examination and supervision",
        (
            "exam_date",
            "supervisor_one",
            "supervisor_one_nip",
            "supervisor_two",
            "supervisor_two_nip",
            "head_of_program",
            "head_of_program_nip",
            "head_of_department",
            "head_of_department_nip",
        ),
    ),
    ("Keywords (semicolon separated)", ("keywords_id", "keywords_en")),
)

_LATEX_ESCAPES: dict[str, str] = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "^": r"\textasciicircum{}",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "%": r"\%",
}


def latex_escape(value: str) -> str:
    """Escape LaTeX special characters in a plain-text metadata value."""
    return "".join(_LATEX_ESCAPES.get(character, character) for character in value)


def latex_unescape(value: str) -> str:
    """Inverse of :func:`latex_escape` (used when reading metadata.tex back)."""
    value = value.replace(r"\textbackslash{}", "\\")
    value = value.replace(r"\textasciicircum{}", "^")
    value = value.replace(r"\textasciitilde{}", "~")
    for escaped, literal in (
        (r"\{", "{"),
        (r"\}", "}"),
        (r"\$", "$"),
        (r"\&", "&"),
        (r"\#", "#"),
        (r"\_", "_"),
        (r"\%", "%"),
    ):
        value = value.replace(escaped, literal)
    return value


def validate_metadata(values: dict, origin: str) -> dict[str, str]:
    """Validate a metadata mapping and return values in contract order."""
    if not isinstance(values, dict):
        raise ToolError(f"{origin} must contain a mapping of key -> string")
    missing = [key for key in KEY_ORDER if key not in values]
    unknown = sorted(set(values) - set(KEY_ORDER))
    if missing or unknown:
        details = []
        if missing:
            details.append("missing keys: " + ", ".join(missing))
        if unknown:
            details.append("unknown keys: " + ", ".join(unknown))
        raise ToolError(f"{origin}: " + "; ".join(details))
    ordered: dict[str, str] = {}
    for key in KEY_ORDER:
        value = values[key]
        if not isinstance(value, str):
            raise ToolError(f"{origin}: value for '{key}' must be a string")
        if not value.strip():
            raise ToolError(f"{origin}: value for '{key}' must not be empty")
        if "\n" in value or "\r" in value:
            raise ToolError(f"{origin}: value for '{key}' must be a single line")
        if any(ord(character) < 32 for character in value):
            raise ToolError(f"{origin}: value for '{key}' contains control characters")
        ordered[key] = value
    return ordered


def parse_metadata_tex(text: str, origin: str) -> dict[str, str]:
    """Read the ``\\newcommand{\\Thesis...}{value}`` contract from metadata.tex."""
    values: dict[str, str] = {}
    for match in re.finditer(
        r"\\newcommand\s*\{\\([A-Za-z@]+)\}\s*\{(.*)\}\s*$", text, flags=re.MULTILINE
    ):
        command, raw = match.group(1), match.group(2)
        key = COMMAND_TO_KEY.get(command)
        if key is None:
            raise ToolError(f"{origin}: unknown metadata command \\{command}")
        if key in values:
            raise ToolError(f"{origin}: metadata command \\{command} defined twice")
        values[key] = latex_unescape(raw)
    missing = [KEY_TO_COMMAND[key] for key in KEY_ORDER if key not in values]
    if missing:
        raise ToolError(
            f"{origin}: missing metadata commands: " + ", ".join("\\" + name for name in missing)
        )
    return validate_metadata(values, origin)


def render_metadata_tex(values: dict[str, str], generator: str = "scripts/sync_metadata.py") -> str:
    """Render metadata.tex deterministically from validated values."""
    lines = [
        "% =====================================================================",
        "%  METADATA — administrative values shared with the Typst starter",
        "% =====================================================================",
        "%  The Typst starter carries the same values in metadata.json.",
        f"%  Synchronise: python3 {generator} --latex <repo> --typst <repo>",
        f"%  Check:       python3 {generator} --latex <repo> --typst <repo> --check",
        "%",
        "%  Every value is the argument of a single \\newcommand and contains",
        "%  plain text only. The writer escapes LaTeX special characters; the",
        "%  file is safe to edit by hand and the synchroniser preserves nothing",
        "%  else, so keep the value lines intact.",
        "% =====================================================================",
        "",
    ]
    for title, keys in LATEX_SECTIONS:
        prefix = f"% -- {title} "
        lines.append(prefix + "-" * max(3, 70 - len(prefix)))
        for key in keys:
            lines.append(f"\\newcommand{{\\{KEY_TO_COMMAND[key]}}}{{{latex_escape(values[key])}}}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def render_metadata_json(values: dict[str, str]) -> str:
    """Render the Typst metadata.json deterministically."""
    return json.dumps(values, ensure_ascii=False, indent=2) + "\n"


def load_metadata_json(path: Path) -> dict[str, str]:
    try:
        raw = json.loads(read_text(path))
    except json.JSONDecodeError as error:
        raise ToolError(f"{path}: invalid JSON: {error}") from error
    return validate_metadata(raw, str(path))


# ---------------------------------------------------------------------------
# Typst text escaping used by the LaTeX -> Typst renderer
# ---------------------------------------------------------------------------

_TYPST_LITERAL_ESCAPES = {
    "\\": "\\\\",
    "#": "\\#",
    "$": "\\$",
    "@": "\\@",
    "_": "\\_",
    "*": "\\*",
    "<": "\\<",
    ">": "\\>",
    "`": "\\`",
    "~": "\\~",
}


def escape_typst_markup(text: str) -> str:
    return "".join(_TYPST_LITERAL_ESCAPES.get(character, character) for character in text)


def balance_brackets(text: str) -> str:
    """Escape square brackets when they are not balanced.

    Typst content blocks use balanced brackets, so literal ``[``/``]`` are fine
    (and readable) as long as they pair up.  An unbalanced bracket would break
    the block, so it is escaped instead.  Brackets already escaped are left
    alone.
    """
    openings = len(re.findall(r"(?<!\\)\[", text))
    closings = len(re.findall(r"(?<!\\)\]", text))
    if openings == closings:
        return text
    return re.sub(r"(?<!\\)([\[\]])", r"\\\1", text)


def typst_string(value: str) -> str:
    """Quote a Python string as a Typst string literal."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return '"' + escaped + '"'
