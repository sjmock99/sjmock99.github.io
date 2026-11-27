# sjmock99.github.io

Personal portfolio site (GitHub Pages, plain HTML/CSS/JS from a Bootstrap template). Most content is generated from
the owner's Notion **Engineering Wiki** by `scripts/sync_notion.py`: skills, experience, the homepage project grid and
one page per project in `projects/`. A GitHub Action (`.github/workflows/sync-skills.yml`) runs it every 30 minutes
and commits the result.

- **Adding or changing a project**: use the `add-project` skill (`.claude/skills/add-project/SKILL.md`). Content is
  edited in Notion, not in the HTML.
- **Generated, never edit by hand**: the `<!-- notion:… -->` regions of `index.html`, `projects/*.html`,
  `assets/data/skills.json`, `assets/img/projects/`, `assets/img/logos/`, `assets/docs/projects/`. The sync
  overwrites them and deletes unused files in those folders. Don't commit locally generated copies either; let the
  Action produce them.
- **Preview without touching the site**: `PREVIEW=true python3 scripts/sync_notion.py` writes to `.preview/`
  (git-ignored); `python3 scripts/admin.py` serves it at http://localhost:8001.
- **This repo is public.** No secrets in it. The Notion key is `~/.notion_token` locally and the `NOTION_API` repo
  secret on GitHub; scripts read it, nothing stores it.
- **Code changes** go on a branch and a pull request. When a CSS/JS file changes, bump its `?v=` in `index.html`
  (project pages copy their `<head>` and scripts from it).
- Python: standard library plus Pillow (`requirements.txt`, also used by the Action). `scripts/shrink_pdf.py` alone
  needs PyMuPDF, installed locally only.
