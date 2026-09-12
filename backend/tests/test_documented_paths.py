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


# ── The consistency pass, 2026-09-12 ────────────────────────────────────────
# Finding 21 fixed paths. These cover the other way a documented command goes
# wrong: it resolves fine and does something other than what the prose says.

MAKEFILE = ROOT / "Makefile"
# `make run`, `make run PORT=8001` — the target, and any variable overrides.
MAKE_INVOCATION = re.compile(r"\bmake ([a-z][a-z-]*)((?: +[A-Z_]+=\S+)*)")


def _command_text(doc: pathlib.Path) -> str:
    """Shell blocks plus inline code spans — never prose, which says "make sure"."""
    text = doc.read_text(encoding="utf-8")
    return "\n".join([_shell_blocks(text), *re.findall(r"`([^`\n]+)`", text)])


def _make_targets() -> set[str]:
    return set(re.findall(r"^([a-z][a-z-]*):", MAKEFILE.read_text(encoding="utf-8"), re.M))


def _make_variables() -> set[str]:
    return set(re.findall(r"^([A-Z_]+) *\??=", MAKEFILE.read_text(encoding="utf-8"), re.M))


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_every_documented_make_target_exists(doc):
    targets = _make_targets()
    missing = {
        target for target, _ in MAKE_INVOCATION.findall(_command_text(doc)) if target not in targets
    }
    assert not missing, f"{doc.name} invokes make targets that do not exist: {sorted(missing)}"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_every_documented_make_override_is_a_real_variable(doc):
    """README told the reader to change the port with `--port 8001` in `make run`.

    The recipe hardcoded 8000 and took no PORT, so the instruction did nothing —
    `make run --port 8001` is parsed as make's own flags. The Makefile now has a
    PORT knob; this is the guard that a documented override names a real one.
    """
    variables = _make_variables()
    unknown = {
        assignment.split("=")[0].strip()
        for _, overrides in MAKE_INVOCATION.findall(_command_text(doc))
        for assignment in overrides.split()
        if assignment.split("=")[0].strip() not in variables
    }
    assert not unknown, f"{doc.name} overrides make variables that do not exist: {sorted(unknown)}"


def test_make_help_lists_every_target():
    """`make help` is where the targets are described, so it has to be complete."""
    text = MAKEFILE.read_text(encoding="utf-8")
    described = set(re.findall(r"make ([a-z][a-z-]*) +—", text))
    assert _make_targets() - {"help"} == described


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_no_doc_recommends_a_relative_database_url(doc):
    """GEMINI.md said DATABASE_URL should be `sqlite:///./grocery.db`.

    A relative sqlite URL resolves against the caller's working directory, so a
    script run from `backend/` silently creates an empty stray database instead
    of opening the real one — which is why `app/core/config.py` writes an
    absolute path when the variable is missing.
    """
    text = doc.read_text(encoding="utf-8")
    assert "sqlite:///./" not in text, f"{doc.name} recommends a relative DATABASE_URL"


def test_config_still_writes_an_absolute_database_url():
    """The premise of the check above, asserted rather than assumed."""
    config = (BACKEND / "app" / "core" / "config.py").read_text(encoding="utf-8")
    assert "DATABASE_URL=sqlite:///{BASE_DIR / 'grocery.db'}" in config


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_no_doc_says_make_lint_formats(doc):
    """README and CONTRIBUTING annotated it `# ruff check + format`.

    `make lint` runs `ruff format --check`, which reports and changes nothing;
    `make format` is the one that writes. `make help` had it right — the prose
    in two other files had drifted, which is the whole shape of this pass.
    """
    for line in doc.read_text(encoding="utf-8").splitlines():
        if not re.search(r"\bmake lint\b.*#", line):
            continue
        comment = line.split("#", 1)[1]
        if "format" in comment:
            assert "format check" in comment, (
                f"{doc.name} says `make lint` formats: {line.strip()!r} — it only checks"
            )
