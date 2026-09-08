"""Audit finding 20: two dependencies used but undeclared, five declared but unused.

`requests` and `tenacity` were imported directly but appeared nowhere in
`dependencies`. They resolved only as transitives of `google-genai`, and both
README.md and CONTRIBUTING.md recommend `uv lock --upgrade` as routine
maintenance — so the day that edge moved, nutrition lookups and OCR retries
would have failed at import.

This walks the AST rather than trusting a grep, and resolves each import to the
distribution that actually provides it, so it keeps working when a package's
import name differs from its install name (PIL/pillow, dotenv/python-dotenv).
"""

from __future__ import annotations

import ast
import pathlib
import sys
import tomllib
from importlib.metadata import packages_distributions

BACKEND = pathlib.Path(__file__).resolve().parent.parent
SOURCE_DIRS = (BACKEND / "app", BACKEND / "scripts")

# Provided by the interpreter or the test runner, not by us.
IGNORED_DISTRIBUTIONS = {"pip", "setuptools", "wheel"}


def _normalise(name: str) -> str:
    return name.lower().replace("_", "-")


def _declared() -> set[str]:
    data = tomllib.loads((BACKEND / "pyproject.toml").read_text())
    project = data["project"]
    specs = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        specs.extend(extra)
    names = set()
    for spec in specs:
        name = spec.split(";")[0].strip()
        for separator in (">=", "==", "<=", "~=", ">", "<", "[", "!"):
            name = name.split(separator)[0]
        names.add(_normalise(name.strip()))
    return names


def _top_level_imports() -> dict[str, set[pathlib.Path]]:
    """Top-level module name -> the files that import it."""
    found: dict[str, set[pathlib.Path]] = {}
    for directory in SOURCE_DIRS:
        for path in directory.rglob("*.py"):
            if "archive" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        found.setdefault(alias.name.split(".")[0], set()).add(path)
                elif isinstance(node, ast.ImportFrom):
                    if node.level:  # relative import, ours by definition
                        continue
                    if node.module:
                        found.setdefault(node.module.split(".")[0], set()).add(path)
    return found


def test_every_third_party_import_is_declared():
    """The guard that would have caught requests and tenacity."""
    declared = _declared()
    provided_by = packages_distributions()
    undeclared: list[str] = []

    for module, files in sorted(_top_level_imports().items()):
        if module in sys.stdlib_module_names or module == "app":
            continue
        distributions = provided_by.get(module)
        if not distributions:
            continue  # not installed here (a local module, or an optional path)
        if any(_normalise(d) in declared or d in IGNORED_DISTRIBUTIONS for d in distributions):
            continue
        where = ", ".join(sorted(str(f.relative_to(BACKEND)) for f in files)[:3])
        undeclared.append(f"{module} (from {'/'.join(distributions)}) imported by {where}")

    assert not undeclared, "imported but not declared in pyproject.toml:\n  " + "\n  ".join(
        undeclared
    )


def test_requests_and_tenacity_specifically():
    """Named, because these are the two the audit found."""
    declared = _declared()
    assert "requests" in declared
    assert "tenacity" in declared


def test_the_unused_five_are_gone():
    """Zero import sites anywhere in app/ or scripts/, so nothing declares them.

    Two Postgres drivers in a SQLite-only application is install size and audit
    surface for nothing — SBOM.md already described them as legacy and unused.
    """
    declared = _declared()
    for dropped in ("asyncpg", "psycopg2-binary", "fuzzywuzzy", "python-levenshtein", "aiofiles"):
        assert dropped not in declared, f"{dropped} came back without an import site"


def test_the_dropped_packages_have_no_import_sites():
    """The check that makes the removal safe rather than merely tidy."""
    imports = _top_level_imports()
    for module in ("asyncpg", "psycopg2", "fuzzywuzzy", "Levenshtein", "aiofiles"):
        assert module not in imports, f"{module} is imported but no longer declared"
