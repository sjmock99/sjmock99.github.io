#!/usr/bin/env python3
"""Pull the Notion Engineering Wiki and write assets/data/skills.json (skills, projects, experience) for the site.

Read-only against Notion. Standard library only, so it runs anywhere Python 3.8+ does.

    python3 scripts/sync_notion.py                 # only Public pages
    SHOW_ALL=true python3 scripts/sync_notion.py   # ignore Public (dev)

The key comes from $NOTION_TOKEN, or else from the file ~/.notion_token.
"""
import html
import json
import os
import re
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
        except (urllib.error.URLError, TimeoutError) as e:  # network blip: retry, then give a clean error
            if attempt < 4:
                time.sleep(2 ** attempt)
                continue
            raise NotionError(f"Couldn't reach Notion ({getattr(e, 'reason', e)})")


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


def plain(p, name):
    return "".join(t["plain_text"] for t in p.get(name, {}).get("rich_text", [])).strip()


def to_record(page):
    p = page["properties"]
    title = "".join(t["plain_text"] for t in p.get("Page", {}).get("title", [])).strip()
    date = p.get("Date", {}).get("date") or {}
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
        "blurb": plain(p, "Blurb"),
        "skills_used": relation_ids(page, "Skills used"),
        # Projects / Experience / Education
        "role": plain(p, "Role"),
        "organization": plain(p, "Organization"),
        "location": plain(p, "Location"),
        "link": p.get("Link", {}).get("url"),
        "start": date.get("start"),
        "end": date.get("end"),
    }


# ---- 🌐 Public section: the part of a page body that's shown on the website ----
# A heading containing "🌐 Public" (everything after it, up to the next heading of the same or a higher level),
# or a toggle / toggle heading with that title (everything inside it). The rest of the page stays private.

def block_children(block_id):
    out, cursor = [], None
    while True:
        q = f"?page_size=100&start_cursor={cursor}" if cursor else "?page_size=100"
        res = request("GET", f"/blocks/{block_id}/children{q}")
        out += res["results"]
        if not res.get("has_more"):
            return out
        cursor = res["next_cursor"]


def block_text(b):
    return "".join(t["plain_text"] for t in b.get(b["type"], {}).get("rich_text", []))


def is_public_marker(b):
    return b["type"] in ("heading_1", "heading_2", "heading_3", "toggle") and re.search(r"🌐\s*public", block_text(b), re.I)


def rich_html(rich):
    out = []
    for t in rich:
        s, a = html.escape(t["plain_text"]), t.get("annotations", {})
        if a.get("code"): s = f"<code>{s}</code>"
        if a.get("bold"): s = f"<b>{s}</b>"
        if a.get("italic"): s = f"<i>{s}</i>"
        if a.get("strikethrough"): s = f"<s>{s}</s>"
        href = t.get("href") or ""
        if href.startswith(("http://", "https://")):
            s = f'<a href="{html.escape(href)}" target="_blank" rel="noopener">{s}</a>'
        out.append(s)
    return "".join(out)


def blocks_html(blocks):
    """Notion blocks -> a small, safe subset of HTML (paragraphs, lists, sub-headings, quotes, dividers)."""
    out, i = [], 0
    while i < len(blocks):
        b, kind = blocks[i], blocks[i]["type"]
        if kind in ("bulleted_list_item", "numbered_list_item"):
            tag, items = "ul" if kind == "bulleted_list_item" else "ol", []
            while i < len(blocks) and blocks[i]["type"] == kind:
                li = blocks[i]
                sub = blocks_html(block_children(li["id"])) if li.get("has_children") else ""
                items.append(f"<li>{rich_html(li[kind]['rich_text'])}{sub}</li>")
                i += 1
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue
        body = rich_html(b.get(kind, {}).get("rich_text", []))
        if kind == "paragraph" and body:
            out.append(f"<p>{body}</p>")
        elif kind.startswith("heading_"):
            out.append(f"<h5>{body}</h5>")
        elif kind == "quote":
            out.append(f"<blockquote>{body}</blockquote>")
        elif kind == "divider":
            out.append("<hr>")
        elif kind == "toggle":
            out.append(f"<p><b>{body}</b></p>")
        if kind in ("toggle", "quote", "paragraph") and b.get("has_children"):
            out.append(blocks_html(block_children(b["id"])))
        i += 1
    return "".join(out)


