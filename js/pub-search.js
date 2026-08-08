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
 * WHAT IS INDEXED
 * Three sources per row, all reduced to one lowercase string:
 *   - the citation text in the markup, with the Abstract and BibTeX disclosures
 *     stripped out (they are appended asynchronously by other scripts, and the
 *     abstract is indexed from JSON instead — see below);
 *   - the full author list from paper-authors.json, because long lists are
 *     condensed to "..." in the markup and without it searching for a middle
 *     author of a 30-author paper would silently fail;
 *   - the abstract from abstracts.json, which is the same file abstracts.js
 *     renders the toggles from, reached through the window.abstractsPromise it
 *     shares so the ~200 KB is fetched once.
 * Reading abstracts from the JSON rather than from the rendered .abs elements is
 * what makes this safe: the index is built from the parsed data in one pass, so
 * it never depends on how far abstracts.js has got through the DOM.
 *
 * Abstract text is kept in a SEPARATE field from the citation text, not
 * concatenated onto it, so apply() can tell a citation hit from an abstract-only
 * hit. That distinction is the difference between a useful result and an
 * apparently random one: a row matching only on abstract text shows a citation
 * with the query nowhere in it, so those rows get flagged (is-abs-match) and the
 * count says how many there are.
 *
 * Both enrichments land asynchronously and simply rebuild the index and re-run
 * apply() when they do. A search typed in the first moments therefore matches on
 * citation text alone and widens once the JSON arrives; the live count keeps up,
 * and nothing already shown disappears.
 *
 * Progressive enhancement: if any fetch fails or JS is off, the full list renders
 * normally, just without the toolbar.
 */
