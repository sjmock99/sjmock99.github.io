My personal website - adapted from the following link.
Template URL: https://bootstrapmade.com/style-bootstrap-portfolio-template/

Test with `python3 -m http.server`

Skill Graph (skills.html)
- Data lives in assets/data/skills.json, built from the Notion Engineering Wiki.
- Notion key: ~/.notion_token locally, repo secret NOTION_API on GitHub.
- Edit skills:   python3 scripts/admin.py   then open http://localhost:8001
- Rebuild data:  python3 scripts/sync_notion.py   (SHOW_ALL=true to include non-Public pages)
- .github/workflows/sync-skills.yml rebuilds the data on GitHub every 30 minutes.
