/*
 * Renders the "BibTeX" toggles on publications.html, each with a copy button.
 *
 * bibtex.json is the source of truth, built by tools/build_bibtex.py from the DOI
 * or arXiv id in each citation's link. Keys are "<section-id>|<entry-number>",
 * the same scheme abstracts.js and pub-authors.js use, so a record attaches to
 * its <li> without re-parsing the page. Entries with no resolvable identifier
 * (a few older technical reports linked to a Scholar search) simply have no
 * record and get no button.
 *
 * The records are baked at build time rather than fetched live because doi.org
 * sends no CORS headers: a page script cannot read that response at all.
 *
 * Placement: the BibTeX disclosure always sits after the Abstract one. Both are
 * appended by independent fetches that can finish in either order, so each script
 * looks for the other's element and inserts relative to it (see abstracts.js).
 *
 * Progressive enhancement: if the fetch fails, JS is off, or the page is opened
 * over file://, the citation list renders exactly as before, just without
 * toggles.
 */
(function () {
  "use strict";

  var SOURCE = "bibtex.json";

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    // Fallback for non-secure contexts, where navigator.clipboard is undefined.
    return new Promise(function (resolve, reject) {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.top = "-1000px";
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      document.body.removeChild(ta);
      ok ? resolve() : reject(new Error("copy blocked"));
    });
  }

  function buildToggle(record) {
    var details = document.createElement("details");
    details.className = "bib";

    var summary = document.createElement("summary");
    summary.textContent = "BibTeX";
    details.appendChild(summary);

    var body = document.createElement("div");
    body.className = "bib-body";

    var pre = document.createElement("pre");
    pre.className = "bib-pre";
    pre.textContent = record; // text node only, never parsed as HTML
    body.appendChild(pre);

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "bib-copy";
    btn.textContent = "Copy";
    // The live region is the button itself: its label changes to "Copied".
    btn.addEventListener("click", function () {
      copyText(record).then(function () {
        btn.textContent = "Copied";
        btn.classList.add("is-copied");
      }).catch(function () {
        btn.textContent = "Press ⌘C";
      });
      setTimeout(function () {
        btn.textContent = "Copy";
        btn.classList.remove("is-copied");
      }, 1600);
    });
    body.appendChild(btn);

    details.appendChild(body);
    return details;
  }

  function render(entries) {
    Object.keys(entries).forEach(function (key) {
      var record = entries[key];
      if (!record) return;

      var parts = key.split("|");
      var section = document.getElementById(parts[0]);
      if (!section) return;

      var li = section.querySelector('li[value="' + parts[1] + '"]');
      if (!li || li.querySelector(".bib")) return;

      li.appendChild(buildToggle(record));
    });
  }

  fetch(SOURCE)
    .then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function (data) {
      render((data && data.entries) || {});
    })
    .catch(function (err) {
      // Non-fatal: the citation list is already complete without this.
      console.warn("BibTeX records unavailable (" + SOURCE + "):", err.message);
    });
})();
