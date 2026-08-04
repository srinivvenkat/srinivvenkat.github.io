/*
 * On-page search and filtering for publications.html.
 *
 * Adds a toolbar above the list with a free-text search box, a type select (the
 * four category sections) and a year select, plus a live count. 104 entries are
 * a lot to scan, and until now the only way to narrow them was to arrive from
 * elsewhere carrying a ?term=/?author=/?topic= parameter — someone landing on
 * this page directly had no control at all.
 *
 * RELATIONSHIP TO pub-filter.js
 * Two independent layers, composed by CSS rather than coordinated in code:
 *   pub-filter.js  hides via the `hidden` PROPERTY  (URL-parameter filtering)
 *   this file      hides via the `is-filtered-out` CLASS
 * An element stays hidden while either layer hides it, and each layer only ever
 * restores what it hid itself, so neither can clobber the other. Arriving with
 * ?topic=epi and then typing narrows within that topic, which is what you would
 * want; the banner's "Show all" still restores the topic layer independently.
 * Deciding whether a row is currently visible therefore has to consult BOTH
 * layers — see isVisible().
 *
 * The toolbar is built here rather than sitting in the HTML so that with JS off
 * there are no dead controls, matching how viz-carousel.js builds its tabs.
 *
 * The search index is the citation text only, with the Abstract and BibTeX
 * disclosures excluded, plus the full author list from paper-authors.json. Full
 * authors matter because long lists are condensed to "..." in the markup, so
 * without them searching for a middle author of a 30-author paper would silently
 * fail. Abstract text is deliberately NOT indexed: it loads asynchronously, so
 * including it would make results depend on fetch timing, and the home-page word
 * cloud already offers abstract-level entry into this list.
 *
 * Progressive enhancement: if any fetch fails or JS is off, the full list renders
 * normally, just without the toolbar.
 */
