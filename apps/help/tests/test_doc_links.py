"""The bundled docs link to help pages at their real address.

Help lives under ``/smallstack/help/``; ``/help/`` alone only redirects to its
index, so ``/help/<page>/`` is a 404. Reads the markdown rather than crawling,
so it holds whatever a project does with its own routes and help settings.
"""

from __future__ import annotations

import re
from pathlib import Path

_APPS = Path(__file__).resolve().parents[2]
_OLD_LINK = re.compile(r"""(?:\]\(|href=["'])/help/""")


def test_bundled_docs_have_no_old_prefix_help_links() -> None:
    docs = [p for pattern in ("*/docs/**/*.md", "*/content/**/*.md") for p in _APPS.glob(pattern)]
    assert docs, "no bundled docs found"
    offenders = [
        f"{path.relative_to(_APPS)}:{number}: {line.strip()[:100]}"
        for path in docs
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if _OLD_LINK.search(line)
    ]
    assert not offenders, "Use /smallstack/help/...:\n" + "\n".join(offenders)
