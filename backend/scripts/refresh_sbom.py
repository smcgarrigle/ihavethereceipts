"""Refresh the version column in SBOM.md from backend/uv.lock.

SBOM.md was maintained by hand and had drifted on 34 of its 48 Python
packages — fastapi said 0.128.0 against 0.141.1, google-genai said 1.60.0
against 2.17.0. The licence and purpose columns are editorial and stay as they
are; only the version is derived, so this rewrites that one field and leaves
every other character of the document alone.

The lock file is the source of truth rather than the installed environment:
that is what a bill of materials should describe, it does not need a synced
venv, and it means this runs in CI on a checkout alone.

Run from backend/:
    uv run python scripts/refresh_sbom.py [--check]

--check exits non-zero without writing, which is what the test uses.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import tomllib

BACKEND = pathlib.Path(__file__).resolve().parent.parent
SBOM = BACKEND.parent / "SBOM.md"
LOCK = BACKEND / "uv.lock"

# | [name](url) | 1.2.3 | MIT | purpose |
ROW = re.compile(r"^(\|\s*\[?)([A-Za-z0-9._-]+)(\]?[^|]*\|\s*)([0-9][^|\s]*)(\s*\|)", re.M)


def locked_versions() -> dict[str, str]:
    """Package name (normalised) -> version, straight from uv.lock."""
    data = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    versions: dict[str, str] = {}
    for package in data.get("package", []):
        name, version = package.get("name"), package.get("version")
        if name and version:
            versions[name.lower().replace("_", "-")] = version
    return versions


def refresh(text: str, versions: dict[str, str] | None = None) -> tuple[str, list[str]]:
    """Return the updated document and a list of what changed."""
    if versions is None:
        versions = locked_versions()
    changes: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name, stated = match.group(2), match.group(4)
        actual = versions.get(name.lower().replace("_", "-"))
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
        print("SBOM.md versions match uv.lock.")
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
