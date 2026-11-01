/**
 * Resume (index.html #resume): each job's bullets start folded. The chevron in the card's header, or a click
 * anywhere on the header, opens or closes them; a timeline row, a "Worked at" logo or any #exp-<id> link scrolls
 * to the job and opens it.
 */
(function () {
  "use strict";

  const instant = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function setOpen(card, open) {
    const btn = card.querySelector(".exp-toggle"), more = card.querySelector(".exp-more");
    if (!btn || !more) return;
    more.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
  }

  function openJob(id, scroll) {
    const card = document.getElementById(id);
    if (!card || !card.classList.contains("experience-card")) return false;
    setOpen(card, true);
    if (scroll) {
      // Measured from the layout (offsetTop), not the card's on-screen box: the card may still be shrunk for its
      // zoom-in animation. Same approach as main.js's section links.
      let top = 0;
      for (let el = card; el; el = el.offsetParent) top += el.offsetTop;
      top -= parseInt(getComputedStyle(card).scrollMarginTop, 10) || 0;
      window.scrollTo({ top, behavior: instant ? "instant" : "smooth" });
    }
    card.classList.add("exp-flash");
    setTimeout(() => card.classList.remove("exp-flash"), 1600);
    return true;
  }

  document.addEventListener("click", e => {
    const row = e.target.closest('a[href^="#exp-"]');  // timeline rows, the "Worked at" logos
    if (row) {
      if (openJob(row.getAttribute("href").slice(1), true)) {
        e.preventDefault();
        history.replaceState(history.state, "", row.getAttribute("href"));
      }
      return;
    }
    // The chevron, or anywhere else on the header (links inside it, if any, still work).
    const head = e.target.closest(".experience-card .card-header");
    if (head && !e.target.closest("a")) {
      const card = head.closest(".experience-card"), btn = card.querySelector(".exp-toggle");
      if (btn) setOpen(card, btn.getAttribute("aria-expanded") !== "true");
    }
  });

  if (/^#exp-[0-9a-f]+$/.test(location.hash)) openJob(location.hash.slice(1), false);
})();
