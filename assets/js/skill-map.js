/**
 * About section: hovering (or focusing) a "What I do" row or a skill map legend entry lights up its disciplines in
 * the skill map (elements with data-discs="mech elec" light the map's <g data-d="mech"> and <g data-d="elec">).
 * Clicking either opens the skill graph pop-up (site-popups.js handles the skills.html links).
 */
(function () {
  "use strict";

  const row = document.querySelector(".intro-row"), svg = row && row.querySelector(".sm-svg");
  if (!svg) return;
  const groups = svg.querySelectorAll("[data-d]"), triggers = row.querySelectorAll("[data-discs]");

  function light(el) {
    const discs = el ? el.dataset.discs.split(" ") : [];
    svg.classList.toggle("sm-dim", discs.length > 0);
    groups.forEach(g => g.classList.toggle("lit", discs.includes(g.dataset.d)));
    // The hovered row itself, plus the legend entries of the disciplines it lights.
    triggers.forEach(t => t.classList.toggle("lit", t === el || (!!t.closest(".sm-legend") && discs.includes(t.dataset.discs))));
  }

  row.addEventListener("mouseover", e => light(e.target.closest("[data-discs]")));
  row.addEventListener("mouseleave", () => light(null));
  row.addEventListener("focusin", e => light(e.target.closest("[data-discs]")));
  row.addEventListener("focusout", () => light(null));
})();
