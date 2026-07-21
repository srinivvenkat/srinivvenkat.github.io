/*
 * Filters the publication list down to a subset arriving from a home-page
 * visualization, via one of two URL params:
 *   ?term=genomic-surveillance  — from the word cloud (wordcloud-data.json maps
 *       every cloud term to the publication keys whose abstract contains it).
 *   ?author=madhav-marathe      — from the collaboration network
 *       (coauthors-data.json maps every co-author node to the keys of the papers
 *       co-authored with the site owner).
 * Both data files key papers as "<section-id>|<number>" — the same keys
 * abstracts.js uses — so we locate the exact <li> entries without re-analyzing
 * anything here.
 *
 * When a param is present, non-matching papers are hidden, along with any year
 * heading, section, or the category table-of-contents that ends up empty. Papers
 * keep their original catalog numbers and stay grouped by year/section. A
 * dismissible banner offers "Show all", which restores the full list exactly.
 * Abstract toggles (from abstracts.js) are left collapsed and still expandable.
 *
 * This file is intentionally separate from abstracts.js: that script keeps its
 * single responsibility (rendering abstract toggles) and this one has no
 * dependency on its internals. When there is no recognized param it does nothing.
 *
 * Progressive enhancement: if the fetch fails or JS is off, the publication list
 * renders normally, just unfiltered.
 */
(function () {
  "use strict";

  var SOURCE = "wordcloud-data.json";
  var AUTHOR_SOURCE = "coauthors-data.json";

  function getParam(name) {
    var m = new RegExp("[?&]" + name + "=([^&]*)").exec(window.location.search);
    return m ? decodeURIComponent(m[1].replace(/\+/g, " ")) : null;
  }

  function slugify(term) {
    return term.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  }

  function prefersReducedMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function clearParam() {
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, "", window.location.pathname);
    }
  }

  function findEntries(keys) {
    var lis = [];
    keys.forEach(function (key) {
      var parts = key.split("|");
      var section = document.getElementById(parts[0]);
      if (!section) return;
      var li = section.querySelector('li[value="' + parts[1] + '"]');
      if (li) lis.push(li);
    });
    return lis;
  }

  // mode "term": "…publications mentioning “label”"; the label is the cloud term.
  // mode "author": "…publications co-authored with label"; the label is a name.
  function buildBanner(label, count, onClear, mode) {
    var banner = document.createElement("div");
    banner.className = "pub-banner";
    banner.setAttribute("role", "status");

    var connector = mode === "author"
      ? (count === 1 ? " publication co-authored with " : " publications co-authored with ")
      : (count === 1 ? " publication mentioning " : " publications mentioning ");

    var msg = document.createElement("span");
    msg.appendChild(document.createTextNode("Showing "));
    var strong = document.createElement("strong");
    strong.textContent = String(count);
    msg.appendChild(strong);
    msg.appendChild(document.createTextNode(connector));
    var termEl = document.createElement("span");
    termEl.className = "pub-banner-term";
    termEl.textContent = mode === "author" ? label : "“" + label + "”";
    msg.appendChild(termEl);
    banner.appendChild(msg);

    var close = document.createElement("button");
    close.type = "button";
    close.className = "pub-banner-close";
    close.textContent = "Show all ×";
    close.addEventListener("click", onClear);
    banner.appendChild(close);

    return banner;
  }

  function apply(label, keys, mode) {
    var lis = findEntries(keys);
    if (!lis.length) {
      // Nothing found among entries (e.g. a stale/bogus slug): clean up quietly.
      clearParam();
      return;
    }

    var matched = new Set(lis);
    var hidden = []; // every element we hide, so restore is exact

    function hide(el) {
      if (el && !el.hidden) { el.hidden = true; hidden.push(el); }
    }

    // 1. Hide every publication that isn't a match.
    var allLis = document.querySelectorAll(".pub-list li");
    allLis.forEach(function (li) { if (!matched.has(li)) hide(li); });

    // 2. Hide each year list left with no visible papers, plus its year heading
    //    (the immediately preceding <h3 class="pub-year">).
    document.querySelectorAll("ol.pub-list").forEach(function (ol) {
      var hasVisible = false;
      ol.querySelectorAll("li").forEach(function (li) { if (!li.hidden) hasVisible = true; });
      if (!hasVisible) {
        hide(ol);
        var prev = ol.previousElementSibling;
        if (prev && prev.classList.contains("pub-year")) hide(prev);
      }
    });

    // 3. Hide each category section left with no visible papers (its <h2> too).
    document.querySelectorAll("main section").forEach(function (section) {
      if (!section.querySelector(".pub-list")) return; // not a publication section
      var hasVisible = false;
      section.querySelectorAll(".pub-list li").forEach(function (li) { if (!li.hidden) hasVisible = true; });
      if (!hasVisible) hide(section);
    });

    // 4. Hide the category table-of-contents (its counts no longer match).
    hide(document.querySelector("nav.pub-toc"));

    // 5. Banner with a restore action.
    var main = document.querySelector("main .container") || document.querySelector("main");
    var banner;
    function onClear() {
      hidden.forEach(function (el) { el.hidden = false; });
      hidden = [];
      if (banner && banner.parentNode) banner.parentNode.removeChild(banner);
      clearParam();
    }
    banner = buildBanner(label, lis.length, onClear, mode);
    if (main) main.insertBefore(banner, main.firstChild);

    // Bring the filtered list into view (the banner sits just above it).
    (banner || lis[0]).scrollIntoView({
      behavior: prefersReducedMotion() ? "auto" : "smooth",
      block: "start"
    });
  }

  function fetchJson(url) {
    return fetch(url).then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    });
  }

  // ?term= comes from the word cloud (wordcloud-data.json); ?author= comes from
  // the home-page collaboration network (coauthors-data.json). Each maps to a set
  // of publication keys we filter the list down to.
  function filterByTerm(slug) {
    fetchJson(SOURCE)
      .then(function (data) {
        var terms = (data && data.terms) || [];
        var match = null;
        for (var i = 0; i < terms.length; i++) {
          if (slugify(terms[i].term) === slug) { match = terms[i]; break; }
        }
        if (!match) { clearParam(); return; }
        apply(match.term, match.keys || [], "term");
      })
      .catch(function (err) {
        console.warn("Publication filter unavailable (" + SOURCE + "):", err.message);
      });
  }

  function filterByAuthor(slug) {
    fetchJson(AUTHOR_SOURCE)
      .then(function (data) {
        var authors = (data && data.nodes) || [];
        var match = null;
        for (var i = 0; i < authors.length; i++) {
          if (authors[i].id === slug) { match = authors[i]; break; }
        }
        if (!match) { clearParam(); return; }
        apply(match.name, match.keys || [], "author");
      })
      .catch(function (err) {
        console.warn("Publication filter unavailable (" + AUTHOR_SOURCE + "):", err.message);
      });
  }

  function init() {
    var term = getParam("term");
    if (term) { filterByTerm(slugify(term)); return; }
    var author = getParam("author");
    if (author) { filterByAuthor(slugify(author)); return; }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
