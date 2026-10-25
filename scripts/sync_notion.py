#!/usr/bin/env python3
"""Pull the Notion Engineering Wiki and write assets/data/skills.json for skills.html.

Read-only against Notion. Standard library only, so it runs anywhere Python 3.8+ does.

    python3 scripts/sync_notion.py                 # only Public pages
    SHOW_ALL=true python3 scripts/sync_notion.py   # ignore Public (dev)

The key comes from $NOTION_TOKEN, or else from the file ~/.notion_token.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA_SOURCE_ID = "2878f022-083c-8115-8062-000b4bbbb400"
DATABASE_ID = "2878f022083c8015a0ddde278a3c5e1d"
NOTION_VERSION = "2025-09-03"
API = "https://api.notion.com/v1"

# Discipline hubs: the roots of the tree. They have no Parent skill and are always shown.
HUBS = {
    "4038f022083c81189869f42fa0a06ba6": "Mechanical",
    "4038f022083c8166a9b2fcd4495d12d2": "Electrical",
    "4038f022083c8114a338c414bce9fda6": "Software",
    "4038f022083c816ba41df0761731bca6": "Systems",
    "4038f022083c811fb594ceb95406688b": "Other",
}

OUT = Path(__file__).resolve().parent.parent / "assets" / "data" / "skills.json"
TOKEN_FILE = Path.home() / ".notion_token"


class NotionError(Exception):
    pass


def get_token():
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token and TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text().strip()
    if not token:
        raise NotionError("No Notion key: set NOTION_TOKEN or create ~/.notion_token")
    return token


def request(method, path, body=None):
    token = get_token()
    req = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                time.sleep(0.35)  # stay under Notion's ~3 requests/second
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and attempt < 4:
                time.sleep(float(e.headers.get("Retry-After", 2 ** attempt)))
                continue
            raise NotionError(f"Notion API {e.code} on {path}: {e.read().decode(errors='replace')}")


def query_all():
    pages, cursor = [], None
    while True:
        # Sorting matters: Notion's unsorted query can leave out pages created in the last few minutes.
        body = {"page_size": 100, "sorts": [{"timestamp": "created_time", "direction": "ascending"}]}
        if cursor:
            body["start_cursor"] = cursor
        res = request("POST", f"/data_sources/{DATA_SOURCE_ID}/query", body)
        # The wiki can also return databases nested inside it (e.g. a wish list); keep only pages.
        pages += [r for r in res["results"] if r.get("object") == "page"]
        if not res.get("has_more"):
            return pages + recent_missing(pages)
        cursor = res["next_cursor"]


def recent_missing(pages):
    """Notion's query index can lag several minutes behind new pages, but search sees them at once.
    Return recently edited wiki pages that the query left out."""
    have = {p["id"] for p in pages}
    # Search also returns the wiki's templates (Reference, Project, …); those aren't real pages.
    have |= {t["id"] for t in request("GET", f"/data_sources/{DATA_SOURCE_ID}/templates")["templates"]}
    res = request("POST", "/search", {
        "filter": {"property": "object", "value": "page"},
        "sort": {"timestamp": "last_edited_time", "direction": "descending"},
        "page_size": 100,
    })
    in_wiki = lambda parent: (parent.get("data_source_id") == DATA_SOURCE_ID
                              or (parent.get("database_id") or "").replace("-", "") == DATABASE_ID)
    return [p for p in res["results"]
            if p["id"] not in have and in_wiki(p["parent"]) and not p.get("in_trash") and not p.get("archived")]


def relation_ids(page, name):
    """Relation values are truncated (~25 items) in query results; fetch the full list if so."""
    prop = page["properties"].get(name)
    if not prop:
        return []
    ids = [r["id"] for r in prop.get("relation", [])]
    if prop.get("has_more"):
        ids, cursor = [], None
        while True:
            q = f"?start_cursor={cursor}" if cursor else ""
            res = request("GET", f"/pages/{page['id']}/properties/{prop['id']}{q}")
            ids += [r["relation"]["id"] for r in res["results"]]
            if not res.get("has_more"):
                break
            cursor = res["next_cursor"]
    return [i.replace("-", "") for i in ids]


def to_record(page):
    p = page["properties"]
    title = "".join(t["plain_text"] for t in p.get("Page", {}).get("title", [])).strip()
    return {
        "id": page["id"].replace("-", ""),
        "name": title,
        "url": page.get("url"),
        "types": [o["name"] for o in p.get("Type", {}).get("multi_select", [])],
        "parent": (relation_ids(page, "Parent skill") or [None])[0],
        "rating": p.get("Rating", {}).get("number"),  # None = unrated; never coerce to 0
        "target": p.get("Target", {}).get("number"),
        "public": p.get("Public", {}).get("checkbox", False),
        # Public-facing description shown on the website (a property, separate from the private page body).
        "blurb": "".join(t["plain_text"] for t in p.get("Blurb", {}).get("rich_text", [])).strip(),
        "skills_used": relation_ids(page, "Skills used"),
    }


def is_skill(r):
    """Type contains Reference, or no Type at all but a Parent skill (e.g. a page made with plain + New)."""
    return "Reference" in r["types"] or (not r["types"] and bool(r["parent"]))


def build(records, show_all):
    visible = lambda r: show_all or r["public"]
    candidates = {
        r["id"]: r for r in records
        if is_skill(r) and (r["id"] in HUBS or r["parent"])
    }

    # Keep a skill only if its whole Parent chain reaches a hub through visible pages.
    keep = {}
    def reaches_hub(rid, seen=()):
        if rid in keep:
            return keep[rid]
        r = candidates.get(rid)
        if r is None or rid in seen:
            ok = False
        elif rid in HUBS:
            ok = True
        else:
            ok = visible(r) and reaches_hub(r["parent"], seen + (rid,))
        keep[rid] = ok
        return ok

    skills = [
        {"id": r["id"], "name": r["name"] or HUBS.get(r["id"], "Untitled"),
         "parent": None if r["id"] in HUBS else r["parent"],
         "rating": r["rating"], "target": r["target"], "blurb": r["blurb"]}
        for r in candidates.values() if reaches_hub(r["id"])
    ]
    skill_ids = {s["id"] for s in skills}

    projects = [
        {"id": r["id"], "name": r["name"], "blurb": r["blurb"],
         "skills": [s for s in r["skills_used"] if s in skill_ids]}
        for r in records
        if "Project" in r["types"] and visible(r)
        and not r["name"].lower().startswith("[old - delete]")
    ]
    skills.sort(key=lambda s: s["name"].lower())
    projects.sort(key=lambda p: p["name"].lower())
    return skills, projects


def fetch_records():
    return [to_record(p) for p in query_all()]


def sync(records, show_all):
    """Write skills.json from already-fetched records. Returns a one-line summary."""
    skills, projects = build(records, show_all)

    hubs = sum(1 for s in skills if s["parent"] is None)
    summary = (f"{len(records)} wiki pages -> {hubs} hubs, {len(skills) - hubs} skills, "
               f"{len(projects)} projects (SHOW_ALL={show_all})")
    if hubs != len(HUBS):
        summary += f"\nwarning: expected {len(HUBS)} hubs; check the integration can see every hub page"

    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    if old.get("source") == "notion" and old.get("skills") == skills and old.get("projects") == projects:
        return summary + "\nno changes"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source": "notion",
        "skills": skills,
        "projects": projects,
    }, indent=1, ensure_ascii=False) + "\n")
    return summary + f"\nwrote {OUT}"


def main():
    show_all = os.environ.get("SHOW_ALL", "").lower() == "true"
    try:
        print(sync(fetch_records(), show_all))
    except NotionError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
