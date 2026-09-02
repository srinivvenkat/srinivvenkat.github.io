/*
 * A GitHub-contributions-style grid over the publication list: rows are the four
 * categories, columns are years, and the shade of a cell is how many papers fall
 * in that category and year. Picking a cell jumps to that year's entries, and a
 * row label jumps to the category, which is why this replaced the list of
 * category links that used to head the page.
 *
 * Everything is read from the page itself at load time (each <section id> with a
 * .pub-list, its <h3 class="pub-year"> headings and the <li> entries under each),
 * so the grid can never disagree with the list below it and no build step or data
 * file has to be regenerated when a paper is added.
 *
 * Cells carry their count as a number as well as a shade, so the grid is readable
 * without relying on color alone, and the whole thing is a real <table> with row
 * and column headers for screen readers. Progressive enhancement: with JS off the
 * publication list renders exactly as before, just without the overview.
 */
(function () {
  "use strict";

  // Sequential single-hue ramp (UVA navy, light to dark). Four steps, each paired
  // with the ink that clears WCAG AA on it: navy on the two light steps, white on
  // the two dark ones.
  var LEVELS = 4;

  // The <h2> of a section is the honest label but too long for a row header on a
  // phone; these are the same names, shortened. Anything not listed falls back to
  // its <h2> text.
  var SHORT_LABELS = {
    "book-chapters": "Book Chapters",
    "journal-articles": "Journal Articles",
    "conference-papers": "Conferences & Workshops",
    "tech-reports": "Reports & Preprints"
  };

  function prefersReducedMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  // One row per publication section: its label, and a year -> {count, heading} map.
  function collect() {
    var rows = [];
    document.querySelectorAll("main section[id]").forEach(function (section) {
      if (!section.querySelector("ol.pub-list")) return;
      var h2 = section.querySelector("h2");
      var years = Object.create(null);
      section.querySelectorAll("h3.pub-year").forEach(function (h3) {
        var year = parseInt(h3.textContent.trim(), 10);
        var ol = h3.nextElementSibling;
        if (!year || !ol || !ol.classList.contains("pub-list")) return;
        var count = ol.querySelectorAll("li").length;
        if (!count) return;
        // A year heading appears once per section, but summing is harmless and
        // keeps the grid right if one is ever split across two lists.
        if (years[year]) years[year].count += count;
        else years[year] = { count: count, heading: h3 };
      });
      if (!Object.keys(years).length) return;
      rows.push({
        id: section.id,
        label: SHORT_LABELS[section.id] || (h2 ? h2.textContent.trim() : section.id),
        fullLabel: h2 ? h2.textContent.trim() : section.id,
        years: years
      });
    });
    return rows;
  }

  // Every year from the earliest to the latest, gaps included: a blank column is
  // information too, and skipping it would distort the timeline.
  function yearRange(rows) {
    var min = Infinity, max = -Infinity;
    rows.forEach(function (row) {
      Object.keys(row.years).forEach(function (y) {
        var year = parseInt(y, 10);
        if (year < min) min = year;
        if (year > max) max = year;
      });
    });
    if (!isFinite(min)) return [];
    var years = [];
    for (var y = min; y <= max; y++) years.push(y);
    return years;
  }

  /* Shades are quantile bins, not a straight count/max split. Publication counts
     are heavily skewed (a dozen cells hold one paper, one holds ten), so a linear
     ramp would paint almost the whole grid in the lightest shade and waste the
     other three. Cutting at the quartiles of the non-empty cells spreads the four
     steps across the years that actually differ; the exact number is printed in
     the cell either way, so no magnitude is lost to the binning. */
  function buildScale(counts) {
    var sorted = counts.slice().sort(function (a, b) { return a - b; });
    var cuts = [];
    for (var i = 1; i < LEVELS; i++) {
      cuts.push(sorted[Math.floor((i / LEVELS) * (sorted.length - 1))]);
    }
    return function (count) {
      if (!count) return 0;
      var level = 1;
      cuts.forEach(function (cut) { if (count > cut) level++; });
      return Math.min(LEVELS, level);
    };
  }

  function plural(n, word) {
    return n + " " + word + (n === 1 ? "" : "s");
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  // Year headings have no ids in the markup, so mint one per cell target here.
  function anchorFor(row, year, heading) {
    var id = row.id + "-" + year;
    if (!heading.id) heading.id = id;
    return heading.id;
  }

  function flash(heading) {
    var ol = heading.nextElementSibling;
    [heading, ol].forEach(function (node) {
      if (!node) return;
      node.classList.remove("pub-flash");
      // Restart the animation even when the same cell is picked twice in a row.
      void node.offsetWidth;
      node.classList.add("pub-flash");
    });
  }

  function buildTable(rows, years, levelFor) {
    var table = el("table", "pub-heatmap-table");
    var caption = el("caption", "sr-only",
      "Publication counts by category and year, " + years[0] + " to " + years[years.length - 1] +
      ". Each cell links to that year's entries.");
    table.appendChild(caption);

    var thead = document.createElement("thead");
    var headRow = document.createElement("tr");
    headRow.appendChild(el("th", "pub-heatmap-corner", "Category"));
    years.forEach(function (year) {
      var th = el("th", "pub-heatmap-year", String(year));
      th.scope = "col";
      headRow.appendChild(th);
    });
    var totalHead = el("th", "pub-heatmap-total-head", "Total");
    totalHead.scope = "col";
    headRow.appendChild(totalHead);
    thead.appendChild(headRow);
    table.appendChild(thead);

    var tbody = document.createElement("tbody");
    rows.forEach(function (row) {
      var tr = document.createElement("tr");
      var th = el("th", "pub-heatmap-row-head");
      th.scope = "row";
      var rowLink = el("a", null, row.label);
      rowLink.href = "#" + row.id;
      th.appendChild(rowLink);
      tr.appendChild(th);

      var total = 0;
      years.forEach(function (year) {
        var cell = row.years[year];
        var count = cell ? cell.count : 0;
        total += count;
        var td = el("td", "pub-heatmap-cell lvl-" + levelFor(count));
        if (!count) {
          td.appendChild(el("span", "sr-only", "none"));
          tr.appendChild(td);
          return;
        }
        var id = anchorFor(row, year, cell.heading);
        var link = el("a", null, String(count));
        link.href = "#" + id;
        link.title = row.fullLabel + " · " + year + " · " + plural(count, "publication");
        link.setAttribute("aria-label",
          plural(count, "publication") + " in " + row.fullLabel + ", " + year);
        link.addEventListener("click", function () {
          // The hash jump does the scrolling; this only marks where you landed.
          if (!prefersReducedMotion()) flash(cell.heading);
        });
        td.appendChild(link);
        tr.appendChild(td);
      });

      tr.appendChild(el("td", "pub-heatmap-total", String(total)));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return table;
  }

  function init() {
    var rows = collect();
    if (rows.length < 2) return;
    var years = yearRange(rows);
    if (years.length < 2) return;

    var counts = [];
    rows.forEach(function (row) {
      Object.keys(row.years).forEach(function (y) { counts.push(row.years[y].count); });
    });
    if (!counts.length) return;
    var levelFor = buildScale(counts);

    var section = el("section", "pub-heatmap");
    section.setAttribute("aria-labelledby", "pub-heatmap-heading");
    var heading = el("h2", "pub-heatmap-heading", "At a glance");
    heading.id = "pub-heatmap-heading";
    section.appendChild(heading);
    var scroller = el("div", "pub-heatmap-scroll");
    scroller.setAttribute("tabindex", "0");
    scroller.setAttribute("role", "region");
    scroller.setAttribute("aria-label", "Publication heatmap");
    scroller.appendChild(buildTable(rows, years, levelFor));
    section.appendChild(scroller);

    // Top of the page: this grid replaced the category chips that used to sit
    // there, and pub-search.js anchors its toolbar below it.
    var main = document.querySelector("main .container") || document.querySelector("main");
    if (!main) return;
    main.insertBefore(section, main.firstChild);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