(function () {
  "use strict";

  var AUTHORS = "paper-authors.json";
  var ABSTRACTS = "abstracts.json";
  var HIDDEN = "is-filtered-out";
  var ABS_MATCH = "is-abs-match";
  var DEBOUNCE = 120;

  // The early years are sparse, so 2014 and earlier collapse into one range
  // option in the year select rather than a run of single-paper years.
  var YEAR_RANGE_MAX = 2014;
  var YEAR_RANGE_VALUE = "-2014"; // the select value for that combined option

  var rows = [];      // { li, ol, heading, section, year, key, text, abstract }
  var toolbar = null;
  var qInput = null, typeSel = null, yearSel = null, countEl = null;
  var timer = null;

  // Keyed "<section-id>|<entry-number>", matching both JSON files. Filled in by
  // their fetches; empty until then, which just means a narrower index.
  var authorsByKey = {};
  var abstractsByKey = {};

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
          out.push({
            li: li,
            ol: ol,
            heading: heading,
            section: section,
            year: year,
            key: section.id + "|" + li.getAttribute("value"),
            text: "",
            abstract: ""
          });
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

  // Rebuilt from scratch each time a source arrives, rather than appended to, so
  // a late fetch can never double-index a row it already contributed to.
  function indexRows() {
    rows.forEach(function (row) {
      var names = authorsByKey[row.key];
      var extra = names && names.length ? " " + names.join(" ") : "";
      row.text = citationText(row.li) + extra.toLowerCase();

      var entry = abstractsByKey[row.key];
      var abstract = entry && entry.abstract ? entry.abstract : "";
      // ** marks structured-abstract labels in the JSON; drop it so a search for
      // "methods" matches "**Methods**" the way the reader sees it.
      row.abstract = abstract.replace(/\*\*/g, "").replace(/\s+/g, " ").toLowerCase();
    });
  }

  /* Flags a row whose only match is inside its abstract, so the reader is not
     left staring at a citation that has nothing to do with what they typed. The
     class styles the existing Abstract pill; the title says why in words, for
     anyone who would not read a colour. The summary belongs to abstracts.js and
     may not be there — an entry can have no abstract at all, and in the ordering
     where this script creates the shared promise, abstracts.js has not rendered
     yet on the first pass. The class is set on the <li> either way, so the
     styling lands whenever the pill appears; only the tooltip waits for the next
     apply(). */
  function markAbstractMatch(row, on) {
    row.li.classList.toggle(ABS_MATCH, on);
    var summary = row.li.querySelector(".abs > summary");
    if (!summary) return;
    if (on) summary.title = "Your search matched this abstract";
    else summary.removeAttribute("title");
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
    qInput.placeholder = "Title, author, journal, abstract…";
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
    var early = years.filter(function (y) { return Number(y) <= YEAR_RANGE_MAX; });
    years.forEach(function (y) {
      if (Number(y) <= YEAR_RANGE_MAX) return;
      yearSel.appendChild(option(y, y));
    });
    if (early.length) {
      var lo = early[early.length - 1]; // oldest year present, e.g. "2010"
      yearSel.appendChild(option(YEAR_RANGE_VALUE, lo + "–" + String(YEAR_RANGE_MAX).slice(-2)));
    }
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
      var absOnly = false;
      if (type && row.section.id !== type) hit = false;
      if (hit && year) {
        if (year === YEAR_RANGE_VALUE) {
          if (Number(row.year) > YEAR_RANGE_MAX) hit = false;
        } else if (row.year !== year) {
          hit = false;
        }
      }
      if (hit && tokens.length) {
        // Every token must appear somewhere, in the citation or in the abstract,
        // but a row is only "abstract-only" when at least one token is missing
        // from the citation — that is the row whose match is invisible on screen.
        var inCitation = true;
        for (var i = 0; i < tokens.length; i++) {
          var onCitation = row.text.indexOf(tokens[i]) !== -1;
          if (!onCitation) {
            inCitation = false;
            if (row.abstract.indexOf(tokens[i]) === -1) { hit = false; break; }
          }
        }
        absOnly = hit && !inCitation;
      }
      row.absOnly = absOnly;
      setHidden(row.li, !hit);
      markAbstractMatch(row, absOnly);
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
    // Counted here, not where the flag is set, so a row hidden by the other
    // layer is left out of both totals.
    var absOnly = 0;
    rows.forEach(function (row) {
      if (!isVisible(row.li)) return;
      shown++;
      if (row.absOnly) absOnly++;
    });

    // Report what is actually on screen, which is the product of BOTH layers, not
    // just of this toolbar's controls: arriving with ?topic=epi narrows the list
    // before the toolbar is touched, and saying "showing all 104" there would be
    // a plain lie.
    var narrowed = shown !== rows.length;

    // The category table of contents carries counts that no longer hold.
    setHidden(document.querySelector("nav.pub-toc"), narrowed);

    var text = !narrowed
      ? "Showing all " + rows.length + " publications"
      : shown === 0
        ? "No publications match"
        : "Showing " + shown + " of " + rows.length + " publications";

    // Explains the rows whose citation looks unrelated to the query.
    if (absOnly) {
      text += absOnly === 1
        ? " · 1 matched in its abstract only"
        : " · " + absOnly + " matched in their abstracts only";
    }

    countEl.textContent = text;
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

    indexRows();
    apply();
    watchOtherLayer();

    // Both enrichments come from files another script on this page already
    // fetches, so each promise is shared on window rather than fetched twice
    // (see pub-authors.js and abstracts.js). Whichever script runs first creates
    // it. They resolve independently and each rebuilds the whole index, so
    // arriving in either order gives the same result.
    window.paperAuthorsPromise = window.paperAuthorsPromise ||
      fetch(AUTHORS).then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      });

    window.paperAuthorsPromise
      .then(function (data) {
        authorsByKey = (data && data.entries) || {};
        indexRows();
        apply();
      })
      .catch(function (err) {
        // Non-fatal: search still works over the visible citation text.
        console.warn("Author index unavailable (" + AUTHORS + "):", err.message);
      });

    window.abstractsPromise = window.abstractsPromise ||
      fetch(ABSTRACTS).then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      });

    window.abstractsPromise
      .then(function (data) {
        abstractsByKey = (data && data.entries) || {};
        indexRows();
        apply();
      })
      .catch(function (err) {
        // Non-fatal: the abstracts simply stay out of the index, and the page
        // shows no toggles either, so there is nothing to explain to the reader.
        console.warn("Abstract index unavailable (" + ABSTRACTS + "):", err.message);
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
