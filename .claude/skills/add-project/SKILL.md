---
name: add-project
description: Add a project to the portfolio site, or improve one already there — gather its sources (decks, repos, Drive, photos, videos, Instagram), write its Notion page, put photos/PDFs/videos on it, preview, and publish. Use when the user wants to add, update, fill in or fix a project page, its photos, cover, PDF or videos.
---

# Add or update a project page

The site is built from the Notion **Engineering Wiki**: `scripts/sync_notion.py` turns each wiki page with Type =
Project and **Public** ticked into a card on the homepage and a page at `projects/<slug>.html`. A GitHub Action runs
the sync every 30 minutes (or by hand: Actions → "Sync skills from Notion" → Run workflow) and commits what it
generated. **So the work happens in Notion, not in the HTML.** Never hand-edit generated files (the
`notion:*` regions of `index.html`, `projects/*.html`, `assets/data/skills.json`, `assets/img/projects/`,
`assets/docs/projects/`); the next sync overwrites them, and the sync deletes any file in those asset folders that no
Notion page uses.

This repo is **public**. Nothing secret goes in it or on a project page: no keys or tokens (the Notion key lives in
`~/.notion_token` locally and the `NOTION_API` repo secret on GitHub), no links to private repos or private Drive
files (visitors get a 404 or "request access").

## 1. Gather and read the sources

Ask for, or find: the existing wiki page (search the wiki before creating one), slides/PDF deck, GitHub repos, Drive
folder, product or project website, YouTube / Instagram links, photos, and **what the user personally did**. Read
them: the deck and the code are where the real facts are.

- Check each link is public (`gh repo view --json isPrivate`, Drive permissions, `curl -o /dev/null -w "%{http_code}"`).
  Private ones go only in the page's private part below the 🌐 Public section.
- Before a repo goes public, scan its **whole history** for secrets, not just the current files. If any are found,
  the user revokes them first; then move them to environment variables, and if wanted strip them from history with
  `git filter-repo --replace-text` (keeps every commit) and force-push. Delete merged branches that still carry them.
- Facts conflict? Believe the newest primary source and say so (e.g. a page that said "being sold" while the product
  site said "waitlist"; an old blurb that said ESP32 when the slides said Teensy).

## 2. The Notion page

