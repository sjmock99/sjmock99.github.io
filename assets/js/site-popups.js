/**
 * Pop-ups, so visitors stay on the page they're on: a link to the skill graph or to a project page opens it over
 * the current page instead of navigating away.
 *   skills.html…        -> the skill graph (#sgDrawer; #skill= / #item= / #disc= links open it at that spot)
 *   projects/<x>.html   -> that project (#pjPopup, homepage only; on a project page these stay normal links)
 * Each loads the page with ?embed=1 in an iframe the first time it opens. Both can be open at once (a skill
 * picked inside a project opens the graph on top); the newest is in front. The address shows the front one
 * (#skill-graph or #project=<x>), so Back closes it and the link can be shared.
 * Ctrl/Cmd-click or middle-click still opens the page in a new tab.
 *
 * Inside a pop-up (a page loaded with ?embed=1) the same links are handed to the page underneath, so pop-ups
 * never nest, and Esc asks it to close the pop-up.
 */
(function () {
  "use strict";

  const ROOT = new URL("../../", document.currentScript.src);  // this file is assets/js/site-popups.js
  const embedded = new URLSearchParams(location.search).get("embed") === "1" && window.parent !== window;
  const plainClick = e => e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;

  // What a link opens: { kind: "skills", hash } or { kind: "project", slug }, or null for any other link.
  function route(href) {
    let u;
    try { u = new URL(href, location.href); } catch (e) { return null; }
    if (u.origin !== location.origin || !u.pathname.startsWith(ROOT.pathname)) return null;
    const rel = u.pathname.slice(ROOT.pathname.length), m = rel.match(/^projects\/([a-z0-9-]+)\.html$/);
    return rel === "skills.html" ? { kind: "skills", hash: u.hash } : m ? { kind: "project", slug: m[1] } : null;
  }

  if (embedded) {
    document.addEventListener("click", e => {
      const a = e.target.closest("a[href]");
      if (!a || a.target === "_blank" || !plainClick(e) || !route(a.href)) return;
      e.preventDefault();
      window.parent.postMessage({ sgOpen: a.href }, location.origin);
    });
    document.addEventListener("keydown", e => {
      // Esc in the photo viewer only closes the photo.
      if (e.key === "Escape" && !document.body.classList.contains("glightbox-open")) window.parent.postMessage("sg-close", location.origin);
    });
    return;
  }

  const POPUPS = { skills: document.getElementById("sgDrawer"), project: document.getElementById("pjPopup") };
  if (!POPUPS.skills && !POPUPS.project) return;
  const instant = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const frames = {};
  let stack = [], project = null, opener = null;  // open pop-ups (front last); the project shown

  const address = () => {
    const front = stack[stack.length - 1];
    return !front ? location.pathname + location.search : front === "skills" ? "#skill-graph" : "#project=" + project;
  };

  function frame(kind, src) {
    const el = POPUPS[kind];
    if (frames[kind]) return frames[kind];
    const f = frames[kind] = document.createElement("iframe");
    f.title = kind === "skills" ? "Skill graph" : "Project";
    f.src = src;
    f.addEventListener("load", () => {
      el.classList.add("loaded");
      if (kind === "project") {
        const t = (f.contentDocument && f.contentDocument.title || "").replace(/ · .*$/, "");
        el.querySelector("h2").textContent = f.title = t || "Project";
      }
    });
    el.querySelector(".sg-drawer-body").appendChild(f);
    return f;
  }

  function load(r) {
    if (r.kind === "skills") {
      const known = frames.skills;
      const f = frame("skills", new URL("skills.html?embed=1" + (r.hash || ""), ROOT).href);
      // Already loaded: the graph follows hash changes and selects the linked skill / item.
      if (known && r.hash) f.contentWindow.location.hash = r.hash.slice(1);
      return;
    }
    const url = new URL(`projects/${r.slug}.html`, ROOT).href;
    POPUPS.project.querySelector(".sg-drawer-full").href = url;
    if (frames.project && project !== r.slug) {
      POPUPS.project.classList.remove("loaded");
      frames.project.contentWindow.location.replace(url + "?embed=1");  // replace: no extra Back step
    }
    frame("project", url + "?embed=1");
    project = r.slug;
  }

  function showEl(el, z) {
    el.style.zIndex = z;
    if (!el.hidden && el.classList.contains("open")) return;
    el.hidden = false;
    requestAnimationFrame(() => el.classList.add("open"));
  }
  function hideEl(el) {
    if (el.hidden) return;
    el.classList.remove("open");
    setTimeout(() => { if (!el.classList.contains("open")) el.hidden = true; }, instant ? 0 : 300);
  }
  // Show exactly the pop-ups in next (front last).
  function render(next) {
    if (!stack.length && next.length) opener = document.activeElement;
    Object.entries(POPUPS).forEach(([k, el]) => { if (el) next.includes(k) ? showEl(el, 10000 + next.indexOf(k)) : hideEl(el); });
    stack = next;
    document.documentElement.classList.toggle("sg-drawer-open", stack.length > 0);
    if (stack.length) POPUPS[stack[stack.length - 1]].querySelector(".sg-drawer-close").focus({ preventScroll: true });
    else if (opener && opener.focus) opener.focus({ preventScroll: true });
  }
  const state = depth => ({ sgPopups: stack, project, depth });

  function open(r) {
    load(r);
    const next = stack.filter(k => k !== r.kind).concat(r.kind);
    const same = next.join() === stack.join();
    const depth = history.state && history.state.sgPopups ? history.state.depth : 0;
    render(next);
    // Another project in the pop-up that's already in front: swap it in place, so Back still closes the pop-up.
    if (same) history.replaceState(state(depth), "", address());
    else history.pushState(state(depth + 1), "", address());
  }

  // Close the front pop-up: go Back when we added that history entry, so Back / Forward stay in step.
  function close() {
    if (!stack.length) return;
    if (history.state && history.state.sgPopups && history.state.depth > 0) return history.back();
    render(stack.slice(0, -1));
    history.replaceState(stack.length ? state(0) : null, "", address());
  }

  window.addEventListener("popstate", () => {
    const st = history.state && history.state.sgPopups ? history.state : null;
    if (st && st.project && st.sgPopups.includes("project")) load({ kind: "project", slug: st.project });
    render(st ? st.sgPopups.filter(k => POPUPS[k]) : []);
  });

  document.addEventListener("click", e => {
    if (e.target.closest("[data-close]")) return close();
    const a = e.target.closest("a[href]");
    if (!a || a.target === "_blank" || !plainClick(e)) return;
    const r = route(a.href);
    if (!r || !POPUPS[r.kind]) return;
    e.preventDefault();
    open(r);
  });

  window.addEventListener("message", e => {
    if (e.origin !== location.origin) return;
    if (e.data === "sg-close") return close();
    if (e.data && typeof e.data.sgOpen === "string") {
      const r = route(e.data.sgOpen);
      if (r && POPUPS[r.kind]) open(r);
      else if (r) location.href = e.data.sgOpen;  // no pop-up for it here (a project page): just go there
    }
  });

  document.addEventListener("keydown", e => {
    if (!stack.length) return;
    if (e.key === "Escape") close();
    // Keep Tab inside the front pop-up's bar (the iframe takes focus on click).
    if (e.key === "Tab") {
      const f = [...POPUPS[stack[stack.length - 1]].querySelectorAll("a[href], button, iframe")];
      const i = f.indexOf(document.activeElement);
      if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus(); }
    }
  });

  // Opened from a shared link: #skill-graph or #project=<x>.
  const m = location.hash.match(/^#project=([a-z0-9-]+)$/);
  const first = location.hash === "#skill-graph" ? { kind: "skills" } : m ? { kind: "project", slug: m[1] } : null;
  if (first && POPUPS[first.kind]) {
    load(first);
    render([first.kind]);
    history.replaceState(state(0), "", address());
  }
})();
