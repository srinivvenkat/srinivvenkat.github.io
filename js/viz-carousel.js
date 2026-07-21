/*
 * Turns the two home-page visualizations (Research Themes word cloud and the
 * Collaboration Network) into a single tabbed carousel: one is shown at a time
 * and a tab toggles between them, instead of both stacking down the page.
 *
 * Progressive enhancement: the markup ships with both panels present, each with
 * its own <h2>, and an empty tablist. This script builds the tabs (labelled from
 * each panel's <h2>, which it then hides), wires an ARIA tab pattern with arrow-key
 * navigation, and flips the container into "enhanced" mode. With JS off, nothing
 * runs and the two panels simply stack — both fully usable.
 *
 * Important: the inactive panel is hidden via CSS visibility (see .viz-panel in
 * style.css), NOT the [hidden] attribute / display:none. The word cloud and the
 * network both measure text with getBBox when they render, and a display:none
 * ancestor makes getBBox return zeros. visibility:hidden keeps layout intact for
 * measuring while still removing the panel from the accessibility tree.
 */
(function () {
  "use strict";

  function init() {
    var root = document.getElementById("research-viz");
    if (!root) return;
    var tablist = root.querySelector(".viz-tabs");
    var panels = Array.prototype.slice.call(root.querySelectorAll(".viz-panel"));
    if (!tablist || panels.length < 2) return;

    var tabs = [];

    panels.forEach(function (panel, i) {
      var titleEl = panel.querySelector(".viz-panel-title");
      var label = titleEl ? titleEl.textContent.trim() : "View " + (i + 1);
      if (titleEl) titleEl.hidden = true; // the tab now serves as the panel's heading

      if (!panel.id) panel.id = "viz-panel-" + i;
      var tabId = panel.id + "-tab";

      var tab = document.createElement("button");
      tab.type = "button";
      tab.className = "viz-tab";
      tab.id = tabId;
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", panel.id);
      tab.textContent = label;
      tablist.appendChild(tab);
      tabs.push(tab);

      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", tabId);
      panel.setAttribute("tabindex", "0");
    });

    function select(idx, focus) {
      tabs.forEach(function (tab, i) {
        var on = i === idx;
        tab.setAttribute("aria-selected", on ? "true" : "false");
        tab.tabIndex = on ? 0 : -1;            // roving tabindex
        panels[i].classList.toggle("is-active", on);
      });
      if (focus) tabs[idx].focus();
    }

    tabs.forEach(function (tab, i) {
      tab.addEventListener("click", function () { select(i, false); });
      tab.addEventListener("keydown", function (e) {
        var idx = null;
        if (e.key === "ArrowRight" || e.key === "ArrowDown") idx = (i + 1) % tabs.length;
        else if (e.key === "ArrowLeft" || e.key === "ArrowUp") idx = (i - 1 + tabs.length) % tabs.length;
        else if (e.key === "Home") idx = 0;
        else if (e.key === "End") idx = tabs.length - 1;
        if (idx !== null) { e.preventDefault(); select(idx, true); }
      });
    });

    select(0, false);          // Research Themes shown first
    root.classList.add("viz-enhanced");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
