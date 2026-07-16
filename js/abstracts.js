/*
 * Renders the "Abstract" toggles on publications.html.
 *
 * abstracts.json is the single source of truth: every entry whose "abstract"
 * field is non-null gets a toggle; entries without one are left alone. Keys are
 * "<section-id>|<entry-number>" and map onto the <section id> / <li value> in
 * the page, so editing an abstract there needs no change here or in the HTML.
 *
 * Progressive enhancement: if the fetch fails, or JS is off, or the page is
 * opened over file:// (where fetch is blocked by CORS), the page still renders
 * fully — it just shows no abstract toggles.
 */
(function () {
  "use strict";

  var SOURCE = "abstracts.json";

  function markdownBoldInto(el, text) {
    // Only **bold** is supported; text is inserted as text nodes, never HTML.
    var re = /\*\*(.+?)\*\*/g;
    var last = 0;
    var m;
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) {
        el.appendChild(document.createTextNode(text.slice(last, m.index)));
      }
      var strong = document.createElement("strong");
      strong.textContent = m[1];
      el.appendChild(strong);
      last = re.lastIndex;
    }
    if (last < text.length) {
      el.appendChild(document.createTextNode(text.slice(last)));
    }
  }

  function buildToggle(abstract) {
    var details = document.createElement("details");
    details.className = "abs";

    var summary = document.createElement("summary");
    summary.textContent = "Abstract";
    details.appendChild(summary);

    var body = document.createElement("div");
    body.className = "abs-body";
    abstract.split("\n\n").forEach(function (para) {
      var trimmed = para.trim();
      if (!trimmed) return;
      var p = document.createElement("p");
      markdownBoldInto(p, trimmed);
      body.appendChild(p);
    });
    details.appendChild(body);

    return details;
  }

  function render(entries) {
    Object.keys(entries).forEach(function (key) {
      var entry = entries[key];
      if (!entry || !entry.abstract) return;

      var parts = key.split("|");
      var section = document.getElementById(parts[0]);
      if (!section) return;

      var li = section.querySelector('li[value="' + parts[1] + '"]');
      if (!li || li.querySelector(".abs")) return;

      li.appendChild(buildToggle(entry.abstract));
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
      // Non-fatal: the publication list itself is already complete without this.
      console.warn("Abstracts unavailable (" + SOURCE + "):", err.message);
    });
})();