def public_html(page_id):
    """HTML for the page's 🌐 Public section, or None if it has none."""
    blocks = block_children(page_id)
    for i, b in enumerate(blocks):
        if not is_public_marker(b):
            continue
        if b["type"] == "toggle" or b[b["type"]].get("is_toggleable"):
            return blocks_html(block_children(b["id"])) if b.get("has_children") else ""
        level, section = int(b["type"][-1]), []
        for nb in blocks[i + 1:]:
            if nb["type"].startswith("heading_") and int(nb["type"][-1]) <= level:
                break
            section.append(nb)
        return blocks_html(section)
    return None


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

    def item(r, **extra):
        return {"id": r["id"], "name": r["name"], "blurb": r["blurb"], "organization": r["organization"],
                "start": r["start"], "end": r["end"], **extra,
                "skills": [s for s in r["skills_used"] if s in skill_ids]}
    projects = [
        item(r, link=r["link"])
        for r in records
        if "Project" in r["types"] and visible(r)
        and not r["name"].lower().startswith("[old - delete]")
    ]
    # Jobs and degrees. No end date on a job means it's current.
    experience = [
        item(r, kind="education" if "Education" in r["types"] else "work", role=r["role"], location=r["location"])
        for r in records
        if ("Experience" in r["types"] or "Education" in r["types"]) and visible(r)
    ]
    skills.sort(key=lambda s: s["name"].lower())
    projects.sort(key=lambda p: p["name"].lower())
    experience.sort(key=lambda e: e["start"] or "", reverse=True)
    return skills, projects, experience


# ---- Homepage resume + skills preview: written into index.html between <!-- notion:<name>:start ... --> and <!-- notion:<name>:end --> ----

