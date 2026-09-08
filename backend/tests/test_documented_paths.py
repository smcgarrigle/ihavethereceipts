"""Audit finding 21: documented maintenance commands pointed at missing files.

Four of the five scripts in the cheatsheet's Data Maintenance section had moved
to `backend/scripts/archive/` — the docs still invoked them from
`backend/scripts/`. The cheatsheet also pointed `tail -f` at
`backend/uvicorn_log.txt`, which nothing writes, and `sqlite3` at
`backend/grocery.db`, while the database is at the repository root. README and
CONTRIBUTING told the reader to install libmagic in five places and nothing
imports `magic`.

This walks the markdown for paths it can check and asserts they resolve, which
is the thing that would have caught all of it.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
BACKEND = ROOT / "backend"
DOCS = sorted(ROOT.glob("*.md"))

# `uv run python scripts/foo.py`, run from backend/ per the cheatsheet's preamble.
SCRIPT_INVOCATION = re.compile(r"(?:uv run )?python3? (scripts/[A-Za-z0-9_/-]+\.py)")


def _docs_text() -> list[tuple[pathlib.Path, str]]:
    return [(doc, doc.read_text(encoding="utf-8")) for doc in DOCS]


def test_there_are_docs_to_check():
    assert DOCS, "no markdown found at the repository root"


def test_every_documented_script_exists():
    """The guard for the finding itself."""
    missing: list[str] = []
    for doc, text in _docs_text():
        for match in SCRIPT_INVOCATION.finditer(text):
            relative = match.group(1)
            if not (BACKEND / relative).is_file():
                missing.append(f"{doc.name}: {relative}")
    assert not missing, "documented scripts that do not exist:\n  " + "\n  ".join(missing)


def _shell_blocks(text: str) -> str:
    """Just the ```bash fences — what a reader will actually copy and run.

    Prose is allowed to name a file in order to say it does not exist; a
    command is not.
    """
    return "\n".join(re.findall(r"```(?:bash|sh|shell)\n(.*?)```", text, re.S))


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_no_command_tails_the_phantom_log(doc):
    """`uvicorn_log.txt` is never written by anything in the tree."""
    assert "uvicorn_log.txt" not in _shell_blocks(doc.read_text(encoding="utf-8"))


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_no_command_puts_the_database_under_backend(doc):
    """The live database is `grocery.db` at the repository root."""
    assert "backend/grocery.db" not in _shell_blocks(doc.read_text(encoding="utf-8"))


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_no_doc_asks_for_libmagic(doc):
    """Nothing imports `magic`, so nothing needs the system library."""
    text = doc.read_text(encoding="utf-8")
    assert "libmagic" not in text
    assert "python-magic" not in text


def test_nothing_imports_magic():
    """The premise of the check above, asserted rather than assumed."""
    for path in (BACKEND / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import magic" not in text, f"{path} imports magic after all"
