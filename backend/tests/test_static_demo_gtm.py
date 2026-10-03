"""GTM goes into full pages of the static demo only, once, with a valid ID."""

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "gtm", Path(__file__).resolve().parent.parent / "scripts" / "gtm.py"
)
assert _SPEC and _SPEC.loader
gtm = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gtm)

PAGE = '<!DOCTYPE html><html><head lang="en"><title>x</title></head><body class="a"><p>hi</p></body></html>'
FRAGMENT = '<div id="results"><p>row</p></div>'


def test_tags_pages_and_skips_fragments(tmp_path):
    (tmp_path / "index.html").write_text(PAGE)
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "frag.html").write_text(FRAGMENT)

    assert gtm.inject_gtm(tmp_path, "GTM-ABC123") == 1

    page = (tmp_path / "index.html").read_text()
    assert page.index("gtm.js") < page.index("<title>")  # top of <head>
    assert (
        page.index('<body class="a">') < page.index("ns.html?id=GTM-ABC123") < page.index("<p>hi")
    )
    assert (tmp_path / "items" / "frag.html").read_text() == FRAGMENT


def test_rerun_does_not_double_tag(tmp_path):
    (tmp_path / "index.html").write_text(PAGE)
    gtm.inject_gtm(tmp_path, "GTM-ABC123")
    assert gtm.inject_gtm(tmp_path, "GTM-ABC123") == 0
    assert (tmp_path / "index.html").read_text().count("googletagmanager.com/gtm.js") == 1


@pytest.mark.parametrize("bad", ["G-NDHTFPESMF", "GTM-abc", "GTM-1');alert(1)//"])
def test_rejects_non_container_ids(tmp_path, bad):
    with pytest.raises(ValueError):
        gtm.inject_gtm(tmp_path, bad)
