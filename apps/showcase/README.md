# showcase — SmallStack's demo pages

The pages that show what SmallStack does on a running site: about, getting started, prompts, the
datasets-and-calendars and blogs-and-newsletters platform pages, the starter pages
(`/starter/`, `/starter/basic/`, `/starter/forms/`, `/starter/dashboard/`), `/components/` and the
public search page at `/search/`.

**Status:** **Upstream's, and deletable.** Don't build your pages here: put them in `apps/website/`
(or an app of your own). Upstream changes this app freely, and a project that keeps it takes
upstream's version on a merge.

**To delete it**, remove three things:

1. the `apps/showcase/` directory,
2. `"apps.showcase"` in `INSTALLED_APPS` (`config/settings/base.py`),
3. `path("", include("apps.showcase.urls"))` in `config/urls.py`.

Nothing outside the app links to it unguarded: the public topbar (`templates/website/base.html`)
and the home page reverse its URLs with `{% url 'showcase:…' as x %}{% if x %}`, so those links
disappear with it. The starter markup worth copying into your own pages is
`templates/showcase/includes/starter_content.html`.
