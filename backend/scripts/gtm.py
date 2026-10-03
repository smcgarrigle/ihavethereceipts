"""Google Tag Manager injection for the static demo.

Kept apart from build_static_demo.py, which rewires the environment on import,
so tests can load this on its own.
"""

from __future__ import annotations

import re
from pathlib import Path

GTM_ID_RE = re.compile(r"^GTM-[A-Z0-9]+$")

HEAD_SNIPPET = """<!-- Google Tag Manager -->
<script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
})(window,document,'script','dataLayer','__GTM_ID__');</script>
<!-- End Google Tag Manager -->
"""

BODY_SNIPPET = """<!-- Google Tag Manager (noscript) -->
<noscript><iframe src="https://www.googletagmanager.com/ns.html?id=__GTM_ID__"
height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>
<!-- End Google Tag Manager (noscript) -->
"""

# Quoted attribute values may contain ">" (Alpine x-data on <body> does), so a
# bare [^>]* would end the tag early and splice the snippet into the attribute.
_ATTRS = r"""(?:\s(?:[^>"']|"[^"]*"|'[^']*')*)?"""
_HEAD_OPEN = re.compile(rf"<head{_ATTRS}>", re.IGNORECASE)
_BODY_OPEN = re.compile(rf"<body{_ATTRS}>", re.IGNORECASE)


def inject_gtm(out: Path, gtm_id: str) -> int:
    """Add the GTM container to every full page under ``out``.

    Only files with both a <head> and a <body> are touched, so htmx fragments
    and JSON snapshots are left alone. Returns the number of pages tagged.
    """
    if not GTM_ID_RE.fullmatch(gtm_id):
        raise ValueError(f"not a GTM container ID: {gtm_id!r}")
    head = HEAD_SNIPPET.replace("__GTM_ID__", gtm_id)
    body = BODY_SNIPPET.replace("__GTM_ID__", gtm_id)
    tagged = 0
    for file in out.rglob("*.html"):
        text = file.read_text(encoding="utf-8")
        if "googletagmanager.com/gtm.js" in text:
            continue
        head_tag = _HEAD_OPEN.search(text)
        body_tag = _BODY_OPEN.search(text)
        if not head_tag or not body_tag:
            continue
        # Body first so the head insertion doesn't shift its offset.
        text = text[: body_tag.end()] + "\n" + body + text[body_tag.end() :]
        text = text[: head_tag.end()] + "\n" + head + text[head_tag.end() :]
        file.write_text(text, encoding="utf-8")
        tagged += 1
    return tagged
