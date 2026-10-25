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
  if (ownerParam !== null) history.replaceState(null, "", location.pathname + location.hash);
  const notionLink = id => owner && /^[0-9a-f]{32}$/.test(id || "")
    ? `<a class="sg-notion" href="https://www.notion.so/${id}" target="_blank" rel="noopener">Open in Notion ↗</a>` : "";

  // What each rating level means (shown in the legend, panel and tooltips). Half steps sit between two levels.
  const LEVELS = {
    1: ["Aware", "Limited knowledge: I understand the concept and when it's used"],
    2: ["Beginner", "Hands-on basics, done with guides or tutorials"],
    3: ["Proficient", "Use it on my own projects without help"],
    4: ["Advanced", "Handle complex problems and can teach others"],
    5: ["Expert", "Deep mastery; I'm the go-to person for it"]
  };
  const levelLabel = r => r == null ? "Not rated yet"
    : Number.isInteger(r) ? LEVELS[r][0] : `${LEVELS[Math.floor(r)][0]} → ${LEVELS[Math.ceil(r)][0]}`;

  const discColor = k => `var(--c-${k})`;
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
    const projects = data.projects.map(p => ({ ...p, nodes: p.skills.map(id => nodeById.get(id)).filter(Boolean) }));
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
    document.getElementById("sgStats").innerHTML =
      `<div><b>${skills.length}</b>skills</div><div><b>${hubs.length}</b>disciplines</div><div><b>${projects.length}</b>projects</div><div><b>${rated.length}</b>rated</div>`;
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
    const totalSP = learned.reduce((t, n) => t + n.data.rating, 0);
    treeEl.innerHTML = `
      <div class="sg-win-title"><span>SKILL</span><span class="sg-win-x" aria-hidden="true">×</span></div>
      <div class="sg-char">
        <div class="sg-portrait"><img src="assets/img/misc/stephen_maple.jpg" alt="Stephen's MapleStory-style character" width="735" height="1307"></div>
        <dl class="sg-char-stats">
          <div><dt>Name</dt><dd>prettygoodengineer</dd></div>
          <div><dt>Job</dt><dd>Robotics Engineer</dd></div>
          <div><dt>Skills learned</dt><dd>${learned.length} / ${allSkills.length}</dd></div>
          <div><dt>Skill points</dt><dd>${Number.isInteger(totalSP) ? totalSP : totalSP.toFixed(1)} / ${allSkills.length * 5}</dd></div>
        </dl>
      </div>
      <div class="sg-tabs" role="tablist">${root.children.map(h => `<button class="sg-tab" role="tab" id="sgTab-${h.data.disc}" aria-controls="sgPane-${h.data.disc}" data-tab="${h.data.disc}" style="--c:${discColor(h.data.disc)}">
          <span class="sg-dot" style="background:${discColor(h.data.disc)}"></span>${esc(h.data.name)}<span class="sg-tab-count" hidden></span></button>`).join("")}</div>
      ${root.children.map(h => {
        const all = h.descendants().slice(1), got = all.filter(n => n.data.rating != null).length;
        return `<div class="sg-pane" role="tabpanel" id="sgPane-${h.data.disc}" aria-labelledby="sgTab-${h.data.disc}" data-disc="${h.data.disc}" style="--c:${discColor(h.data.disc)}" hidden>
          <p class="sg-pane-meta">${got} of ${all.length} ${esc(h.data.name.toLowerCase())} skills learned${h.data.blurb ? ` · ${esc(h.data.blurb)}` : ""}</p>
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

    // ---- interaction ----
    let state = { disc: null, project: null };
    const panel = document.getElementById("sgPanel");

    // rows: which skill rows to light in the tree view (defaults to set; a level filter passes only the matches).
    function highlight(set, focus, rows = set) {
      svg.classed("dim", !!set.size);
      nodes.classed("on", d => set.has(d));
      links.classed("on", d => set.has(d.target) && set.has(d.source));
      treeEl.classList.toggle("dim", !!set.size);
      tileOf.forEach((el, n) => { el.classList.toggle("on", rows.has(n)); el.classList.toggle("sel", n === focus); });
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
      const top = rated.slice().sort((a, b) => b.data.rating - a.data.rating).slice(0, 6);
      panel.innerHTML = `
        <p class="sg-crumb">OVERVIEW</p>
        <h3>Select a skill or project</h3>
        <p class="sg-empty">Tap any skill to see its rating, what it branches into, and which projects used it.</p>
        ${top.length ? `<div><p class="sg-section-t">Strongest so far</p><div class="sg-list">${top.map(n => skillChip(n, true)).join("")}</div></div>` : ""}`;
    }
    function showNode(n) {
      if (n.depth === 0) { clearAll(); return; }
      const d = n.data, path = n.ancestors().reverse().slice(1, -1).map(a => a.data.name);
      const kids = n.children || [];
      const projs = usedIn.get(n) || [];
      const desc = n.descendants().filter(x => x !== n);
      highlight(new Set([...ancestorsOf([n]), ...desc]), n);
      panel.innerHTML = `
        <button class="sg-close" id="sgClose">Clear</button>
        <p class="sg-crumb">${esc(path.join("  /  ") || "DISCIPLINE")}</p>
        <h3>${esc(d.name)}</h3>
        ${d.blurb ? `<p class="sg-blurb">${esc(d.blurb)}</p>` : ""}
        ${notionLink(d.id)}
        <dl class="sg-kv">
          ${d.kind === "hub" ? `<dt>Skills</dt><dd>${desc.length}</dd>` :
            `<dt>Rating</dt><dd>${d.rating != null ? pips(d.rating, d.disc) + `<span style="font-variant-numeric:tabular-nums">${d.rating} / 5</span> <span class="sg-level-name">· ${esc(levelLabel(d.rating))}</span>` : `<span class="sg-empty">Not rated yet</span>`}</dd>`}
        </dl>
        <div><p class="sg-section-t">${d.kind === "hub" ? "Branches" : "Branches into"}</p>${kids.length ? `<div class="sg-list">${kids.map(k => skillChip(k)).join("")}</div>` : `<p class="sg-empty">Nothing below this one.</p>`}</div>
        ${d.kind === "hub" ? "" : `<div><p class="sg-section-t">Used in</p>${projs.length ? `<div class="sg-list">${projs.map(p => `<button class="sg-chip" data-project="${esc(p.id)}">${esc(p.name)}</button>`).join("")}</div>` : `<p class="sg-empty">No projects linked yet.</p>`}</div>`}`;
    }
    function showProject(p) {
      highlight(ancestorsOf(p.nodes));
      const by = d3.group(p.nodes, n => n.data.disc);
      panel.innerHTML = `
        <button class="sg-close" id="sgClose">Clear</button>
        <p class="sg-crumb">PROJECT</p>
        <h3>${esc(p.name)}</h3>
        ${p.blurb ? `<p class="sg-blurb">${esc(p.blurb)}</p>` : ""}
        ${notionLink(p.id)}
        <dl class="sg-kv"><dt>Skills</dt><dd>${p.nodes.length} across ${by.size} discipline${by.size === 1 ? "" : "s"}</dd></dl>
        ${hubs.filter(h => by.has(h.disc)).map(h => `<div><p class="sg-section-t">${esc(h.name)}</p><div class="sg-list">${by.get(h.disc).map(n => skillChip(n, true)).join("")}</div></div>`).join("")}`;
    }
    // Level filter: Lv 3 covers ratings 3 and 3.5; "none" = not rated yet. Several levels can be on at once.
    const levelOf = n => n.data.rating == null ? "none" : String(Math.floor(n.data.rating));
    const levelName = l => l === "none" ? "Unrated" : `Lv ${l}`;
    function showLevels() {
      const matches = skills.filter(n => state.levels.has(levelOf(n)))
        .sort((a, b) => (b.data.rating ?? -1) - (a.data.rating ?? -1) || a.data.name.localeCompare(b.data.name));
      highlight(ancestorsOf(matches), null, new Set(matches));
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
    document.getElementById("sgLevels").innerHTML = `<p class="sg-levels-t">What the levels mean <span>· half steps (e.g. 3.5) sit between two levels</span></p>
      <ol>${Object.entries(LEVELS).map(([l, [name, desc]]) => `<li><b>Lv ${l} · ${name}</b><span>${esc(desc)}</span></li>`).join("")}</ol>`;

    function clearAll() {
      state = { disc: null, project: null };
      highlight(new Set()); syncChips(); showDefault();
    }
    function syncChips() {
      document.querySelectorAll("#discBar .sg-chip").forEach(b => b.setAttribute("aria-pressed", b.dataset.disc === state.disc));
      document.querySelectorAll("#projBar .sg-chip").forEach(b => b.setAttribute("aria-pressed", b.dataset.project === state.project));
      document.querySelectorAll("#levelBar [data-level]").forEach(b => b.setAttribute("aria-pressed", !!state.levels?.has(b.dataset.level)));
    }
    function selectNode(n) { state = { disc: null, project: null }; syncChips(); showNode(n); }
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
    const projBar = document.getElementById("projBar");
    if (!projects.length) projBar.hidden = true;
    projects.forEach(p => {
      const b = document.createElement("button"); b.className = "sg-chip"; b.dataset.project = p.id; b.setAttribute("aria-pressed", "false");
      b.textContent = p.name;
      b.onclick = () => { if (state.project === p.id) { clearAll(); return; } selectProject(p); };
      projBar.appendChild(b);
    });
    panel.addEventListener("click", e => {
      const t = e.target.closest("button"); if (!t) return;
      if (t.id === "sgClose") return clearAll();
      if (t.dataset.skill) { const n = nodeById.get(t.dataset.skill); if (n) selectNode(n); }
      if (t.dataset.project) { const p = projects.find(x => x.id === t.dataset.project); if (p) selectProject(p); }
    });
    // ---- view switch (Graph / Tree), remembered per visitor; #tree in the URL opens the tree ----
    const stage = document.querySelector(".sg-stage");
    function setView(v) {
      stage.hidden = v !== "graph"; treeEl.hidden = v !== "tree";
      document.querySelectorAll("#viewBar [data-view]").forEach(b => b.setAttribute("aria-pressed", b.dataset.view === v));
      try { localStorage.setItem("sg-view", v); } catch (e) { /* storage blocked; fine */ }
    }
    document.querySelectorAll("#viewBar [data-view]").forEach(b => b.onclick = () => setView(b.dataset.view));
    let saved = null;
    try { saved = localStorage.getItem("sg-view"); } catch (e) { /* ignore */ }
    setView(location.hash === "#tree" ? "tree" : location.hash === "#graph" ? "graph" : saved === "tree" ? "tree" : "graph");

    // ---- search: type a name, pick a result to select it (and bring it into view) ----
    const searchEl = document.getElementById("sgSearch"), resultsEl = document.getElementById("sgResults");
    const searchIndex = [
      ...root.descendants().slice(1).map(n => ({
        name: n.data.name, node: n, disc: n.data.disc,
        where: n.depth === 1 ? "Discipline" : n.ancestors().reverse().slice(1, -1).map(a => a.data.name).join(" / ")
      })),
      ...projects.map(p => ({ name: p.name, project: p, where: "Project" }))
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
    const instant = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    function bringIntoView(n) {
      showTab(n.data.disc);
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
  }
})();
