/*
 * Turns each condensing ellipsis ("...") in a citation on publications.html into
 * a hoverable button that reveals the paper's full, ordered author list.
 *
 * paper-authors.json is the source of truth: keys are "<section-id>|<entry-number>"
 * and map onto the <section id> / <li value> in the page (same scheme as
 * abstracts.json). Only the citation's leading author text — the direct text-node
 * children of each <li>, before the title <a> — is scanned, so titles, journal
 * names, and the appended Abstract disclosure are never touched. A single popover
 * element is shared across all buttons; long lists scroll inside it.
 *
 * Progressive enhancement: if the fetch fails, JS is off, or the paper isn't in
 * OpenAlex (no entry), the ellipsis is left as plain text and the page still reads
 * exactly as before.
 */
(function () {
  "use strict";

  var SOURCE = "paper-authors.json";
  var ELLIPSIS = "...";

  var popover = null;
  var listEl = null;
  var activeBtn = null;
  var hideTimer = null;

  function ensurePopover() {
    if (popover) return popover;
    popover = document.createElement("div");
    popover.className = "author-popover";
    popover.id = "author-popover";
    popover.setAttribute("role", "tooltip");
    popover.hidden = true;

    var title = document.createElement("div");
    title.className = "author-popover-title";
    popover.appendChild(title);

    listEl = document.createElement("div");
    listEl.className = "author-popover-list";
    popover.appendChild(listEl);

    // Keep the popover open while the pointer is over it (so it can be scrolled).
    popover.addEventListener("mouseenter", function () { clearTimeout(hideTimer); });
    popover.addEventListener("mouseleave", scheduleHide);

    document.body.appendChild(popover);
    return popover;
  }

  // Render a full name in the citation style: given/middle names as initials, the
  // surname in full. "Velma K. Lopez" -> "V. K. Lopez", "K.T. Sato" -> "K. T. Sato",
  // "Ana Pastore y Piontti" -> "A. P. y Piontti" (lowercase particles kept verbatim).
  // Site owner, shown as "SV" in the citations — match that in the popover across the
  // OpenAlex name variants (Srini/Srinivasan Venkatramanan, and known typos).
  var OWNER = /^srini(?:vasan)? venkat(?:a?ramanan|)$/i;

  function abbreviate(name) {
    if (OWNER.test(name.trim())) return "SV";
    var tokens = name.trim().split(/\s+/);
    if (tokens.length < 2) return name;
    var surname = tokens[tokens.length - 1];
    var given = tokens.slice(0, -1).map(function (tok) {
      if (/^\p{Ll}[\p{Ll}.]*$/u.test(tok)) return tok; // particle: van, de, y, dos
      var chars = Array.from(tok);
      var initials = [];
      for (var i = 0; i < chars.length; i++) {
        if (/\p{L}/u.test(chars[i]) && (i === 0 || /[.\-\s]/.test(chars[i - 1]))) {
          initials.push(chars[i].toUpperCase() + ".");
        }
      }
      return initials.length ? initials.join(" ") : tok;
    });
    return given.join(" ") + " " + surname;
  }

  function fill(names) {
    ensurePopover();
    popover.querySelector(".author-popover-title").textContent =
      "All " + names.length + " authors";
    listEl.textContent = names.map(abbreviate).join(", ");
    listEl.scrollTop = 0;
  }

  function position(btn) {
    var r = btn.getBoundingClientRect();
    var pw = popover.offsetWidth;
    var ph = popover.offsetHeight;
    var vw = document.documentElement.clientWidth;
    var margin = 8;

    var left = r.left;
    if (left + pw > vw - margin) left = vw - pw - margin;
    if (left < margin) left = margin;

    var top = r.bottom + 6;
    var spaceBelow = window.innerHeight - r.bottom;
    if (spaceBelow < ph + 12 && r.top > ph + 12) top = r.top - ph - 6;

    popover.style.left = (left + window.scrollX) + "px";
    popover.style.top = (top + window.scrollY) + "px";
  }

  function show(btn) {
    clearTimeout(hideTimer);
    if (activeBtn && activeBtn !== btn) activeBtn.setAttribute("aria-expanded", "false");
    activeBtn = btn;
    ensurePopover();
    fill(btn._authors);
    popover.hidden = false;
    position(btn);
    btn.setAttribute("aria-expanded", "true");
  }

  function hide() {
    if (popover) popover.hidden = true;
    if (activeBtn) {
      activeBtn.setAttribute("aria-expanded", "false");
      activeBtn = null;
    }
  }

  function scheduleHide() {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hide, 160);
  }

  function makeButton(names) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "author-ellipsis";
    btn.textContent = ELLIPSIS;
    btn.setAttribute("aria-haspopup", "true");
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-controls", "author-popover");
    btn.setAttribute("aria-label", "Show all " + names.length + " authors");
    btn.title = "Show all " + names.length + " authors";
    btn._authors = names;

    btn.addEventListener("mouseenter", function () { show(btn); });
    btn.addEventListener("mouseleave", scheduleHide);
    btn.addEventListener("focus", function () { show(btn); });
    btn.addEventListener("blur", scheduleHide);
    btn.addEventListener("click", function () {
      if (activeBtn === btn && popover && !popover.hidden) hide();
      else show(btn);
    });
    return btn;
  }

  // Replace every "..." inside a single text node with an author-list button.
  function enhanceTextNode(node, names) {
    var text = node.nodeValue;
    if (text.indexOf(ELLIPSIS) === -1) return;

    var frag = document.createDocumentFragment();
    var i = 0;
    var idx;
    while ((idx = text.indexOf(ELLIPSIS, i)) !== -1) {
      if (idx > i) frag.appendChild(document.createTextNode(text.slice(i, idx)));
      frag.appendChild(makeButton(names));
      i = idx + ELLIPSIS.length;
    }
    if (i < text.length) frag.appendChild(document.createTextNode(text.slice(i)));

    node.parentNode.replaceChild(frag, node);
  }

  function enhance(entries) {
    Object.keys(entries).forEach(function (key) {
      var names = entries[key];
      if (!names || !names.length) return;

      var parts = key.split("|");
      var section = document.getElementById(parts[0]);
      if (!section) return;

      var li = section.querySelector('li[value="' + parts[1] + '"]');
      if (!li) return;

      // Only the citation's leading author text — direct text-node children of the
      // <li>. Snapshot first, since enhanceTextNode mutates the child list.
      var textNodes = [];
      for (var n = li.firstChild; n; n = n.nextSibling) {
        if (n.nodeType === 3 && n.nodeValue.indexOf(ELLIPSIS) !== -1) textNodes.push(n);
      }
      textNodes.forEach(function (node) { enhanceTextNode(node, names); });
    });
  }

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && popover && !popover.hidden) {
      var toFocus = activeBtn;
      hide();
      if (toFocus) toFocus.focus();
    }
  });

  window.addEventListener("scroll", function () {
    if (activeBtn && popover && !popover.hidden) position(activeBtn);
  }, true);
  window.addEventListener("resize", function () {
    if (activeBtn && popover && !popover.hidden) position(activeBtn);
  });

  fetch(SOURCE)
    .then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function (data) {
      enhance((data && data.entries) || {});
    })
    .catch(function (err) {
      // Non-fatal: the ellipses simply stay as plain text.
      console.warn("Full author lists unavailable (" + SOURCE + "):", err.message);
    });
})();
