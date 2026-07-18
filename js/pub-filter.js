/*
 * Highlights publications that match a term arriving from the home-page word
 * cloud, e.g. publications.html?term=genomic-surveillance.
 *
 * The word cloud links to this page with a ?term= slug. wordcloud-data.json maps
 * every cloud term to the publication keys ("<section-id>|<number>") whose
 * abstract contains it — the same keys abstracts.js uses — so we can highlight
 * the exact <li> entries without re-tokenizing anything here.
 *
 * This file is intentionally separate from abstracts.js: that script keeps its
 * single responsibility (rendering abstract toggles) and this one has no
 * dependency on its internals. When there is no ?term= param it does nothing.
 *
 * Progressive enhancement: if the fetch fails or JS is off, the publication list
 * renders normally, just without highlighting.
 */
(function () {
  "use strict";

  var SOURCE = "wordcloud-data.json";

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

  function buildBanner(term, count, onClear) {
    var banner = document.createElement("div");
    banner.className = "pub-banner";
    banner.setAttribute("role", "status");

    var msg = document.createElement("span");
    msg.appendChild(document.createTextNode("Showing "));
    var strong = document.createElement("strong");
    strong.textContent = String(count);
    msg.appendChild(strong);
    msg.appendChild(document.createTextNode(
      (count === 1 ? " publication mentioning " : " publications mentioning ")));
    var termEl = document.createElement("span");
    termEl.className = "pub-banner-term";
    termEl.textContent = "“" + term + "”";
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

  function apply(term, keys) {
    var lis = findEntries(keys);
    if (!lis.length) {
      // Term not found among entries (e.g. a stale/bogus slug): clean up quietly.
      clearParam();
      return;
    }

    lis.forEach(function (li) { li.classList.add("pub-match"); });

    var main = document.querySelector("main .container") || document.querySelector("main");
    var banner;
    function onClear() {
      lis.forEach(function (li) { li.classList.remove("pub-match"); });
      if (banner && banner.parentNode) banner.parentNode.removeChild(banner);
      clearParam();
    }
    banner = buildBanner(term, lis.length, onClear);
    if (main) main.insertBefore(banner, main.firstChild);

    // Scroll the first match into view.
    lis[0].scrollIntoView({
      behavior: prefersReducedMotion() ? "auto" : "smooth",
      block: "center"
    });

    // abstracts.js injects <details class="abs"> on its own async fetch, so the
    // toggles may not exist yet. Poll briefly to auto-open matches, then stop.
    var tries = 0;
    var poll = setInterval(function () {
      tries++;
      var opened = 0;
      lis.forEach(function (li) {
        var abs = li.querySelector(".abs");
        if (abs && !abs.hasAttribute("open")) { abs.setAttribute("open", ""); opened++; }
      });
      if (opened > 0 || tries >= 6) clearInterval(poll);
    }, 250);
  }

  function init() {
    var raw = getParam("term");
    if (!raw) return;
    var slug = slugify(raw);

    fetch(SOURCE)
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        var terms = (data && data.terms) || [];
        var match = null;
        for (var i = 0; i < terms.length; i++) {
          if (slugify(terms[i].term) === slug) { match = terms[i]; break; }
        }
        if (!match) { clearParam(); return; }
        apply(match.term, match.keys || []);
      })
      .catch(function (err) {
        console.warn("Publication filter unavailable (" + SOURCE + "):", err.message);
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
