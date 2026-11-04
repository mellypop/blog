# A Catgirl's Diary

A pastel pink and blue Zensical blog to store my rablings, with golden moonlight
accents.

## Local preview

Use Python **3.11 or newer** (CI uses 3.13).

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
zensical serve
```

Open the address printed by Zensical. For a production-style check:

```sh
zensical build --clean --strict
```

Generated files go to `site/`, which is not committed. Zensical is pinned in
[`requirements.txt`](requirements.txt); update the pin deliberately and repeat
the checks below when upgrading.

## Writing in Obsidian

Choose **Open folder as vault** and select the **repository root**, not `docs/`.
The shared [vault settings](.obsidian/app.json) put new notes in
`docs/blog/posts/2026/`, use relative Markdown links, update links when notes move,
and put attachments in `docs/attachments/`. Appearance follows the system.
Posts are organized under `docs/blog/posts/<year>/` using their publication year.
When starting a new year, create its folder and update Obsidian's
**Default location for new notes** to that year's folder; this setting is not dynamic.

Theme assets, CI configuration, virtual environments, caches, and generated
output are excluded using Obsidian's built-in excluded-files settings.
**Exclusions do not hide folders in the file explorer**: they affect search,
graph, unlinked mentions, and link suggestions. No community plugins are needed.
Personal workspace layouts and trash are gitignored.

Everything under `docs/` is publishable content; Obsidian exclusions are
**not a privacy boundary**. Keep private notes outside this directory.
Give every note in `docs/blog/posts/` a title and creation date before building.
Drafts are visible in local preview but omitted from production builds.

### Add a post

Create `docs/blog/posts/2026/my-little-story.md` (use the publication year):

```markdown
---
date: 2026-11-03
authors:
  - artemis
categories:
  - Little joys
draft: true
---

# My little story

A short introduction for the blog index.

<!-- more -->

The rest of the story goes here.
```

Replace the date with the actual publication date. Remove `draft: true` when
ready. Excerpt separators are required so the index stays readable.
The native blog generates newest-first listings, archives, categories, reading
times, and post navigation. Author details live in
[`docs/blog/.authors.yml`](docs/blog/.authors.yml).

Use ordinary Markdown links to source files, not Obsidian wikilinks:

```markdown
[Another post](small-joys.md)
[Home](../../../index.md)
![My photo](../../../attachments/my-photo.jpg)
```

Links between posts in the same year use just the filename; links to another
year use paths such as `../2027/my-little-story.md`.
Zensical discovers year subdirectories automatically and rewrites source links
for the published site. Published post URLs still come from frontmatter dates
and titles, not source folders, so moving existing posts does not change their URLs.
Obsidian's standard Markdown editor handles the posts. The Home page also uses
HTML wrappers with `markdown` attributes for its card layout; edit the Markdown
inside these wrappers and use Zensical preview to see the final layout.

## Theme

- Configuration, navigation, and appearance selector: [`zensical.toml`](zensical.toml).
- Palette and layouts: [`theme.css`](docs/assets/stylesheets/theme.css).
- Original SVGs, including the favicon: [`docs/assets/images/`](docs/assets/images/).
- Search shortcut markup: [`overrides/partials/search.html`](overrides/partials/search.html).
  The icon and shortcut use real elements rather than pseudo-elements so axe can
  audit text contrast independently, including in Linux WebKit.

## Automated browser checks

The publishing workflow runs [browser checks](tests/browser_checks.py) against the
built site **before uploading the Pages artifact**. A failed check blocks
deployment. Chromium, Firefox, and WebKit each check every generated page except the standalone 404 page
in light/dark mode at 1440, 390, and 320 pixel widths, including archives and
categories. Tests cover overflow, images, JavaScript/asset errors, WCAG A/AA
accessibility and text contrast, system/manual appearance switching and
persistence, theme accents, reduced motion, and keyboard search.
WebKit provides Safari-engine coverage, not testing of the branded Safari
application. All three engines must pass before deployment.

The test server starts and stops automatically and serves the production Pages
subpath from `site_url`. No hardcoded repository name, port, or post dates are
needed. Contrast is also checked with decorative dots removed and each hero
gradient stop isolated; unresolved contrast checks in those passes fail the run.
This does not replace visual review or a complete accessibility audit.

Run the same checks locally after building:

```sh
python -m pip install -r requirements-browser.txt
python -m playwright install chromium firefox webkit
zensical build --clean --strict
python tests/browser_checks.py
```

On Linux, use `python -m playwright install --with-deps chromium firefox webkit`
to install browser system dependencies too. To run just one engine, pass
`--browser chromium`, `--browser firefox`, or `--browser webkit`.
To use an existing Chrome installation instead, pass
`--browser chromium --browser-executable /absolute/path/to/chrome`.

The pinned axe-core 4.11.0 audit library is downloaded from cdnjs to the ignored
`.cache/browser-checks/` directory and verified against a SHA-256 checksum.
The first run needs network access. Local JSON reports and page screenshots
are written in per-engine `chromium/`, `firefox/`, and `webkit/` subdirectories
there. CI uploads them as the **browser-checks** artifact,
including on failure, and retains them for seven days.