Properties: **Page** (title), **Type** = Project, **Blurb** (one sentence; the card text and the page's lede),
**Date** (start, and end if it's over), **Link** (the main button: GitHub shows "Code on GitHub", YouTube "Watch
the video", anything else "Visit the link"), **Organization** (optional, shown next to the date), **Skills used**
(relations to skill pages in the same wiki), **Interests** (relations to the Interest pages: the chips in the
homepage's Interests section and on the project page; jobs can be tagged too), **Featured**, **Public** (leave
unticked for the user to tick), and **Needs review** (tick it on anything Claude wrote).

Interest pages themselves are wiki pages with Type = Interest, a Blurb (the panel's text), **Site icon** (a
Bootstrap icon name such as `bi-rocket-takeoff`) and Public ticked. Their chips keep the order the pages were made
in; an interest with nothing tagged still shows.

Body, from the wiki's Project template:

```
📌 callout: private one-line summary
🌐 Public            ← toggle heading: everything inside is published
   ### What it is    ← 1–3 sentences: what it is, why it exists
   ### What I did    ← bullets: the user's own part, concrete (tools, decisions, numbers)
   ### Result        ← bullets: outcome, numbers, links (site, repo, Instagram)
   ### Documentation ← PDFs go here
   📷 Photos         ← toggle: the gallery; its first photo is the cover
🎯 Goal / 📋 Status / 🔧 Build notes / 🔗 Links   ← private notes, never published
```

Lines wholly in (brackets) are template hints and are never published; empty sub-headings are dropped.

**Writing**: short and plain, first person, past tense for finished work. Only claim what the sources or the user
say. Flag anything guessed (dates especially) in your reply. Keep the user's own edits; re-read the page before
changing it, because they often edit it in between.

## 3. Media: how each kind shows on the site

| In Notion | On the site |
|---|---|
| First photo in 📷 Photos (or the page cover) | Card image and page banner; not repeated in the grid |
| Other photos in 📷 Photos | Square grid tiles; click opens the lightbox with the caption |
| A link in a photo's caption | That tile opens the link in a new tab, with a small badge (Instagram icon for Instagram) |
| Photo in the text of 🌐 Public | Full width, uncropped, caption underneath. Use for labelled/annotated images and wide screenshots |
| YouTube / Vimeo embed | In the text: a player. In 📷 Photos: its thumbnail; plays in the lightbox |
| Instagram post / reel embed | Its preview image with an Instagram icon, opening the post. Instagram won't let videos play on other sites; put videos on YouTube for real playback |
| Uploaded video file (≤ 20 MB) | Copied in; plays on the page; loops silently in the grid |
| PDF (or a .pdf file block) | Where it sits: title bar with Open / Download over a viewer (bar only on phones); a "Documentation" button in the header; ≤ 15 MB |
| Google Sheet link (embed / bookmark), shared "anyone with the link can view" | A live, view-only viewer like the PDF one, with Open and Make a copy. Consecutive links to the same sheet become one viewer with a tab each; the link's `#gid=` picks the tab, a caption "Title: Tab" names both. Wide spreadsheet screenshots in the 📷 Photos grid show whole instead of cropped |

Good habits:

- **Cover**: the banner is about 2:1 and at most 520 px tall, and the card is 16:10, so a portrait photo loses its top
  and bottom. Make a wide version: `python3 scripts/make_cover.py photo.jpg cover.jpg` (blurred sides) or
  `--fill backdrop` for a plain studio backdrop. Look at the result before uploading.
- **Gallery**: 6–15 varied photos beat 40 near-duplicates. Product shots, the build/behind the scenes, one or two
  examples of social posts if social media was part of the work. Link the rest via the Instagram/website.
- **Wide screenshots** (spreadsheets, dashboards): crop away empty rows; put them in the text, not the grid, where
  squares would show only a strip.
- **Small images** (under ~800 px): fine in the grid; for a cover, use make_cover so it isn't stretched.

## 4. Getting files onto the page

Notion on this plan refuses uploads over **5 MB**.

```bash
python3 scripts/upload_to_notion.py photos <page> cover.jpg a.png "b.jpg=Caption"   # shrinks big photos itself
python3 scripts/upload_to_notion.py pdf <page> deck.pdf --caption "Slides: …"        # after the Documentation heading
python3 scripts/upload_to_notion.py caption <page> Frame_46 "Meet the team" --link https://www.instagram.com/p/…/
python3 scripts/shrink_pdf.py deck.pdf "deck web.pdf"        # a PDF over 5 MB (needs: pip install --user pymupdf)
python3 -I scripts/export_site_images.py https://site.example ~/code/<project>/photos   # every image on a site
```

Text and properties go through the Notion connector (fetch the page first, then make small `update_content` edits).

## 5. Preview, then publish

```bash
PREVIEW=true python3 scripts/sync_notion.py    # drafts too; writes only .preview/ (git-ignored)
```

Check `.preview/projects/<slug>.html`: the kicker (date), the main button, how many tiles, players and PDFs, and the
sync's summary ("no photos yet", "couldn't get these photos"). The slug comes from the title, so renaming a project
changes its URL. To see it in a browser, `python3 scripts/admin.py` serves the preview at
http://localhost:8001/preview/.

Content changes need no commit: once the user ticks **Public**, the next sync publishes them. Changes to the code
(`scripts/`, `assets/css`, `assets/js`) go on a branch and a pull request; when a CSS or JS file changes, bump its
`?v=` in `index.html` so browsers fetch the new one. After merging, run the sync once so the pages are rebuilt.

## Known gotchas

- **Creating a wiki page through the Notion connector with a data-source parent drops all its properties** (title
  included): in a wiki the connector wants the wiki page itself as the parent. Simplest is the REST API through
  `sync_notion.request("POST", "/pages", {"parent": {"type": "data_source_id", "data_source_id": DATA_SOURCE_ID},
  ...})`, which keeps properties. Either way, check them afterwards with `sync_notion.to_record`.
- Changing a select / multi-select option list (e.g. adding a Type) replaces the whole list: fetch the data source
  first and list every existing option with its colour, or the missing ones are deleted.
- **The connector's markdown can't target image blocks** (an image line won't match as `old_str` or an anchor). To
  change an image's caption or link use `scripts/upload_to_notion.py caption`; to move an image, anchor on the
  caption text next to it. After any move, check the image still exists.
- Notion's query can lag a few minutes behind new pages; the sync also searches recent edits to catch them.
- A page opened as a side peek may hide properties; "N more properties" or Open as page shows them all.
- GitHub Actions may fail to fetch Instagram thumbnails now and then; the tile still links, and the sync retries.
