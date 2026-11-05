"""Write or check the output of a converter.

Both converters produce an in-memory :class:`ConversionResult` (text files and
asset copies).  ``--check`` compares that result with the target repository
without writing; the normal mode writes only changed files and reports how many
were updated.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .common import copy_bytes_atomic, write_text_atomic


def apply_result(result, target: Path, check: bool) -> int:
    """Write or verify a conversion result; return an exit code."""
    target = target.resolve()
    missing: list[str] = []
    stale: list[str] = []
    updated = 0
    unchanged = 0
    for relative in sorted(result.files):
        destination = target / relative
        content = result.files[relative]
        if not destination.is_file():
            if check:
                missing.append(relative)
                continue
            write_text_atomic(destination, content)
            updated += 1
            continue
        try:
            current = destination.read_text(encoding="utf-8")
        except OSError as error:
            print(f"error: cannot read {destination}: {error}", file=sys.stderr)
            return 2
        if current == content:
            unchanged += 1
            continue
        if check:
            stale.append(relative)
            continue
        write_text_atomic(destination, content)
        updated += 1
    asset_updated = 0
    asset_unchanged = 0
    for relative in sorted(result.assets):
        destination = target / relative
        source = result.assets[relative]
        if not destination.is_file():
            if check:
                missing.append(relative)
                continue
            copy_bytes_atomic(source, destination)
            asset_updated += 1
            continue
        try:
            same = destination.read_bytes() == source.read_bytes()
        except OSError as error:
            print(f"error: cannot read {destination}: {error}", file=sys.stderr)
            return 2
        if same:
            asset_unchanged += 1
            continue
        if check:
            stale.append(relative)
            continue
        copy_bytes_atomic(source, destination)
        asset_updated += 1

    if check:
        if not missing and not stale:
            print(
                f"check: up to date — {unchanged} unchanged text file(s), "
                f"{asset_unchanged} unchanged asset(s)"
            )
            return 0
        print("check: FAILED — the target differs from the generated output")
        for name in missing:
            print(f"  missing: {name}")
        for name in stale:
            print(f"  stale:   {name}")
        print("run the converter without --check to regenerate the target")
        return 1

    print(
        f"wrote {updated} updated text file(s), {unchanged} unchanged; "
        f"{asset_updated} asset(s) copied, {asset_unchanged} unchanged"
    )
    return 0
