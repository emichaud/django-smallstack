"""The light/dark toggle saves a signed-in user's choice, and first paint reads it.

``theme.js`` saves the toggle to the profile only when ``config.js`` carries
``data-theme-url`` / ``data-palette-url``. Without them it changes this
browser's copy alone, and on the next load the profile's older choice wins, so
the toggle flips back. A downstream theme built from the theming guide had
exactly that, because the guide's setup left the URLs out. These tests hold the
shipped shell, every template that loads ``config.js`` and every documented
base template to the full setup, and check ``theme-init.js``'s order (profile,
then this browser, then dark) by running it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from django.urls import reverse

from apps.smallstack import template_hygiene

REPO = template_hygiene.REPO_ROOT
THEME_INIT = REPO / "apps/smallstack/static/smallstack/js/theme-init.js"

_CONFIG_TAG = re.compile(r"<script\b[^>]*smallstack/js/config\.js[^>]*>", re.S)
_INIT_TAG = re.compile(r"<script\b[^>]*smallstack/js/theme-init\.js[^>]*>", re.S)
_HTML_FENCE = re.compile(r"```html\n(.*?)```", re.S)


def _doc_files() -> list[Path]:
    roots = [REPO / "docs", *(REPO / "apps").glob("*/docs"), REPO / "apps/help/content"]
    return sorted(p for root in roots if root.is_dir() for p in root.rglob("*.md"))


@pytest.mark.django_db
def test_the_shipped_shell_saves_and_paints_the_profile_theme(client, django_user_model):
    user = django_user_model.objects.create_user("lighty", password="x")
    user.profile.theme_preference = "light"
    user.profile.color_palette = "orange"
    user.profile.save()
    client.force_login(user)
    html = client.get(reverse("profile")).content.decode()

    config = _CONFIG_TAG.search(html)
    assert config, "the page loads no config.js"
    assert f'data-theme-url="{reverse("theme_preference")}"' in config.group(0)
    assert f'data-palette-url="{reverse("palette_preference")}"' in config.group(0)

    init = _INIT_TAG.search(html)
    assert init, "the page loads no theme-init.js"
    assert 'data-user-theme="light"' in init.group(0)
    assert 'data-user-palette="orange"' in init.group(0)


def test_every_template_that_loads_config_js_passes_the_save_urls():
    offenders = []
    for path in template_hygiene.project_templates():
        for tag in _CONFIG_TAG.findall(path.read_text(errors="replace")):
            if "data-theme-url=" not in tag or "data-palette-url=" not in tag:
                offenders.append(str(path.relative_to(REPO)))
    assert not offenders, "config.js without data-theme-url / data-palette-url (the toggle won't save):\n" + "\n".join(
        offenders
    )


def test_documented_base_templates_use_the_saving_setup():
    """A base template in the docs gets copied; it must be one that saves."""
    offenders = []
    for path in _doc_files():
        text = path.read_text(errors="replace")
        rel = path.relative_to(REPO)
        if "window.SMALLSTACK = {" in text:
            offenders.append(f"{rel}: an inline window.SMALLSTACK block (the CSP refuses it; use config.js)")
        for block in _HTML_FENCE.findall(text):
            if "<html" not in block or "smallstack/js/theme.js" not in block:
                continue
            config = _CONFIG_TAG.search(block)
            if not config or "data-theme-url=" not in config.group(0) or "data-palette-url=" not in config.group(0):
                offenders.append(f"{rel}: a base template whose config.js lacks the save URLs")
            if not _INIT_TAG.search(block):
                offenders.append(f"{rel}: a base template without theme-init.js")
    assert not offenders, "\n".join(offenders)


_HARNESS = r"""
const fs = require('fs');
const [src, casesJson] = process.argv.slice(1);
const code = fs.readFileSync(src, 'utf8');
const out = [];
for (const c of JSON.parse(casesJson)) {
    const attrs = {};
    const root = { setAttribute: (k, v) => { attrs[k] = v; }, classList: { add() {} } };
    const storage = c.storage === null
        ? { getItem() { throw new Error('blocked'); } }
        : { getItem: (k) => (k in c.storage ? c.storage[k] : null) };
    new Function('document', 'localStorage', code)(
        { documentElement: root, currentScript: { dataset: c.dataset } }, storage);
    out.push([attrs['data-theme'], attrs['data-palette']]);
}
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run theme-init.js")
def test_theme_init_paints_the_profile_choice_first():
    site = {"palette": "purple", "defaultPalette": "django"}
    stored_dark = {"smallstack-theme": "dark", "smallstack-palette": "gold"}
    cases = [
        # (dataset, storage) -> (theme, palette)
        ({**site, "userTheme": "light", "userPalette": "orange"}, stored_dark, ["light", "orange"]),
        ({**site, "userTheme": "light", "userPalette": "orange"}, {}, ["light", "orange"]),
        ({**site, "userTheme": "light"}, None, ["light", "purple"]),
        ({**site, "userTheme": "", "userPalette": ""}, {"smallstack-theme": "light"}, ["light", "purple"]),
        (site, stored_dark, ["dark", "gold"]),
        (site, {}, ["dark", "purple"]),
        ({"defaultPalette": "django"}, None, ["dark", "django"]),
    ]
    payload = [{"dataset": d, "storage": s} for d, s, _ in cases]
    result = subprocess.run(
        ["node", "-e", _HARNESS, str(THEME_INIT), json.dumps(payload)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert json.loads(result.stdout) == [want for _, _, want in cases]
