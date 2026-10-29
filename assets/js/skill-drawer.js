/**
 * Skill graph slide-out (index.html): any link to skills.html opens the graph in a panel over the page
 * instead of navigating away. skills.html#skill=<id> / #item=<id> / #disc=<key> links open it at that spot.
 * The panel loads skills.html?embed=1 in an iframe the first time it opens, so the homepage stays light.
 * While open the address ends in #skill-graph, so the back button closes it and the link can be shared.
 * Ctrl/Cmd-click or middle-click still opens skills.html in a new tab.
 */
(function () {
  "use strict";

  const drawer = document.getElementById("sgDrawer");
  if (!drawer) return;
  const HASH = "#skill-graph";
  const body = drawer.querySelector(".sg-drawer-body");
  const instant = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let frame = null, opener = null;

  function open(hash, push = true) {
    if (!frame) {
      frame = document.createElement("iframe");
      frame.title = "Skill graph";
      frame.src = "skills.html?embed=1" + (hash || "");
      frame.addEventListener("load", () => drawer.classList.add("loaded"));
      body.appendChild(frame);
    } else if (hash) {
      // Already loaded: the graph listens for hash changes and selects the linked skill / item.
      frame.contentWindow.location.hash = hash.slice(1);
    }
    if (!drawer.hidden) return;
    opener = document.activeElement;
    drawer.hidden = false;
    requestAnimationFrame(() => drawer.classList.add("open"));
    document.documentElement.classList.add("sg-drawer-open");
    if (push && location.hash !== HASH) history.pushState({ sgDrawer: true }, "", HASH);
    drawer.querySelector(".sg-drawer-close").focus({ preventScroll: true });
  }

  function hide() {
    if (drawer.hidden) return;
    drawer.classList.remove("open");
    document.documentElement.classList.remove("sg-drawer-open");
    setTimeout(() => { if (!drawer.classList.contains("open")) drawer.hidden = true; }, instant ? 0 : 300);
    if (opener && opener.focus) opener.focus({ preventScroll: true });
  }

  // Closing goes "back" when we added the history entry, so back/forward stay in step with the panel.
  function close() {
    if (history.state && history.state.sgDrawer) history.back();
    else {
      hide();
      if (location.hash === HASH) history.replaceState(null, "", location.pathname + location.search);
    }
  }

  window.addEventListener("popstate", () => (location.hash === HASH ? open(null, false) : hide()));

  document.addEventListener("click", e => {
    if (e.target.closest("[data-close]")) return close();
    const a = e.target.closest('a[href^="skills.html"]');
    if (!a || a.target === "_blank" || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    open(new URL(a.href).hash);
  });

  document.addEventListener("keydown", e => {
    if (drawer.hidden) return;
    if (e.key === "Escape") close();
    // Keep Tab inside the panel's own bar (the iframe takes focus on click).
    if (e.key === "Tab") {
      const f = [...drawer.querySelectorAll("a[href], button, iframe")];
      const i = f.indexOf(document.activeElement);
      if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus(); }
    }
  });

  // Esc inside the graph with nothing left to clear asks to close the panel.
  window.addEventListener("message", e => { if (e.origin === location.origin && e.data === "sg-close") close(); });

  if (location.hash === HASH) open(null, false);
})();
