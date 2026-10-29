/**
 * Skill Graph (skills.html): radial skill tree drawn with D3 from assets/data/skills.json.
 * The JSON is a snapshot of the Notion Engineering Wiki, refreshed by scripts/sync_notion.py.
 */
(function () {
  "use strict";

  const HUB_KEYS = { Mechanical: "mech", Electrical: "elec", Software: "soft", Systems: "sys", Other: "oth" };
  const HUB_ORDER = ["Mechanical", "Electrical", "Software", "Systems", "Other"];

  // Owner mode: shows "Open in Notion" links. Notion itself keeps the pages private (only my login can open
  // them), so this only decides whether the button is shown. ?owner=1 turns it on for this browser, ?owner=0 off.
  const OWNER_KEY = "sg-owner";
  const ownerParam = new URLSearchParams(location.search).get("owner");
  try {
    if (ownerParam === "1") localStorage.setItem(OWNER_KEY, "1");
    if (ownerParam === "0") localStorage.removeItem(OWNER_KEY);
  } catch (e) { /* storage blocked */ }
  let owner = ["localhost", "127.0.0.1"].includes(location.hostname);
  try { owner = owner || localStorage.getItem(OWNER_KEY) === "1"; } catch (e) { /* ignore */ }
  const embedded = new URLSearchParams(location.search).get("embed") === "1";
  if (ownerParam !== null) history.replaceState(null, "", location.pathname + (embedded ? "?embed=1" : "") + location.hash);
  const notionLink = id => owner && /^[0-9a-f]{32}$/.test(id || "")
    ? `<a class="sg-notion" href="https://www.notion.so/${id}" target="_blank" rel="noopener">Open in Notion ↗</a>` : "";

  // What each rating level means (shown in the legend, panel and tooltips). Half steps sit between two levels.
  const LEVELS = {
    1: ["Aware", "I know what it's for; courses or tutorials only"],
    2: ["Beginner", "Used it with guidance, e.g. in one personal project"],
    3: ["Proficient", "Use it on my own; shipped it in a project or job"],
    4: ["Advanced", "Designed with it across several projects or jobs; can teach it"],
    5: ["Expert", "The person others come to for it"]
  };
  const levelLabel = r => r == null ? "Not rated yet"
    : Number.isInteger(r) ? LEVELS[r][0] : `${LEVELS[Math.floor(r)][0]} → ${LEVELS[Math.ceil(r)][0]}`;

  const phone = window.matchMedia("(max-width: 768px)");  // same breakpoint as the bottom sheet in skill-graph.css
  const discColor = k => `var(--c-${k})`;
  const KIND_LABEL = { project: "Project", work: "Experience", education: "Education" };
  // Jobs and degrees are named by their organization; projects by their own name.
  const itemTitle = p => (p.kind !== "project" && p.organization) || p.name;
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  // "Sep 2024 – Sep 2025", "Feb 2026 – Present"; degrees show years only.
  const dateRange = p => {
    if (!p.start) return "";
    const f = d => p.kind === "education" ? d.slice(0, 4) : `${MONTHS[+d.slice(5, 7) - 1]} ${d.slice(0, 4)}`;
    const end = p.end ? f(p.end) : p.kind === "work" ? "Present" : "";
    return end && end !== f(p.start) ? `${f(p.start)} – ${end}` : f(p.start);
  };
  const rScale = r => r == null ? 4 : 3 + r * 1.6;
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  fetch("assets/data/skills.json", { cache: "no-cache" })
    .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(render)
    .catch(err => {
      const hint = location.protocol === "file:"
        ? " This page was opened as a file. Open it through a web server instead, e.g. run <code>python3 -m http.server 8000</code> in the site folder and go to http://localhost:8000/skills.html."
        : "";
      document.getElementById("sgPanel").innerHTML = `<p class="sg-empty">Couldn't load the skill data (${esc(err.message)}).${hint}</p>`;
    });

  function render(data) {
    // ---- build hierarchy: hubs are skills with no parent ----
    const byId = new Map(data.skills.map(s => [s.id, { ...s, children: [] }]));
    const hubs = [];
    byId.forEach(s => {
      const p = s.parent && byId.get(s.parent);
      if (p) p.children.push(s);
      else if (!s.parent) hubs.push(s);
    });
    hubs.sort((a, b) => HUB_ORDER.indexOf(a.name) - HUB_ORDER.indexOf(b.name));
    hubs.forEach(h => h.kind = "hub");
    const setDisc = (s, k) => { s.disc = k; s.children.forEach(c => setDisc(c, k)); };
    hubs.forEach(h => setDisc(h, HUB_KEYS[h.name] || "oth"));

    const root = d3.hierarchy({ name: "Stephen", kind: "root", children: hubs });

    const nodeById = new Map();
    root.each(n => { if (!n.data.kind) nodeById.set(n.data.id, n); });
    // Projects plus experience (kind "work" / "education"); all of them are "things that used skills".
    const projects = [...data.projects.map(p => ({ ...p, kind: "project" })), ...(data.experience || [])]
      .map(p => ({ ...p, nodes: p.skills.map(id => nodeById.get(id)).filter(Boolean) }));
    const usedIn = new Map();
    projects.forEach(p => p.nodes.forEach(n => { if (!usedIn.has(n)) usedIn.set(n, []); usedIn.get(n).push(p); }));

    const R = 455;
    // Fixed ring per depth. Main skills sit close in (155) and their labels point outward, into the wide gap
    // before the sub-skill ring (385), so they never run into the hub names near the center.
    const RINGS = [0, 75, 155, 385, 455];
    const ring = d => RINGS[Math.min(d, RINGS.length - 1)];
    const labelOut = d => d.depth === 2 || !d.children;

    // Within each branch: highest rated first, unrated last, then A-Z (disciplines keep their fixed order).
    root.sort((a, b) => a.depth === 1 ? 0 : (b.data.rating ?? -1) - (a.data.rating ?? -1) || a.data.name.localeCompare(b.data.name));
    // Angular spacing scaled by 1/radius, so a skill on an inner ring gets as much room (in px) as one further out.
    d3.tree().size([2 * Math.PI, R]).separation((a, b) => (a.parent === b.parent ? 1 : 1.4) * RINGS[3] / ring(Math.max(a.depth, b.depth)))(root);
    root.each(n => { n.y = ring(n.depth); });

    // ---- stats ----
    const skills = root.descendants().filter(n => !n.data.kind);
    const rated = skills.filter(n => n.data.rating != null);
    // Skills per level band, counted (never averaged, so a new Lv 1 skill adds breadth instead of lowering a score).
    const BANDS = ["Lv 4–5", "Lv 3", "Lv 2", "Lv 1", "Not rated"];
    const SHADE = [100, 68, 42, 20];  // % of the discipline color per band: darker = stronger
    const bandOf = r => r == null ? 4 : r >= 4 ? 0 : r >= 3 ? 1 : r >= 2 ? 2 : 3;
    const discMix = h => { const c = [0, 0, 0, 0, 0]; h.descendants().slice(1).forEach(n => c[bandOf(n.data.rating)]++); return c; };
    const sum = c => c.reduce((a, b) => a + b, 0);
    const mixTitle = (name, c) => `${name}: ` + c.map((k, i) => k && `${k} at ${BANDS[i]}`).filter(Boolean).join(", ");
    // One bar per discipline, segments in band order; width relative to the biggest discipline (max).
    const mixBar = (c, disc, max) => `<span class="sg-mix" style="width:${sum(c) / max * 100}%">${c.map((k, i) => !k ? "" :
      `<i class="${i === 4 ? "none" : ""}" style="flex:${k};${i < 4 ? `background:color-mix(in srgb, ${discColor(disc)} ${SHADE[i]}%, var(--sg-surface))` : `border-color:${discColor(disc)}`}"></i>`).join("")}</span>`;
    const mixLegend = () => `<p class="sg-mix-legend" aria-hidden="true">${BANDS.map((b, i) =>
      `<span><i class="${i === 4 ? "none" : ""}" style="${i < 4 ? `background:color-mix(in srgb, var(--sg-ink) ${SHADE[i]}%, var(--sg-surface))` : ""}"></i>${b}</span>`).join("")}</p>`;
    document.getElementById("sgStats").innerHTML =
      `<div><b>${skills.length}</b>skills</div><div><b>${hubs.length}</b>disciplines</div><div><b>${projects.filter(p => p.kind === "work").length}</b>jobs</div><div><b>${projects.filter(p => p.kind === "project").length}</b>projects</div>`;
    const updatedEl = document.getElementById("sgUpdated");
    if (data.updated) updatedEl.textContent = `Data from my Notion wiki, updated ${data.updated}.`;
    if (owner) {
      updatedEl.insertAdjacentHTML("beforeend", ` · <b>Owner mode</b> (Notion links on) · <a href="?owner=0${esc(location.hash)}">turn off</a>`);
    }

    // ---- svg ----
    const pad = 125, size = (R + pad) * 2;
    const svg = d3.select("#sgGraph").attr("viewBox", [-size / 2, -size / 2, size, size]);
    const g = svg.append("g");
    const zoom = d3.zoom().scaleExtent([0.6, 4]).on("zoom", e => g.attr("transform", e.transform));
    svg.call(zoom);

    const links = g.append("g").selectAll("path").data(root.links()).join("path")
      .attr("class", "link")
      .style("stroke", d => d.target.data.disc ? discColor(d.target.data.disc) : null)
      .style("stroke-opacity", .35);

    const nodes = g.append("g").selectAll("g").data(root.descendants()).join("g")
      // "minor" = sub-skills below the main skills (slightly smaller labels).
      .attr("class", d => "node " + (d.data.kind || "skill") + (d.depth >= 3 ? " minor" : ""))
      .attr("tabindex", 0).attr("role", "button")
      .attr("aria-label", d => d.data.name + (d.data.rating != null ? `, rated ${d.data.rating} of 5` : ""));

    nodes.append("circle")
      .attr("r", d => d.depth === 0 ? 30 : d.data.kind === "hub" ? 10 : rScale(d.data.rating))
      .style("fill", d => d.depth === 0 ? "var(--sg-ink)" : (d.data.kind === "hub" || d.data.rating != null) ? discColor(d.data.disc) : "var(--sg-surface)")
      .style("stroke", d => d.depth === 0 ? "var(--sg-ink)" : discColor(d.data.disc))
      .attr("stroke-dasharray", d => (!d.data.kind && d.data.rating == null) ? "2 2" : null);

    const angle = d => d.x * 180 / Math.PI - 90;
    const labels = nodes.append("text")
      // Sub-skills that have their own sub-skills (e.g. WebDev) usually share a spoke with their parent's label;
      // drop them one line to the side so the two don't print on top of each other.
      .attr("dy", d => d.depth >= 3 && d.children ? "1.45em" : "0.32em")
      .text(d => d.data.name);

    links.attr("d", d3.linkRadial().angle(d => d.x).radius(d => d.y));
    nodes.attr("transform", d => d.depth === 0 ? "" : `rotate(${angle(d)}) translate(${d.y},0)`);
    labels
        .attr("x", d => { if (d.depth <= 1) return 0; const off = rScale(d.data.rating) + 5; return (d.x < Math.PI) === labelOut(d) ? off : -off; })
        .attr("text-anchor", d => d.depth <= 1 ? "middle" : (d.x < Math.PI) === labelOut(d) ? "start" : "end")
        // Hub names sit level, just outside their dot; skill names run along their spoke.
        .attr("transform", d => d.depth === 0 ? null : d.depth === 1 ? `rotate(${-angle(d)}) translate(${22 * Math.cos(d.x - Math.PI / 2)},${22 * Math.sin(d.x - Math.PI / 2) + 4})` : d.x >= Math.PI ? "rotate(180)" : null);

    // ---- tree view: a skill window in the style of classic (~2010) MapleStory, one tab per discipline ----
    const treeEl = document.getElementById("sgTree");
    const tileOf = new Map();  // hierarchy node -> skill row button
    // Icon stand-in: initials ("Machine Design" -> "MD", "CAD" -> "CAD", "Dynamics" -> "Dy").
    const initials = name => {
      const words = name.replace(/[()]/g, "").split(/[\s/&+,-]+/).filter(Boolean);
      if (words.length > 1) return (words[0][0] + words[1][0]).toUpperCase();
      return /^[A-Z0-9]{2,4}$/.test(words[0]) ? words[0].slice(0, 3) : words[0].slice(0, 2);
    };
    const lvBar = r => `<span class="sg-lvbar" aria-hidden="true">${[1, 2, 3, 4, 5].map(i => `<i class="${r >= i ? "full" : r >= i - .5 ? "half" : ""}"></i>`).join("")}</span>`;
    const row = (n, cls) => `<button class="sg-skill ${cls || ""}${n.data.rating == null ? " locked" : ""}" data-key="${esc(n.data.id)}" title="${esc(levelLabel(n.data.rating))}"
        aria-label="${esc(n.data.name)}${n.data.rating != null ? `, level ${n.data.rating} of 5` : ", not learned yet"}">
        <span class="sg-icon" aria-hidden="true">${esc(initials(n.data.name))}</span>
        <span class="sg-skill-text"><span class="sg-skill-name">${esc(n.data.name)}</span>
          <span class="sg-skill-lv">${n.data.rating != null ? `Lv. ${n.data.rating}${lvBar(n.data.rating)}` : "Not learned yet"}</span></span>
      </button>`;
    const branch = n => `<li>${row(n)}${n.children ? `<ul>${n.children.map(branch).join("")}</ul>` : ""}</li>`;
    const allSkills = root.descendants().filter(n => !n.data.kind);
    const learned = allSkills.filter(n => n.data.rating != null);
    treeEl.innerHTML = `
      <div class="sg-win-title"><span>SKILL</span><span class="sg-win-x" aria-hidden="true">×</span></div>
      <div class="sg-char">
        <div class="sg-portrait"><img src="assets/img/misc/stephen_maple.jpg" alt="Stephen's MapleStory-style character" width="735" height="1307"></div>
        <dl class="sg-char-stats">
          <div><dt>Name</dt><dd>prettygoodengineer</dd></div>
          <div><dt>Job</dt><dd>Robotics Engineer</dd></div>
          <div><dt>Skills</dt><dd>${allSkills.length}</dd></div>
          <div><dt>Lv 4+</dt><dd>${learned.filter(n => n.data.rating >= 4).length}</dd></div>
        </dl>
      </div>
      <div class="sg-tabs" role="tablist">${root.children.map(h => `<button class="sg-tab" role="tab" id="sgTab-${h.data.disc}" aria-controls="sgPane-${h.data.disc}" data-tab="${h.data.disc}" style="--c:${discColor(h.data.disc)}">
          <span class="sg-dot" style="background:${discColor(h.data.disc)}"></span>${esc(h.data.name)}<span class="sg-tab-count" hidden></span></button>`).join("")}</div>
      ${root.children.map(h => {
        const c = discMix(h);
        return `<div class="sg-pane" role="tabpanel" id="sgPane-${h.data.disc}" aria-labelledby="sgTab-${h.data.disc}" data-disc="${h.data.disc}" style="--c:${discColor(h.data.disc)}" hidden>
          <p class="sg-pane-meta">${sum(c)} ${esc(h.data.name.toLowerCase())} skills · ${c[0]} at Lv 4+${h.data.blurb ? ` · ${esc(h.data.blurb)}` : ""}</p>
          <div class="sg-groups"></div>
        </div>`;
      }).join("")}`;
    const nodeByKey = new Map(root.descendants().slice(1).map(n => [n.data.id, n]));
    treeEl.querySelectorAll(".sg-pane").forEach(pane => {
      const h = root.children.find(x => x.data.disc === pane.dataset.disc);
      pane.querySelector(".sg-groups").innerHTML = (h.children || []).map(c =>
        `<ul class="sg-group"><li>${row(c, "main")}${c.children ? `<ul>${c.children.map(branch).join("")}</ul>` : ""}</li></ul>`).join("");
    });
    treeEl.querySelectorAll(".sg-skill").forEach(el => tileOf.set(nodeByKey.get(el.dataset.key), el));
    let currentTab = null;
    function showTab(disc) {
      currentTab = disc;
      treeEl.querySelectorAll(".sg-tab").forEach(t => { const on = t.dataset.tab === disc; t.setAttribute("aria-selected", on); t.tabIndex = on ? 0 : -1; });
      treeEl.querySelectorAll(".sg-pane").forEach(p => p.hidden = p.dataset.disc !== disc);
    }
    showTab(root.children[0].data.disc);
    // Switching tabs by hand starts fresh (a skill picked on another tab would leave this one all faded),
    // but a project highlight is kept so its skills can be followed from tab to tab.
    function switchTab(disc) {
      if (disc === currentTab) return;
      if (!state.project && !state.levels) clearAll();
      showTab(disc);
    }
    treeEl.addEventListener("click", e => {
      const tab = e.target.closest(".sg-tab");
      if (tab) return switchTab(tab.dataset.tab);
      const t = e.target.closest(".sg-skill");
      if (t) selectNode(nodeByKey.get(t.dataset.key));
    });
    treeEl.querySelector(".sg-tabs").addEventListener("keydown", e => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const tabs = [...treeEl.querySelectorAll(".sg-tab")], i = tabs.findIndex(t => t.dataset.tab === currentTab);
      const next = tabs[(i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
      switchTab(next.dataset.tab); next.focus();
    });

    // ---- bars view: every skill as a horizontal bar, sortable by rating or name ----
    const barsEl = document.getElementById("sgBars");
    const barOf = new Map();  // hierarchy node -> bar row button
    const instant = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const SORTS = { desc: "High → low", asc: "Low → high", name: "A – Z", disc: "By discipline" };
    let barSort = "desc";
    try { if (SORTS[localStorage.getItem("sg-bar-sort")]) barSort = localStorage.getItem("sg-bar-sort"); } catch (e) { /* ignore */ }
    barsEl.innerHTML = `
      <div class="sg-bars-head"><span class="sg-label">Sort</span>${Object.entries(SORTS).map(([k, t]) =>
        `<button class="sg-chip" data-sort="${k}" aria-pressed="false">${t}</button>`).join("")}
        <span class="sg-bars-hint">Click a bar for details · click empty space or press Esc to go back</span></div>
      <div class="sg-bar-axis" aria-hidden="true"><span></span><span class="sg-bar-ticks">${[0, 1, 2, 3, 4, 5].map(i => `<i style="left:${i * 20}%">${i}</i>`).join("")}</span><span></span></div>
      <div class="sg-bar-list" role="list"></div>`;
    const barList = barsEl.querySelector(".sg-bar-list");
    skills.forEach(n => {
      const d = n.data, el = document.createElement("button");
      el.className = "sg-bar" + (d.rating == null ? " locked" : "");
      el.setAttribute("role", "listitem");
      el.title = `${d.name} · ${levelLabel(d.rating)}`;
      el.setAttribute("aria-label", `${d.name}${d.rating != null ? `, level ${d.rating} of 5` : ", not rated yet"}`);
      el.innerHTML = `<span class="sg-bar-name"><span class="sg-dot" style="background:${discColor(d.disc)}"></span>${esc(d.name)}</span>
        <span class="sg-bar-track"><i style="width:${(d.rating || 0) / 5 * 100}%;background:${discColor(d.disc)}"></i></span>
        <span class="sg-bar-val">${d.rating != null ? d.rating : "–"}</span>`;
      el.onclick = () => selected === n ? stepBack() : selectNode(n);
      barOf.set(n, el);
    });
    // Section headers (built fresh each time, since one discipline can appear in both the focus and "other" sections).
    const barHead = (dot, title, meta) => {
      const el = document.createElement("p");
      el.className = "sg-bar-group" + (dot ? "" : " sg-bar-section");
      el.innerHTML = `${dot ? `<span class="sg-dot" style="background:${dot}"></span>` : ""}${esc(title)}<span>${esc(meta)}</span>`;
      return el;
    };
    const byName = (a, b) => a.data.name.localeCompare(b.data.name);
    // Unrated skills always sit at the bottom, whichever way the ratings run.
    const byRating = dir => (a, b) => (a.data.rating == null) - (b.data.rating == null)
      || dir * ((a.data.rating ?? 0) - (b.data.rating ?? 0)) || byName(a, b);
    // Bar rows for a list of skills in the chosen order; "disc" = disciplines in their usual order, highest first within each.
    function orderedBars(list, k) {
      if (k !== "disc") return list.slice().sort(k === "name" ? byName : byRating(k === "asc" ? 1 : -1)).map(n => barOf.get(n));
      const by = d3.group(list, n => n.data.disc);
      return root.children.filter(h => by.has(h.data.disc)).flatMap(h => {
        const c = discMix(h);
        return [barHead(discColor(h.data.disc), h.data.name, `${sum(c)} skills · ${c[0]} at Lv 4+`),
          ...by.get(h.data.disc).sort(byRating(-1)).map(n => barOf.get(n))];
      });
    }
    // A project, level or discipline filter pulls its skills into a section at the top; the rest go below.
    let barFocus = null;  // { title, nodes } or null
    function arrangeBars() {
      barsEl.classList.toggle("dim", !!barFocus);
      if (!barFocus) return barList.replaceChildren(...orderedBars(skills, barSort));
      const inFocus = new Set(barFocus.nodes), rest = skills.filter(n => !inFocus.has(n));
      // Light exactly the focus section (the highlight also lights parent skills, which here would sit in "other").
      barOf.forEach((el, n) => el.classList.toggle("on", inFocus.has(n)));
      barList.replaceChildren(
        barHead(null, barFocus.title, `${inFocus.size} skill${inFocus.size === 1 ? "" : "s"}`), ...orderedBars([...inFocus], barSort),
        ...(rest.length ? [barHead(null, "Other skills", `${rest.length}`), ...orderedBars(rest, barSort)] : []));
      if (!barsEl.hidden) barList.firstChild.scrollIntoView({ behavior: instant ? "auto" : "smooth", block: "nearest" });
    }
    function setBarFocus(title, nodes) { barFocus = title ? { title, nodes } : null; arrangeBars(); }
    function sortBars(k) {
      barSort = k;
      try { localStorage.setItem("sg-bar-sort", k); } catch (e) { /* ignore */ }
      barsEl.querySelectorAll("[data-sort]").forEach(b => b.setAttribute("aria-pressed", b.dataset.sort === k));
      arrangeBars();
    }
    barsEl.querySelectorAll("[data-sort]").forEach(b => b.onclick = () => sortBars(b.dataset.sort));
    sortBars(barSort);

    // ---- interaction ----
    let state = { disc: null, project: null };
    const panel = document.getElementById("sgPanel");

    // ---- phones: the panel is a bottom sheet (CSS). peek = just the handle and title; open = half; full = tall ----
    const sheet = document.getElementById("sgSheet"), grab = sheet.querySelector(".sg-grab");
    const SHEET = ["peek", "open", "full"];
    let sheetState = "peek";
    function setSheet(st) {
      sheetState = st;
      SHEET.forEach(x => sheet.classList.toggle("sheet-" + x, x === st));
      grab.setAttribute("aria-expanded", String(st !== "peek"));
      grab.setAttribute("aria-label", st === "full" ? "Show less" : "Show more details");
      if (st === "peek") sheet.scrollTop = 0;
    }
    setSheet("peek");
    // Tap the handle: peek -> open -> full -> peek. Drag it: up for more, down for less.
    let dragY = null;
    grab.addEventListener("pointerdown", e => { dragY = e.clientY; grab.setPointerCapture(e.pointerId); });
    grab.addEventListener("pointerup", e => {
      if (dragY == null) return;
      const dy = e.clientY - dragY, i = SHEET.indexOf(sheetState);
      dragY = null;
      if (Math.abs(dy) < 12) setSheet(SHEET[(i + 1) % SHEET.length]);
      else setSheet(SHEET[Math.max(0, Math.min(SHEET.length - 1, i + (dy < 0 ? 1 : -1)))]);
    });
    grab.addEventListener("pointercancel", () => { dragY = null; });
    // Peeking: tapping the visible title opens it too.
    sheet.addEventListener("click", e => { if (sheetState === "peek" && !e.target.closest("button, a")) setSheet("open"); });

    // rows: which skill rows to light in the tree view (defaults to set; a level filter passes only the matches).
    function highlight(set, focus, rows = set) {
      svg.classed("dim", !!set.size);
      nodes.classed("on", d => set.has(d));
      links.classed("on", d => set.has(d.target) && set.has(d.source));
      treeEl.classList.toggle("dim", !!set.size);
      tileOf.forEach((el, n) => { el.classList.toggle("on", rows.has(n)); el.classList.toggle("sel", n === focus); });
      // The bars list isn't a hierarchy, so a picked skill is only marked; fading comes from the focus section (arrangeBars).
      barOf.forEach((el, n) => el.classList.toggle("sel", n === focus));
      // Each tab shows how many highlighted skills it holds, so a project's skills are easy to find.
      treeEl.querySelectorAll(".sg-tab").forEach(t => {
        const c = t.querySelector(".sg-tab-count");
        const k = set.size ? [...tileOf.keys()].filter(n => rows.has(n) && n.data.disc === t.dataset.tab).length : 0;
        c.hidden = !k; c.textContent = k;
      });
    }
    function ancestorsOf(list) { const s = new Set(); list.forEach(n => n.ancestors().forEach(a => s.add(a))); return s; }

    function pips(r, disc) {
      let h = `<span class="sg-pips" style="color:${discColor(disc)}">`;
      for (let i = 1; i <= 5; i++) { const full = r >= i, half = !full && r >= i - .5; h += `<span class="sg-pip${half ? " half" : ""}">${full || half ? "<i></i>" : ""}</span>`; }
      return h + "</span>";
    }
    const skillChip = (n, dot) => `<button class="sg-chip" data-skill="${esc(n.data.id)}">${dot ? `<span class="sg-dot" style="background:${discColor(n.data.disc)}"></span>` : ""}${esc(n.data.name)}${dot && n.data.rating != null ? ` · ${n.data.rating}` : ""}</button>`;

    function showDefault() {
      setSheet("peek");
      const top = rated.slice().sort((a, b) => b.data.rating - a.data.rating).slice(0, 6);
      panel.innerHTML = `
        <p class="sg-crumb">OVERVIEW</p>
        <h3>Select a skill or project</h3>
        <p class="sg-empty">Tap any skill to see its rating, what it branches into, and which projects used it.</p>
        ${mixRows()}
        ${top.length ? `<div><p class="sg-section-t">Strongest so far</p><div class="sg-list">${top.map(n => skillChip(n, true)).join("")}</div></div>` : ""}`;
    }
    // A discipline's skills by level: the bar, then one row per band (swatch, level, what it means, count).
    const BAND_NAMES = ["Advanced / Expert", "Proficient", "Beginner", "Aware", ""];
    function levelBreakdown(c, disc) {
      return `<div><p class="sg-section-t">Skills by level</p>
        <span class="sg-mix-track sg-mix-wide">${mixBar(c, disc, sum(c))}</span>
        <ul class="sg-mix-list">${c.map((k, i) => (i === 4 && !k) ? "" : `<li class="${k ? "" : "zero"}">
          <i class="${i === 4 ? "none" : ""}" style="${i < 4 ? `background:color-mix(in srgb, ${discColor(disc)} ${SHADE[i]}%, var(--sg-surface))` : `border-color:${discColor(disc)}`}"></i>
          <span class="sg-mix-lv">${BANDS[i]}</span><span class="sg-mix-name">${BAND_NAMES[i]}</span><b>${k}</b></li>`).join("")}</ul></div>`;
    }
    // Each discipline's skills by level band; strongest (most Lv 4+) first. Each row opens that discipline.
    function mixRows() {
      const rows = root.children.map(h => ({ h, c: discMix(h) })).filter(r => sum(r.c))
        .sort((a, b) => b.c[0] - a.c[0] || sum(b.c) - sum(a.c));
      if (!rows.length) return "";
      const max = Math.max(...rows.map(r => sum(r.c)));
      return `<div><p class="sg-section-t">Skills by discipline and level</p><div class="sg-avgs">${rows.map(({ h, c }) =>
        `<button class="sg-avg" data-hub="${esc(h.data.id)}" title="${esc(mixTitle(h.data.name, c))}">
          <span class="sg-avg-name"><span class="sg-dot" style="background:${discColor(h.data.disc)}"></span>${esc(h.data.name)}</span>
          <span class="sg-mix-track">${mixBar(c, h.data.disc, max)}</span>
          <span class="sg-avg-val">${sum(c)}</span></button>`).join("")}</div>${mixLegend()}</div>`;
    }
    function showNode(n) {
      if (sheetState === "peek") setSheet("open");
      if (n.depth === 0) { clearAll(); return; }
      const d = n.data, path = n.ancestors().reverse().slice(1, -1).map(a => a.data.name);
      const kids = n.children || [];
      const projs = usedIn.get(n) || [];
      const desc = n.descendants().filter(x => x !== n);
      highlight(new Set([...ancestorsOf([n]), ...desc]), n);
      // A discipline gets its own section in the bars view; picking a single skill keeps the current order.
      if (d.kind === "hub") setBarFocus(`${d.name} skills`, desc);
      panel.innerHTML = `
        <button class="sg-close" id="sgClose">Clear</button>
        <p class="sg-crumb">${esc(path.join("  /  ") || "DISCIPLINE")}</p>
        <h3>${esc(d.name)}</h3>
        ${d.blurb ? `<p class="sg-blurb">${esc(d.blurb)}</p>` : ""}
        ${notionLink(d.id)}
        <dl class="sg-kv">
          ${d.kind === "hub" ? (() => {
            return `<dt>Skills</dt><dd>${sum(discMix(n))}</dd>`;
          })() :
            `<dt>Rating</dt><dd>${d.rating != null ? pips(d.rating, d.disc) + `<span style="font-variant-numeric:tabular-nums">${d.rating} / 5</span> <span class="sg-level-name">· ${esc(levelLabel(d.rating))}</span>` : `<span class="sg-empty">Not rated yet</span>`}</dd>`}
        </dl>
        ${d.kind === "hub" ? levelBreakdown(discMix(n), d.disc) : ""}
        <div><p class="sg-section-t">${d.kind === "hub" ? "Branches" : "Branches into"}</p>${kids.length ? `<div class="sg-list">${kids.map(k => skillChip(k)).join("")}</div>` : `<p class="sg-empty">Nothing below this one.</p>`}</div>
        ${d.kind === "hub" ? "" : `<div><p class="sg-section-t">Used in</p>${projs.length ? `<div class="sg-list">${projs.map(p => `<button class="sg-chip" data-project="${esc(p.id)}">${esc(itemTitle(p))}</button>`).join("")}</div>` : `<p class="sg-empty">No projects or experience linked yet.</p>`}</div>`}`;
    }
    function showProject(p) {
      if (sheetState === "peek") setSheet("open");
      highlight(ancestorsOf(p.nodes));
      setBarFocus(p.kind === "project" ? `Used in ${p.name}` : `Used at ${itemTitle(p)}`, p.nodes);
      const by = d3.group(p.nodes, n => n.data.disc);
      const meta = [p.kind !== "project" && p.role, p.kind === "project" && p.organization, dateRange(p)].filter(Boolean);
      panel.innerHTML = `
        <button class="sg-close" id="sgClose">Clear</button>
        <p class="sg-crumb">${KIND_LABEL[p.kind].toUpperCase()}</p>
        <h3>${esc(itemTitle(p))}</h3>
        ${meta.length ? `<p class="sg-meta">${meta.map(esc).join(" · ")}</p>` : ""}
        ${p.blurb ? `<p class="sg-blurb">${esc(p.blurb)}</p>` : ""}
        ${notionLink(p.id)}
        <dl class="sg-kv"><dt>Skills</dt><dd>${p.nodes.length ? `${p.nodes.length} across ${by.size} discipline${by.size === 1 ? "" : "s"}` : "None linked yet"}</dd></dl>
        ${hubs.filter(h => by.has(h.disc)).map(h => `<div><p class="sg-section-t">${esc(h.name)}</p><div class="sg-list">${by.get(h.disc).map(n => skillChip(n, true)).join("")}</div></div>`).join("")}`;
    }
    // Level filter: Lv 3 covers ratings 3 and 3.5; "none" = not rated yet. Several levels can be on at once.
    const levelOf = n => n.data.rating == null ? "none" : String(Math.floor(n.data.rating));
    const levelName = l => l === "none" ? "Unrated" : `Lv ${l}`;
    function showLevels() {
      if (sheetState === "peek") setSheet("open");
      const matches = skills.filter(n => state.levels.has(levelOf(n)))
        .sort((a, b) => (b.data.rating ?? -1) - (a.data.rating ?? -1) || a.data.name.localeCompare(b.data.name));
      highlight(ancestorsOf(matches), null, new Set(matches));
      setBarFocus(`${[...state.levels].sort().map(levelName).join(" + ")} skills`, matches);
      const by = d3.group(matches, n => n.data.disc);
      const names = [...state.levels].sort().map(levelName);
      panel.innerHTML = `
        <button class="sg-close" id="sgClose">Clear</button>
        <p class="sg-crumb">LEVEL FILTER</p>
        <h3>${esc(names.join(" + "))} skills</h3>
        <dl class="sg-kv"><dt>Skills</dt><dd>${matches.length}${matches.length ? ` across ${by.size} discipline${by.size === 1 ? "" : "s"}` : ""}</dd></dl>
        ${matches.length ? hubs.filter(h => by.has(h.disc)).map(h => `<div><p class="sg-section-t">${esc(h.name)}</p><div class="sg-list">${by.get(h.disc).map(n => skillChip(n, true)).join("")}</div></div>`).join("")
          : `<p class="sg-empty">No skills at this level yet.</p>`}`;
    }
    function toggleLevel(l) {
      const levels = new Set(state.levels || []);
      levels.has(l) ? levels.delete(l) : levels.add(l);
      if (!levels.size) return clearAll();
      state = { disc: null, project: null, levels }; syncChips(); showLevels();
    }
    document.querySelectorAll("#levelBar [data-level]").forEach(b => {
      b.onclick = () => toggleLevel(b.dataset.level);
      const l = +b.dataset.level;
      if (LEVELS[l]) b.title = `${LEVELS[l][0]}: ${LEVELS[l][1]} (rated ${l}${l < 5 ? `–${l}.5` : ""})`;
    });
    // Collapsed by default on phones (it's tall there); open on bigger screens.
    document.getElementById("sgLevels").innerHTML = `<details${phone.matches ? "" : " open"}><summary><p class="sg-levels-t">What the levels mean <span>· half steps (e.g. 3.5) sit between two levels</span></p></summary>
      <ol>${Object.entries(LEVELS).map(([l, [name, desc]]) => `<li><b>Lv ${l} · ${name}</b><span>${esc(desc)}</span></li>`).join("")}</ol></details>`;

    function clearAll() {
      state = { disc: null, project: null }; selected = null; prevFilter = null;
      highlight(new Set()); syncChips(); showDefault(); setBarFocus(null);
    }
    function syncChips() {
      document.querySelectorAll("#discBar .sg-chip").forEach(b => b.setAttribute("aria-pressed", b.dataset.disc === state.disc));
      document.querySelectorAll("#projBar .sg-chip, #expBar .sg-chip").forEach(b => b.setAttribute("aria-pressed", b.dataset.project === state.project));
      document.querySelectorAll("#levelBar [data-level]").forEach(b => b.setAttribute("aria-pressed", !!state.levels?.has(b.dataset.level)));
    }
    // selected: the skill open in the panel; prevFilter: the project / level / discipline filter it was picked from,
    // so "back" (empty-space click, Esc, or clicking the same bar again) returns there before clearing everything.
    let selected = null, prevFilter = null;
    function selectNode(n) {
      if (state.disc || state.project || state.levels) prevFilter = state;
      selected = n; state = { disc: null, project: null }; syncChips(); showNode(n);
    }
    function stepBack() {
      const f = prevFilter;
      if (!selected || !f) return clearAll();
      selected = null; prevFilter = null;
      if (f.project) return selectProject(projects.find(p => p.id === f.project));
      state = f; syncChips();
      if (f.levels) return showLevels();
      const h = root.children.find(x => x.data.disc === f.disc); showNode(h); showTab(f.disc);
    }
    barsEl.addEventListener("click", e => { if (!e.target.closest(".sg-bar, .sg-chip")) stepBack(); });
    document.addEventListener("keydown", e => {
      if (e.key !== "Escape" || e.target.closest("input, textarea")) return;
      if (state.disc || state.project || state.levels || selected) stepBack();
      else if (embedded) window.parent.postMessage("sg-close", location.origin);  // nothing left to clear: close the panel
    });
    function selectProject(p) { state = { disc: null, project: p.id }; syncChips(); showProject(p); }

    nodes.on("click", (e, n) => selectNode(n))
      .on("keydown", (e, n) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectNode(n); } });

    const discBar = document.getElementById("discBar");
    root.children.forEach(hubNode => {
      const h = hubNode.data;
      const b = document.createElement("button"); b.className = "sg-chip"; b.dataset.disc = h.disc; b.setAttribute("aria-pressed", "false");
      b.innerHTML = `<span class="sg-dot" style="background:${discColor(h.disc)}"></span>${esc(h.name)}`;
      b.onclick = () => {
        if (state.disc === h.disc) { clearAll(); return; }
        state = { disc: h.disc, project: null }; syncChips(); showNode(hubNode);
        showTab(h.disc);
      };
      discBar.appendChild(b);
    });
    const projBar = document.getElementById("projBar"), expBar = document.getElementById("expBar");
    projBar.hidden = !projects.some(p => p.kind === "project");
    expBar.hidden = !projects.some(p => p.kind !== "project");
    // Same organization twice (e.g. two JPL roles): tell the chips apart by start year.
    const orgCount = d3.rollup(projects, v => v.length, itemTitle);
    projects.forEach(p => {
      const b = document.createElement("button"); b.className = "sg-chip"; b.dataset.project = p.id; b.setAttribute("aria-pressed", "false");
      b.textContent = itemTitle(p) + (p.kind !== "project" && orgCount.get(itemTitle(p)) > 1 && p.start ? ` ’${p.start.slice(2, 4)}` : "");
      if (p.kind !== "project") b.title = [p.role, dateRange(p)].filter(Boolean).join(" · ");
      b.onclick = () => { if (state.project === p.id) { clearAll(); return; } selectProject(p); };
      (p.kind === "project" ? projBar : expBar).appendChild(b);
    });
    panel.addEventListener("click", e => {
      const t = e.target.closest("button"); if (!t) return;
      if (t.id === "sgClose") return clearAll();
      if (t.dataset.skill) { const n = nodeById.get(t.dataset.skill); if (n) selectNode(n); }
      if (t.dataset.hub) {
        const h = root.children.find(x => x.data.id === t.dataset.hub);
        if (h) { state = { disc: h.data.disc, project: null }; syncChips(); showNode(h); showTab(h.data.disc); }
      }
      if (t.dataset.project) { const p = projects.find(x => x.id === t.dataset.project); if (p) selectProject(p); }
    });
    // ---- view switch (Graph / Tree / Bars), remembered per visitor; #tree or #bars in the URL opens that view ----
    const stage = document.querySelector(".sg-stage");
    function setView(v) {
      stage.hidden = v !== "graph"; treeEl.hidden = v !== "tree"; barsEl.hidden = v !== "bars";
      document.querySelectorAll("#viewBar [data-view]").forEach(b => b.setAttribute("aria-pressed", b.dataset.view === v));
      try { localStorage.setItem("sg-view", v); } catch (e) { /* storage blocked; fine */ }
    }
    document.querySelectorAll("#viewBar [data-view]").forEach(b => b.onclick = () => setView(b.dataset.view));
    let saved = null;
    try { saved = localStorage.getItem("sg-view"); } catch (e) { /* ignore */ }
    const VIEWS = ["graph", "tree", "bars"], fromHash = location.hash.slice(1);
    setView(VIEWS.includes(fromHash) ? fromHash : VIEWS.includes(saved) ? saved : "graph");

    // ---- search: type a name, pick a result to select it (and bring it into view) ----
    const searchEl = document.getElementById("sgSearch"), resultsEl = document.getElementById("sgResults");
    const searchIndex = [
      ...root.descendants().slice(1).map(n => ({
        name: n.data.name, node: n, disc: n.data.disc,
        where: n.depth === 1 ? "Discipline" : n.ancestors().reverse().slice(1, -1).map(a => a.data.name).join(" / ")
      })),
      ...projects.map(p => ({ name: itemTitle(p), project: p, where: p.kind === "project" ? "Project" : [KIND_LABEL[p.kind], p.role].filter(Boolean).join(" · ") }))
    ];
    let matches = [], active = 0;
    function showResults() {
      const q = searchEl.value.trim().toLowerCase();
      matches = !q ? [] : searchIndex
        .map(it => ({ it, at: it.name.toLowerCase().indexOf(q) }))
        .filter(m => m.at >= 0)
        .sort((a, b) => (a.at !== 0) - (b.at !== 0) || a.it.name.localeCompare(b.it.name))
        .slice(0, 8).map(m => m.it);
      active = 0;
      resultsEl.innerHTML = matches.length ? matches.map((m, i) => `<li role="option" id="sgOpt${i}" data-i="${i}" aria-selected="${i === active}">
          ${m.disc ? `<span class="sg-dot" style="background:${discColor(m.disc)}"></span>` : `<span class="sg-dot sg-dot-proj"></span>`}
          <span class="sg-r-name">${esc(m.name)}</span><span class="sg-r-where">${esc(m.where)}</span></li>`).join("")
        : q ? `<li class="sg-r-none">No matches</li>` : "";
      resultsEl.hidden = !q;
      searchEl.setAttribute("aria-expanded", String(!!q));
      searchEl.setAttribute("aria-activedescendant", matches.length ? "sgOpt0" : "");
    }
    function setActive(i) {
      if (!matches.length) return;
      active = (i + matches.length) % matches.length;
      resultsEl.querySelectorAll("[data-i]").forEach(li => li.setAttribute("aria-selected", String(+li.dataset.i === active)));
      searchEl.setAttribute("aria-activedescendant", "sgOpt" + active);
    }
    function bringIntoView(n) {
      showTab(n.data.disc);
      if (!barsEl.hidden) { barOf.get(n)?.scrollIntoView({ behavior: instant ? "auto" : "smooth", block: "center" }); return; }
      if (!treeEl.hidden) { tileOf.get(n)?.scrollIntoView({ behavior: instant ? "auto" : "smooth", block: "center" }); return; }
      // Graph: center the node, zooming in a little for skills so its neighborhood is readable.
      const k = Math.max(d3.zoomTransform(svg.node()).k, n.depth === 1 ? 1 : 1.6);
      const px = n.y * Math.cos(n.x - Math.PI / 2), py = n.y * Math.sin(n.x - Math.PI / 2);
      svg.transition().duration(instant ? 0 : 600).call(zoom.transform, d3.zoomIdentity.scale(k).translate(-px, -py));
    }
    function pick(m) {
      if (!m) return;
      if (m.project) selectProject(m.project);
      else { selectNode(m.node); bringIntoView(m.node); }
      searchEl.value = m.name; resultsEl.hidden = true; searchEl.setAttribute("aria-expanded", "false");
    }
    searchEl.addEventListener("input", showResults);
    searchEl.addEventListener("focus", () => { if (searchEl.value) showResults(); });
    searchEl.addEventListener("keydown", e => {
      if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
      else if (e.key === "Enter") { e.preventDefault(); pick(matches[active]); }
      else if (e.key === "Escape") { resultsEl.hidden = true; searchEl.setAttribute("aria-expanded", "false"); }
    });
    // mousedown (not click) so the pick happens before the input loses focus
    resultsEl.addEventListener("mousedown", e => {
      const li = e.target.closest("[data-i]");
      if (li) { e.preventDefault(); pick(matches[+li.dataset.i]); }
    });
    searchEl.addEventListener("blur", () => { resultsEl.hidden = true; searchEl.setAttribute("aria-expanded", "false"); });

    showDefault();

    // Deep links from the homepage: #skill=<id> selects a skill, #item=<id> a project / job / degree, #disc=<key> a
    // discipline. Also followed while open (the homepage panel changes the hash to point somewhere new).
    function followLink() {
      const link = new URLSearchParams(location.hash.slice(1));
      const item = projects.find(p => p.id === link.get("item")), skill = nodeById.get(link.get("skill"));
      const hub = root.children.find(h => h.data.disc === link.get("disc"));
      if (item) selectProject(item);
      else if (skill) { selectNode(skill); bringIntoView(skill); }
      else if (hub) { state = { disc: hub.data.disc, project: null }; syncChips(); showNode(hub); showTab(hub.data.disc); }
      else return;
      // In the panel, drop the hash once used so clicking the same homepage link again still works.
      if (embedded) history.replaceState(null, "", location.pathname + location.search);
    }
    followLink();
    window.addEventListener("hashchange", followLink);
  }
})();
