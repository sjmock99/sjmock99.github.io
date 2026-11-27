My personal website - adapted from the following link.
Template URL: https://bootstrapmade.com/style-bootstrap-portfolio-template/

Test with `python3 -m http.server`

Skill Graph (skills.html)
- Data lives in assets/data/skills.json, built from the Notion Engineering Wiki.
- Notion key: ~/.notion_token locally, repo secret NOTION_API on GitHub.
- Edit skills:   python3 scripts/admin.py   then open http://localhost:8001
- Rebuild data:  python3 scripts/sync_notion.py   (SHOW_ALL=true to include non-Public pages)
- .github/workflows/sync-skills.yml rebuilds the data on GitHub every 30 minutes.

Projects (projects/*.html, the homepage grid)
- Also built from the wiki: pages with Type = Project and Public ticked. How to add one: .claude/skills/add-project/SKILL.md
- Preview drafts:   PREVIEW=true python3 scripts/sync_notion.py   (writes .preview/ only)
- Helpers:
    scripts/upload_to_notion.py   put photos / a PDF on a project's Notion page; set photo captions and links
    scripts/make_cover.py         wide cover from a portrait photo (no cropping)
    scripts/shrink_pdf.py         PDF under Notion's 5 MB upload limit (pip install --user pymupdf)
    scripts/export_site_images.py download every image from a website, full size