(function () {
  "use strict";

  var AUTHORS = "paper-authors.json";
  var HIDDEN = "is-filtered-out";
  var DEBOUNCE = 120;

  var rows = [];      // { li, ol, heading, section, year, text }
  var toolbar = null;
  var qInput = null, typeSel = null, yearSel = null, countEl = null;
  var timer = null;

  // Visible means: hidden by neither layer. pub-filter.js owns the property,
  // this file owns the class.
  function isVisible(el) {
    return !el.hidden && !el.classList.contains(HIDDEN);
  }

  function setHidden(el, on) {
    if (!el) return;
    el.classList.toggle(HIDDEN, on);
  }

  function collect() {
    var out = [];
    document.querySelectorAll("main section").forEach(function (section) {
      if (!section.querySelector(".pub-list")) return;
      section.querySelectorAll("ol.pub-list, ul.pub-list").forEach(function (ol) {
        var prev = ol.previousElementSibling;
        var heading = prev && prev.classList.contains("pub-year") ? prev : null;
        var year = heading ? heading.textContent.trim() : "";
        ol.querySelectorAll("li").forEach(function (li) {
          out.push({ li: li, ol: ol, heading: heading, section: section, year: year, text: "" });
        });
      });
    });
    return out;
  }

  // Citation text without the disclosures, which are appended asynchronously.
  function citationText(li) {
    var clone = li.cloneNode(true);
    clone.querySelectorAll(".abs, .bib").forEach(function (n) { n.remove(); });
    return clone.textContent.replace(/\s+/g, " ").trim().toLowerCase();
  }

  function indexRows(authorsByKey) {
    rows.forEach(function (row) {
      var extra = "";
      var key = row.section.id + "|" + row.li.getAttribute("value");
      var names = authorsByKey[key];
      if (names && names.length) extra = " " + names.join(" ");
      row.text = citationText(row.li) + extra.toLowerCase();
    });
  }

  function option(value, label) {
    var o = document.createElement("option");
    o.value = value;
    o.textContent = label;
    return o;
  }

  function control(labelText, id, el) {
    var wrap = document.createElement("div");
    wrap.className = "pub-control";
    var label = document.createElement("label");
    label.setAttribute("for", id);
    label.textContent = labelText;
    el.id = id;
    wrap.appendChild(label);
    wrap.appendChild(el);
    return wrap;
  }

  function buildToolbar() {
    var form = document.createElement("form");
    form.className = "pub-controls";
    form.setAttribute("role", "search");
    form.setAttribute("aria-label", "Search and filter publications");
    // Nothing to submit: filtering is live. Enter should not reload the page.
    form.addEventListener("submit", function (e) { e.preventDefault(); });

    qInput = document.createElement("input");
    qInput.type = "search";
    qInput.placeholder = "Title, author, journal…";
    qInput.autocomplete = "off";
    form.appendChild(control("Search", "pub-q", qInput));

    typeSel = document.createElement("select");
    typeSel.appendChild(option("", "All types"));
    document.querySelectorAll("main section").forEach(function (section) {
      if (!section.querySelector(".pub-list")) return;
      var h2 = section.querySelector("h2");
      if (h2) typeSel.appendChild(option(section.id, h2.textContent.trim()));
    });
    form.appendChild(control("Type", "pub-type", typeSel));

    yearSel = document.createElement("select");
    yearSel.appendChild(option("", "All years"));
    var years = [];
    rows.forEach(function (r) {
      if (r.year && years.indexOf(r.year) === -1) years.push(r.year);
    });
    years.sort(function (a, b) { return b.localeCompare(a); });
    years.forEach(function (y) { yearSel.appendChild(option(y, y)); });
    form.appendChild(control("Year", "pub-year", yearSel));

    var clear = document.createElement("button");
    clear.type = "button";
    clear.className = "pub-clear";
    clear.textContent = "Clear";
    clear.addEventListener("click", function () {
      qInput.value = "";
      typeSel.value = "";
      yearSel.value = "";
      apply();
      qInput.focus();
    });
    form.appendChild(clear);

    countEl = document.createElement("p");
    countEl.className = "pub-count";
    countEl.setAttribute("role", "status");
    countEl.setAttribute("aria-live", "polite");
    form.appendChild(countEl);

    qInput.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(apply, DEBOUNCE);
    });
    typeSel.addEventListener("change", apply);
    yearSel.addEventListener("change", apply);

    return form;
  }

  function apply() {
    var q = qInput.value.trim().toLowerCase();
    var tokens = q ? q.split(/\s+/) : [];
    var type = typeSel.value;
    var year = yearSel.value;

    rows.forEach(function (row) {
      var hit = true;
      if (type && row.section.id !== type) hit = false;
      if (hit && year && row.year !== year) hit = false;
      if (hit && tokens.length) {
        for (var i = 0; i < tokens.length; i++) {
          if (row.text.indexOf(tokens[i]) === -1) { hit = false; break; }
        }
      }
      setHidden(row.li, !hit);
    });

    // Roll the result up: a year list, its heading, and a whole category section
    // disappear once nothing inside them is visible on EITHER layer.
    var shown = 0;
    document.querySelectorAll("ol.pub-list, ul.pub-list").forEach(function (ol) {
      var any = false;
      ol.querySelectorAll("li").forEach(function (li) { if (isVisible(li)) any = true; });
      setHidden(ol, !any);
      var prev = ol.previousElementSibling;
      if (prev && prev.classList.contains("pub-year")) setHidden(prev, !any);
    });
    document.querySelectorAll("main section").forEach(function (section) {
      if (!section.querySelector(".pub-list")) return;
      var any = false;
      section.querySelectorAll(".pub-list li").forEach(function (li) {
        if (isVisible(li)) any = true;
      });
      setHidden(section, !any);
    });
    rows.forEach(function (row) { if (isVisible(row.li)) shown++; });

    // Report what is actually on screen, which is the product of BOTH layers, not
    // just of this toolbar's controls: arriving with ?topic=epi narrows the list
    // before the toolbar is touched, and saying "showing all 104" there would be
    // a plain lie.
    var narrowed = shown !== rows.length;

    // The category table of contents carries counts that no longer hold.
    setHidden(document.querySelector("nav.pub-toc"), narrowed);

    countEl.textContent = !narrowed
      ? "Showing all " + rows.length + " publications"
      : shown === 0
        ? "No publications match"
        : "Showing " + shown + " of " + rows.length + " publications";
    countEl.classList.toggle("is-empty", shown === 0);
  }

  /* pub-filter.js hides and restores rows asynchronously, after its own fetch
     resolves and again when its banner's "Show all" is pressed. Watching the
     `hidden` attribute keeps the count and the empty-section rollup honest
     without the two files having to know about each other. Only that attribute
     is observed, and this file only ever sets classes, so this cannot re-trigger
     itself. */
  function watchOtherLayer() {
    if (!window.MutationObserver) return;
    var main = document.querySelector("main");
    if (!main) return;
    var pending = null;
    new MutationObserver(function () {
      clearTimeout(pending);
      pending = setTimeout(apply, 0);
    }).observe(main, {
      subtree: true,
      attributes: true,
      attributeFilter: ["hidden"]
    });
  }

  function init() {
    rows = collect();
    if (!rows.length) return;

    toolbar = buildToolbar();
    var toc = document.querySelector("nav.pub-toc");
    var anchor = toc && toc.nextElementSibling ? toc.nextElementSibling : toc;
    if (anchor && anchor.parentNode) {
      anchor.parentNode.insertBefore(toolbar, anchor.nextSibling);
    } else {
      var main = document.querySelector("main .container");
      if (main) main.insertBefore(toolbar, main.firstChild);
    }

    indexRows({});
    apply();
    watchOtherLayer();

    // Enrich the index with full author lists once they arrive. pub-authors.js
    // needs the same file, and both scripts start together, so the promise is
    // shared on window rather than fetched twice (see pub-authors.js).
    window.paperAuthorsPromise = window.paperAuthorsPromise ||
      fetch(AUTHORS).then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      });

    window.paperAuthorsPromise
      .then(function (data) {
        indexRows((data && data.entries) || {});
        apply();
      })
      .catch(function (err) {
        // Non-fatal: search still works over the visible citation text.
        console.warn("Author index unavailable (" + AUTHORS + "):", err.message);
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
