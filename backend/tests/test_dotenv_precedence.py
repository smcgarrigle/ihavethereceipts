"""An exported DATABASE_URL must win over any .env file the app finds.

app/main.py calls load_dotenv() without a path, which searches upward from
app/ for a .env. From a git worktree under .claude/worktrees/, that search
reaches the main checkout's .env and its live DATABASE_URL. With
override=True that value replaced the temp database that
scripts/build_static_demo.py exports, and the demo seed was written into the
live grocery.db.

The import runs in a subprocess without TESTING (TESTING skips .env loading
entirely, which would hide the bug). The upward search is redirected to a
decoy .env in tmp_path, so no real .env is read and nothing is written to the
repo: SECRET_KEY and DATABASE_URL are both set, so config.py has nothing to
generate.
"""

import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

PROBE = """
import sys
import dotenv.main
dotenv.main.find_dotenv = lambda *a, **k: sys.argv[1]
import app.main  # noqa: F401
from app.database import DATABASE_URL
print(DATABASE_URL)
"""


def test_exported_database_url_beats_found_dotenv(tmp_path):
    exported = f"sqlite:///{tmp_path / 'exported.db'}"
    decoy = tmp_path / ".env"
    decoy.write_text(f"DATABASE_URL=sqlite:///{tmp_path / 'from-dotenv.db'}\n")

    env = {k: v for k, v in os.environ.items() if k != "TESTING"}
    env.update(
        DATABASE_URL=exported,
        SECRET_KEY="dotenv-precedence-test",
        OCR_BACKEND="local",
        FOLDER_WATCH="0",
    )
    result = subprocess.run(
        [sys.executable, "-c", PROBE, str(decoy)],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    resolved = result.stdout.strip().splitlines()[-1]
    assert resolved == exported, f"app used {resolved}, not the exported {exported}"
