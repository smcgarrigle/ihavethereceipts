"""TruePriceMemory browser extension core (PR 3/5): build, manifests, and JS unit tests.

Verifies that:
1. ``extension/scripts/build.mjs`` builds both ``dist/chrome`` and ``dist/firefox``
   cleanly from ``extension/src``.
2. Chrome uses Manifest V3 ``background.service_worker`` while Firefox uses
   Manifest V3 ``background.scripts`` + ``browser_specific_settings.gecko.id``.
3. Permissions stay minimal: ``storage``, ``contextMenus``, ``activeTab``, and host
   permissions limited to local loopback and the supported retailers.
4. The Node unit test suite (``extension/tests/common.test.mjs``) passes.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
EXT_DIR = ROOT / "extension"
BUILD_SCRIPT = EXT_DIR / "scripts" / "build.mjs"
CHROME_DIST = EXT_DIR / "dist" / "chrome"
FIREFOX_DIST = EXT_DIR / "dist" / "firefox"


def test_extension_build_script_runs_and_emits_both_targets():
    assert BUILD_SCRIPT.is_file(), "extension/scripts/build.mjs must exist"
    node = shutil.which("node")
    assert node is not None, "node is required to run extension build/tests"

    res = subprocess.run(
        [node, str(BUILD_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr or res.stdout
    assert (CHROME_DIST / "manifest.json").is_file()
    assert (FIREFOX_DIST / "manifest.json").is_file()


def test_chrome_and_firefox_manifests_have_least_privilege_and_valid_backgrounds():
    chrome_manifest = json.loads((CHROME_DIST / "manifest.json").read_text(encoding="utf-8"))
    firefox_manifest = json.loads((FIREFOX_DIST / "manifest.json").read_text(encoding="utf-8"))

    for manifest in (chrome_manifest, firefox_manifest):
        assert manifest["manifest_version"] == 3
        assert "TruePriceMemory" in manifest["name"]
        assert set(manifest["permissions"]) == {"storage", "contextMenus", "activeTab"}
        hosts = manifest["host_permissions"]
        assert "http://127.0.0.1:8000/*" in hosts
        assert "http://localhost:8000/*" in hosts
        assert "<all_urls>" not in hosts
        assert "*://*/*" not in hosts

    assert chrome_manifest["background"] == {
        "service_worker": "background.js",
        "type": "module",
    }
    assert firefox_manifest["background"] == {
        "scripts": ["background.js"],
        "type": "module",
    }
    assert "gecko" in firefox_manifest["browser_specific_settings"]
    assert firefox_manifest["browser_specific_settings"]["gecko"]["id"]

    for manifest in (chrome_manifest, firefox_manifest):
        assert "content_scripts" in manifest
        cs = manifest["content_scripts"][0]
        assert "content/content_script.js" in cs["js"]
        assert "https://*.amazon.com/*" in cs["matches"]
        assert "https://*.safeway.com/*" in cs["matches"]


@pytest.mark.parametrize("target_dir", [CHROME_DIST, FIREFOX_DIST], ids=["chrome", "firefox"])
def test_built_bundle_contains_required_files(target_dir: pathlib.Path):
    required = [
        "manifest.json",
        "background.js",
        "common.js",
        "content/content_script.js",
        "options/options.html",
        "options/options.js",
        "options/options.css",
        "popup/popup.html",
        "popup/popup.js",
        "popup/popup.css",
    ]
    for rel in required:
        assert (target_dir / rel).is_file(), f"missing {rel} in {target_dir.name}"


def test_extension_javascript_unit_tests_pass():
    node = shutil.which("node")
    assert node is not None
    test_files = [
        str(EXT_DIR / "tests" / "common.test.mjs"),
        str(EXT_DIR / "tests" / "extractors.test.mjs"),
    ]
    res = subprocess.run(
        [node, "--test", *test_files],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr or res.stdout