INDEX = OUT.parent.parent.parent / "index.html"
HUB_KEYS = {"Mechanical": "mech", "Electrical": "elec", "Software": "soft", "Systems": "sys", "Other": "oth"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MAX_CHIPS = 12  # more than this and the card links to the graph for the rest


def date_range(it):
    """Same format as skill-graph.js: "Sep 2024 - Sep 2025", "Feb 2026 - Present"; degrees show years only."""
    if not it["start"]:
        return ""
    f = (lambda d: d[:4]) if it["kind"] == "education" else (lambda d: f"{MONTHS[int(d[5:7]) - 1]} {d[:4]}")
    end = f(it["end"]) if it["end"] else ("Present" if it["kind"] == "work" else "")
    return f"{f(it['start'])} - {end}" if end and end != f(it["start"]) else f(it["start"])


def top_level_class(h, cls):
    """Add class="cls" to the outermost <ul>/<ol> tags of a details fragment (nested lists keep their own look)."""
    out, depth, pos = [], 0, 0
    for m in re.finditer(r"<(/?)(ul|ol)>", h):
        out.append(h[pos:m.start()])
        if m.group(1):
            depth -= 1
            out.append(m.group(0))
        else:
            out.append(f'<{m.group(2)} class="{cls}">' if depth == 0 else m.group(0))
            depth += 1
        pos = m.end()
    return "".join(out) + h[pos:]


def skill_chips(it, skills):
    by_id = {s["id"]: s for s in skills}
    def disc(s):
        seen = set()
        while s["parent"] and s["parent"] in by_id and s["id"] not in seen:
            seen.add(s["id"])
            s = by_id[s["parent"]]
        return HUB_KEYS.get(s["name"], "oth")
    used = sorted((by_id[i] for i in it["skills"] if i in by_id),
                  key=lambda s: (-(s["rating"] or 0), s["name"].lower()))
    if not used:
        return ""
    e = html.escape
    def chip(s):
        title = f"{s['name']} · Lv {s['rating']:g}" if s["rating"] else s["name"]
        return (f'<a class="rs-chip" href="skills.html#skill={s["id"]}" title="{e(title)}">'
                f'<span class="rs-dot rs-{disc(s)}"></span>{e(s["name"])}</a>')
    chips = "".join(chip(s) for s in used[:MAX_CHIPS])
    more = f"+{len(used) - MAX_CHIPS} more in the skill graph" if len(used) > MAX_CHIPS else "See these in the skill graph"
    return (f'<div class="rs-skills">{chips}</div>'
            f'<a class="rs-more" href="skills.html#item={it["id"]}">{more} →</a>')


def experience_html(items, skills):
    e, out = html.escape, []
    for n, it in enumerate(i for i in items if i["kind"] == "work"):
        org = ": ".join(x for x in (it["organization"], it["location"]) if x) or it["name"]
        out.append(f"""
                <div class="experience-card" data-aos="zoom-in" data-aos-delay="{max(300, 500 - n * 100)}">
                  <div class="card-header">
                    <div class="role-info">
                      <h3>{e(it["role"] or it["name"])}</h3>
                      <h4>{e(org)}</h4>
                    </div>
                    <span class="duration">{e(date_range(it))}</span>
                  </div>
                  <div class="card-body">
                    {f"<p>{e(it['blurb'])}</p>" if it["blurb"] else ""}
                    {top_level_class(it.get("details") or "", "achievements")}
                    {skill_chips(it, skills)}
                  </div>
                </div>""")
    return "".join(out)


def education_html(items, skills):
    e, out = html.escape, []
    edu = [i for i in items if i["kind"] == "education"]
    for n, it in enumerate(edu):
        school = f'{it["organization"]} ({it["location"]})' if it["location"] else it["organization"]
        out.append(f"""
                <div class="education-item" data-aos="slide-up" data-aos-delay="{400 - n * 100 if n < 3 else 200}">
                  <div class="timeline-marker"></div>
                  <div class="education-content">
                    <div class="degree-header">
                      <h3>{e(it["role"] or it["name"])}</h3>
                      <span class="year">{e(date_range(it))}</span>
                    </div>
                    <h4 class="institution">{e(school)}</h4>
                    {f"<p>{e(it['blurb'])}</p>" if it["blurb"] else ""}
                    {top_level_class(it.get("details") or "", "edu-details")}
                    {skill_chips(it, skills)}
                  </div>
                </div>""")
    return "".join(out)


BANDS = ["Lv 4–5", "Lv 3", "Lv 2", "Lv 1", "Not rated"]
SHADE = [100, 68, 42, 20]  # % of the discipline color per band: darker = stronger (same as skill-graph.js)


def band(r):
    return 4 if r is None else 0 if r >= 4 else 1 if r >= 3 else 2 if r >= 2 else 3


def skills_html(skills, projects, experience):
    """Homepage Skills section: counts, each discipline's skills by level band, strongest skills, link to the graph.
    Counts only, never averages, so adding a new Lv 1 skill shows as breadth rather than lowering a score."""
    e, by_id = html.escape, {s["id"]: s for s in skills}
    def hub_of(s):
        seen = set()
        while s["parent"] and s["parent"] in by_id and s["id"] not in seen:
            seen.add(s["id"])
            s = by_id[s["parent"]]
        return s
    tree = [s for s in skills if s["parent"]]  # everything but the hubs, like the graph's counts
    mixes = []
    for hub in (s for s in skills if not s["parent"]):
        c = [0] * 5
        for s in tree:
            if hub_of(s) is hub:
                c[band(s["rating"])] += 1
        if sum(c):
            mixes.append((hub, HUB_KEYS.get(hub["name"], "oth"), c))
    mixes.sort(key=lambda m: (-m[2][0], -sum(m[2])))
    widest = max((sum(c) for _, _, c in mixes), default=1)
    def bar(key, c):
        segs = "".join(
            f'<i class="sk-none rs-b-{key}" style="flex:{k}" title="{BANDS[i]}: {k}"></i>' if i == 4 else
            f'<i style="flex:{k};background:color-mix(in srgb, var(--rs-{key}) {SHADE[i]}%, var(--surface-color))" title="{BANDS[i]}: {k}"></i>'
            for i, k in enumerate(c) if k)
        return f'<span class="sk-mix" style="width:{sum(c) / widest * 100:.0f}%">{segs}</span>'
    rows = "".join(f'''<a class="sk-disc" href="skills.html#disc={key}" title="{e(hub["name"])}: {e(", ".join(f"{k} at {BANDS[i]}" for i, k in enumerate(c) if k))}">
                <span class="sk-name"><span class="rs-dot rs-{key}"></span>{e(hub["name"])}</span>
                <span class="sk-track">{bar(key, c)}</span>
                <span class="sk-val">{sum(c)}</span></a>''' for hub, key, c in mixes)
    legend = "".join(
        f'<span><i class="sk-none"></i>{b}</span>' if i == 4 else
        f'<span><i style="background:color-mix(in srgb, var(--heading-color) {SHADE[i]}%, var(--surface-color))"></i>{b}</span>'
        for i, b in enumerate(BANDS))
    top = sorted((s for s in tree if s["rating"]), key=lambda s: (-s["rating"], s["name"].lower()))[:12]
    chips = "".join(
        f'<a class="rs-chip" href="skills.html#skill={s["id"]}"><span class="rs-dot rs-{HUB_KEYS.get(hub_of(s)["name"], "oth")}"></span>'
        f'{e(s["name"])}<span class="sk-lv">{s["rating"]:g}</span></a>' for s in top)
    jobs = sum(1 for x in experience if x["kind"] == "work")
    return f"""
      <div class="container" data-aos="fade-up" data-aos-delay="100">
        <div class="sk-preview">
          <div class="sk-stats">
            <div><b>{len(tree)}</b>skills</div>
            <div><b>{len(mixes)}</b>disciplines</div>
            <div><b>{jobs}</b>jobs</div>
            <div><b>{len(projects)}</b>projects</div>
          </div>
          <div class="sk-cols">
            <div>
              <h3>Skills by discipline and level</h3>
              {rows}
              <p class="sk-legend" aria-hidden="true">{legend}</p>
            </div>
            <div>
              <h3>Strongest skills</h3>
              <div class="rs-skills">{chips}</div>
            </div>
          </div>
          <a class="sk-cta" href="skills.html">Explore the full skill graph <i class="bi bi-arrow-right"></i></a>
        </div>
      </div>"""


def write_index(skills, projects, experience):
    """Fill the generated regions of index.html. Returns True if the file changed."""
    if not INDEX.exists():
        return False
    page = old = INDEX.read_text(encoding="utf-8")
    for name, body in (("experience", experience_html(experience, skills)),
                       ("education", education_html(experience, skills)),
                       ("skills", skills_html(skills, projects, experience))):
        pat = re.compile(rf"(<!-- notion:{name}:start[^>]*-->).*?(\n[ \t]*<!-- notion:{name}:end -->)", re.S)
        page = pat.sub(lambda m: m.group(1) + body + m.group(2), page, count=1)
    if page != old:
        INDEX.write_text(page, encoding="utf-8")
    return page != old


def fetch_records():
    return [to_record(p) for p in query_all()]


def sync(records, show_all):
    """Write skills.json from already-fetched records. Returns a one-line summary."""
    skills, projects, experience = build(records, show_all)
    # The detailed write-up for each project / job comes from its page body (the 🌐 Public section).
    missing = []
    for it in projects + experience:
        it["details"] = public_html(it["id"])
        if it["details"] is None:
            missing.append(it["name"])

    hubs = sum(1 for s in skills if s["parent"] is None)
    summary = (f"{len(records)} wiki pages -> {hubs} hubs, {len(skills) - hubs} skills, "
               f"{len(projects)} projects, {len(experience)} experience (SHOW_ALL={show_all})")
    if missing:
        summary += "\nno 🌐 Public section yet: " + ", ".join(missing)
    if hubs != len(HUBS):
        summary += f"\nwarning: expected {len(HUBS)} hubs; check the integration can see every hub page"

    if write_index(skills, projects, experience):
        summary += f"\nupdated the resume in {INDEX.name}"
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    if (old.get("source") == "notion" and old.get("skills") == skills and old.get("projects") == projects
            and old.get("experience") == experience):
        return summary + "\nno changes to skills.json"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source": "notion",
        "skills": skills,
        "projects": projects,
        "experience": experience,
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
