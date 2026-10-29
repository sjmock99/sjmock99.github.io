#!/usr/bin/env python3
"""Local admin for the Skill Graph: edit skills, projects and experience (jobs, degrees) in Notion.

    python3 scripts/admin.py          # then open http://localhost:8001

Runs only on this computer (bound to 127.0.0.1). Uses the same key as sync_notion.py.
New pages are created directly in the wiki database, the same as Notion's "+ New" button
(not nested inside another page), using the wiki's template of the same Type when there is one. "Delete" moves a page to Notion's Trash (restorable there for 30 days); it never
deletes permanently.
"""
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_notion as notion  # noqa: E402

PORT = int(os.environ.get("ADMIN_PORT", "8001"))
PAGE = Path(__file__).resolve().parent / "admin.html"
ALLOWED_HOSTS = {f"localhost:{PORT}", f"127.0.0.1:{PORT}"}
RATINGS = {x / 2 for x in range(2, 11)}  # 1, 1.5, ... 5
LABELS = {"Reference": "skill", "Project": "project", "Experience": "job", "Education": "degree"}
TEXT_FIELDS = {"role": "Role", "organization": "Organization", "location": "Location"}
# Jobs and degrees are named "Organization — Role" automatically (two JPL roles stay distinct in Notion).
auto_title = lambda org, role: " — ".join(x for x in (org, role) if x)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Body for new pages that have no template: the heading whose contents the site shows (see sync_notion.public_html).
PUBLIC_SECTION = [
    {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "🌐 Public"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": []}},
]

records = {}  # id -> record, as returned by sync_notion.to_record
templates = {}  # template name -> id, e.g. "Reference", "Project"
lock = threading.Lock()


def load():
    fresh = {r["id"]: r for r in notion.fetch_records()}
    res = notion.request("GET", f"/data_sources/{notion.DATA_SOURCE_ID}/templates")
    with lock:
        records.clear()
        records.update(fresh)
        templates.clear()
        templates.update({t["name"]: t["id"] for t in res.get("templates", [])})


def patch(page_id, properties):
    page = notion.request("PATCH", f"/pages/{page_id}", {"properties": properties})
    rec = notion.to_record(page)
    with lock:
        records[rec["id"]] = rec
    return rec


def check_rating(value):
    if value is None:
        return None  # clears the property; never write 0
    value = float(value)
    if value not in RATINGS:
        raise ValueError("rating must be 1 to 5 in half steps, or empty")
    return value


def create_page(kind, body):
    """kind is a Type: "Reference" (a skill), "Project", "Experience" or "Education". Uses the wiki template of
    the same name if there is one; otherwise the page starts with an empty 🌐 Public section."""
    label = LABELS[kind]
    name = " ".join(str(body.get("name") or "").split())
    if not name or len(name) > 200:
        raise ValueError(f"give the {label} a name")
    with lock:
        is_kind = notion.is_skill if kind == "Reference" else (lambda r: kind in r["types"])
        taken = any(r["name"].lower() == name.lower() and is_kind(r) for r in records.values())
        template = templates.get(kind)
    if taken:
        raise ValueError(f'a {label} called "{name}" already exists')
    props = {
        "Page": {"title": [{"text": {"content": name}}]},
        "Type": {"multi_select": [{"name": kind}]},
        "Public": {"checkbox": bool(body.get("public"))},
    }
    if kind == "Reference":
        parent = body.get("parent") or None
        if not parent or parent not in records:
            raise ValueError("pick a parent skill")
        props["Parent skill"] = {"relation": [{"id": parent}]}
        rating = check_rating(body.get("rating"))
        if rating is not None:
            props["Rating"] = {"number": rating}
    req = {
        "parent": {"type": "data_source_id", "data_source_id": notion.DATA_SOURCE_ID},
        "properties": props,
    }
    if template:  # Notion fills in the template's content a moment after the page is created
        req["template"] = {"type": "template_id", "template_id": template}
    elif kind != "Reference":
        req["children"] = PUBLIC_SECTION
    page = notion.request("POST", "/pages", req)
    rec = notion.to_record(page)
    with lock:
        records[rec["id"]] = rec
    return rec


def trash_page(page_id):
    if page_id in notion.HUBS:
        raise ValueError("discipline hubs can't be deleted")
    with lock:
        rec = records[page_id]
        kids = [r["name"] for r in records.values() if r["parent"] == page_id]
    if kids:
        raise ValueError(f"move or delete what's under it first: {', '.join(kids[:5])}")
    notion.request("PATCH", f"/pages/{page_id}", {"in_trash": True})
    with lock:
        records.pop(page_id, None)
    return {"ok": True, "name": rec["name"]}


def would_cycle(skill_id, parent_id):
    seen = set()
    while parent_id and parent_id not in seen:
        if parent_id == skill_id:
            return True
        seen.add(parent_id)
        parent_id = records.get(parent_id, {}).get("parent")
    return False


def handle_action(action, body):
    page_id = body.get("id", "")
    if action == "sync":
        # Re-read Notion first, so edits made in Notion itself (not just in this admin) are included.
        load()
        with lock:
            snapshot = list(records.values())
        return {"message": notion.sync(snapshot, bool(body.get("showAll")))}
    if action == "reload":
        load()
        return {"ok": True}
    if action == "create":
        return create_page("Reference", body)
    if action == "create-project":
        return create_page("Project", body)
    if action == "create-experience":
        kind = body.get("kind")
        if kind not in ("Experience", "Education"):
            raise ValueError("kind must be Experience or Education")
        org, role = (" ".join(str(body.get(k) or "").split())[:300] for k in ("organization", "role"))
        if not org:
            raise ValueError("give the organization" if kind == "Experience" else "give the school")
        rec = create_page(kind, {**body, "name": auto_title(org, role)})
        return patch(rec["id"], {"Organization": {"rich_text": [{"text": {"content": org}}]},
                                 "Role": {"rich_text": [{"text": {"content": role}}] if role else []}})
    if page_id not in records:
        raise ValueError("unknown page")
    if action == "trash":
        return trash_page(page_id)
    if action == "rating":
        return patch(page_id, {"Rating": {"number": check_rating(body.get("value"))}})
    if action == "target":
        return patch(page_id, {"Target": {"number": check_rating(body.get("value"))}})
    if action == "blurb":
        text = " ".join(str(body.get("value") or "").split())
        if len(text) > 2000:
            raise ValueError("keep the blurb under 2000 characters")
        return patch(page_id, {"Blurb": {"rich_text": [{"text": {"content": text}}] if text else []}})
    if action == "name":
        name = " ".join(str(body.get("value") or "").split())
        if not name or len(name) > 200:
            raise ValueError("give it a name")
        return patch(page_id, {"Page": {"title": [{"text": {"content": name}}]}})
    if action == "field":
        prop = TEXT_FIELDS.get(body.get("field"))
        if not prop:
            raise ValueError("unknown field")
        text = " ".join(str(body.get("value") or "").split())[:300]
        props = {prop: {"rich_text": [{"text": {"content": text}}] if text else []}}
        with lock:
            rec = dict(records[page_id])
        if {"Experience", "Education"} & set(rec["types"]) and body["field"] in ("role", "organization"):
            rec[body["field"]] = text
            title = auto_title(rec["organization"], rec["role"])
            if title and title != rec["name"]:
                props["Page"] = {"title": [{"text": {"content": title}}]}
        return patch(page_id, props)
    if action == "link":
        url = str(body.get("value") or "").strip()
        if url and not url.startswith(("http://", "https://")):
            raise ValueError("links must start with http:// or https://")
        return patch(page_id, {"Link": {"url": url or None}})
    if action == "date":
        start, end = (body.get("value") or {}).get("start"), (body.get("value") or {}).get("end")
        if any(d and not DATE_RE.match(d) for d in (start, end)):
            raise ValueError("dates must look like 2024-09-01")
        if end and not start:
            raise ValueError("set a start date first")
        if start and end and end < start:
            raise ValueError("the end is before the start")
        return patch(page_id, {"Date": {"date": {"start": start, "end": end or None} if start else None}})
    if action == "public":
        return patch(page_id, {"Public": {"checkbox": bool(body.get("value"))}})
    if action == "parent":
        parent = body.get("value") or None
        if parent and parent not in records:
            raise ValueError("unknown parent")
        if page_id in notion.HUBS:
            raise ValueError("discipline hubs can't have a parent")
        if parent and would_cycle(page_id, parent):
            raise ValueError("that would make a skill its own ancestor")
        return patch(page_id, {"Parent skill": {"relation": [{"id": parent}] if parent else []}})
    if action == "skills-used":
        ids = list(dict.fromkeys(body.get("value") or []))
        if any(i not in records for i in ids):
            raise ValueError("unknown skill")
        return patch(page_id, {"Skills used": {"relation": [{"id": i} for i in ids]}})
    raise ValueError("unknown action")


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def trusted(self):
        # Blocks other websites (and DNS-rebinding tricks) from driving this server via your browser.
        if self.headers.get("Host") not in ALLOWED_HOSTS:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin.split("//", 1)[-1] in ALLOWED_HOSTS

    def do_GET(self):
        if not self.trusted():
            return self.send(403, {"error": "forbidden"})
        if self.path in ("/", "/index.html"):
            return self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/data":
            with lock:
                return self.send(200, {"records": list(records.values()), "hubs": notion.HUBS})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        if not self.trusted() or self.headers.get("Content-Type") != "application/json":
            return self.send(403, {"error": "forbidden"})
        if not self.path.startswith("/api/"):
            return self.send(404, {"error": "not found"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            self.send(200, handle_action(self.path[len("/api/"):], body))
        except (ValueError, TypeError) as e:
            self.send(400, {"error": str(e)})
        except notion.NotionError as e:
            self.send(502, {"error": str(e)})

    def log_message(self, fmt, *args):
        if "POST" in (args[0] if args else ""):
            sys.stderr.write("%s\n" % (fmt % args))


def main():
    print("Loading the wiki from Notion…")
    try:
        load()
    except notion.NotionError as e:
        sys.exit(str(e))
    print(f"{len(records)} pages loaded. Admin running at http://localhost:{PORT}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
