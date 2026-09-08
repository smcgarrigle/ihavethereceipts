"""Refresh the version column in SBOM.md from what is actually installed.

SBOM.md was maintained by hand and had drifted on 34 of its 48 Python
packages — fastapi said 0.128.0 against 0.141.1 installed, google-genai said
1.60.0 against 2.17.0. The licence and purpose columns are editorial and stay
as they are; only the version is derived, so this rewrites that one field and
leaves every other character of the document alone.

Run from backend/:
    uv run python scripts/refresh_sbom.py [--check]

--check exits non-zero without writing, which is what the test uses.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from importlib.metadata import PackageNotFoundError, version

SBOM = pathlib.Path(__file__).resolve().parent.parent.parent / "SBOM.md"

# | [name](url) | 1.2.3 | MIT | purpose |
ROW = re.compile(r"^(\|\s*\[?)([A-Za-z0-9._-]+)(\]?[^|]*\|\s*)([0-9][^|\s]*)(\s*\|)", re.M)


def installed(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def refresh(text: str) -> tuple[str, list[str]]:
    """Return the updated document and a list of what changed."""
    changes: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name, stated = match.group(2), match.group(4)
        actual = installed(name)
        if actual is None or actual == stated:
            return match.group(0)
        changes.append(f"{name}: {stated} -> {actual}")
        return f"{match.group(1)}{name}{match.group(3)}{actual}{match.group(5)}"

    return ROW.sub(replace, text), changes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="report drift without writing")
    args = parser.parse_args()

    original = SBOM.read_text(encoding="utf-8")
    updated, changes = refresh(original)

    if not changes:
        print("SBOM.md versions match the installed packages.")
        return 0

    for change in changes:
        print(f"  {change}")
    if args.check:
        print(f"\n{len(changes)} package(s) drifted. Run: uv run python scripts/refresh_sbom.py")
        return 1

    SBOM.write_text(updated, encoding="utf-8")
    print(f"\nUpdated {len(changes)} version(s) in SBOM.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
