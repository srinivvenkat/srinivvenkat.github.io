/*
 * Renders the "Research Themes" word cloud on the home page.
 *
 * Data comes from wordcloud-data.json, precomputed by tools/build_wordcloud.py
 * (TF-IDF-style weights, theme, and the publication keys each term appears in).
 * This script does no text analysis — it only lays out what the precompute
 * produced, using each term's combined all-time weight.
 *
 * Progressive enhancement: if the fetch fails, JS is off, or the page is opened
 * over file:// (where fetch is blocked), the section keeps its heading and intro
 * and simply shows no cloud. The legend starts hidden in the markup and is
 * revealed only after a successful render.
 *
 * Design choices worth knowing:
 *  - SVG (not canvas) so every word is a real <a>, focusable and clickable.
 *  - Words are packed once via an Archimedean spiral, biggest first, so the
 *    layout is stable and never overlaps.
 */
(function () {
  "use strict";

  var SOURCE = "wordcloud-data.json";
  var SVGNS = "http://www.w3.org/2000/svg";

  // Font-size mapping. Weights are normalized to [0,1] across the displayed
  // terms, then curved. Because selection is now balanced per theme, prominence
  // no longer needs a dramatic size range — a compact range keeps every keyword
  // legible while still giving each theme's flagship some emphasis.
  var FONT_MIN = 20;
  var FONT_MAX_DESKTOP = 50;
  var FONT_MAX_MOBILE = 36;
  var SIZE_EXP = 0.85; // <1 lifts the middle so mid-weight words stay readable
  var MOBILE_BP = 640;

  var PAD = 3; // px padding around each word's box when packing

  function isMobile() {
    return window.matchMedia("(max-width: " + MOBILE_BP + "px)").matches;
  }

  function fontMax() {
    return isMobile() ? FONT_MAX_MOBILE : FONT_MAX_DESKTOP;
  }

  // norm is a 0..1 rank of this term's weight within the displayed set.
  function sizeFor(norm, max) {
    return FONT_MIN + (max - FONT_MIN) * Math.pow(Math.max(0, norm), SIZE_EXP);
  }

  function rectsOverlap(a, b) {
    return !(a.x + a.w < b.x || b.x + b.w < a.x || a.y + a.h < b.y || b.y + b.h < a.y);
  }

  // Horizontal stretch: the container is much wider than tall, so bias the
  // spiral into a landscape ellipse (x expands faster than y). This fills the
  // available width instead of packing into a narrow central column. Set per
  // render (see build) — gentler on narrow phone screens.
  var ASPECT = 2.1;

  // Archimedean-spiral placement: try the centre first, then walk outward until
  // the candidate box clears everything already placed.
  function placeWord(box, placed, cx, cy) {
    var step = 0.35;
    var a = 4; // spiral tightness (px per radian)
    for (var theta = 0; theta < 60 * Math.PI; theta += step) {
      var r = a * theta;
      var x = cx + ASPECT * r * Math.cos(theta) - box.w / 2;
      var y = cy + r * Math.sin(theta) - box.h / 2;
      var cand = { x: x, y: y, w: box.w, h: box.h };
      var hit = false;
      for (var i = 0; i < placed.length; i++) {
        if (rectsOverlap(cand, placed[i])) { hit = true; break; }
      }
      if (!hit) return cand;
      // Loosen the step slightly as we go so large clouds stay fast.
      if (theta > 12 * Math.PI) step = 0.5;
    }
    return null;
  }

  function slugify(term) {
    return term.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  }

  function build(data, svg) {
    var terms = data.terms || [];
    if (isMobile()) {
      terms = terms.filter(function (t) { return t.mobile; });
    }
    if (!terms.length) return null;

    var max = fontMax();
    var themes = data.themes || {};
    // Wide ellipse on desktop to fill the column; near-round on phones so the
    // cloud doesn't flatten into an unreadable strip.
    ASPECT = isMobile() ? 1.35 : 2.1;

    // Normalize weights across the displayed terms so the full font-size range
    // is used regardless of the raw weight distribution.
    var wMin = Infinity, wMax = -Infinity;
    terms.forEach(function (t) {
      if (t.weight < wMin) wMin = t.weight;
      if (t.weight > wMax) wMax = t.weight;
    });
    var span = wMax - wMin;
    function norm(w) { return span > 0 ? (w - wMin) / span : 1; }

    // Biggest first, placed from the centre out.
    terms = terms.slice().sort(function (a, b) { return b.weight - a.weight; });

    var placed = [];
    var nodes = [];
    var cx = 0, cy = 0;

    // A hidden measuring text node reused for every getBBox() call.
    var meas = document.createElementNS(SVGNS, "text");
    meas.setAttribute("x", "-9999");
    meas.setAttribute("y", "-9999");
    meas.style.fontFamily = "Georgia, 'Times New Roman', serif";
    meas.style.fontWeight = "bold";
    svg.appendChild(meas);

    terms.forEach(function (t) {
      var size = sizeFor(norm(t.weight), max);

      meas.style.fontSize = size + "px";
      meas.textContent = t.term;
      var bb = meas.getBBox();
      var box = { w: bb.width + PAD * 2, h: bb.height + PAD * 2 };

      var pos = placeWord(box, placed, cx, cy);
      if (!pos) return; // give up on this word rather than overlap
      placed.push(pos);

      nodes.push({
        term: t,
        // Baseline y: box top + padding + ascent-ish. getBBox height includes
        // descenders; placing the baseline near the box bottom looks right.
        x: pos.x + PAD,
        baseline: pos.y + box.h - PAD - bb.height * 0.18,
        size: size
      });
    });

    svg.removeChild(meas);

    if (!nodes.length) return null;

    // Compute the content bounds for the viewBox.
    var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    placed.forEach(function (p) {
      minX = Math.min(minX, p.x); minY = Math.min(minY, p.y);
      maxX = Math.max(maxX, p.x + p.w); maxY = Math.max(maxY, p.y + p.h);
    });
    var m = 8;
    svg.setAttribute("viewBox",
      (minX - m) + " " + (minY - m) + " " + (maxX - minX + 2 * m) + " " + (maxY - minY + 2 * m));

    var wordEls = [];
    nodes.forEach(function (n) {
      var t = n.term;
      var themeLabel = (themes[t.theme] && themes[t.theme].label) || "general";
      var count = (t.keys || []).length;

      var a = document.createElementNS(SVGNS, "a");
      a.setAttribute("href", "publications.html?term=" + encodeURIComponent(slugify(t.term)));
      a.setAttribute("class", "wc-word");
      a.setAttribute("data-theme", t.theme);
      a.setAttribute("role", "link");
      a.setAttribute("aria-label",
        t.term + " — " + themeLabel + ", appears in " + count +
        (count === 1 ? " publication" : " publications"));

      var text = document.createElementNS(SVGNS, "text");
      text.setAttribute("x", n.x);
      text.setAttribute("y", n.baseline);
      text.setAttribute("font-size", n.size);
      text.textContent = t.term;
      // Set the theme color inline from the data so word colors never depend on
      // the external stylesheet loading (or a stale cached copy of it).
      var themeColor = themes[t.theme] && themes[t.theme].color;
      if (themeColor) text.style.fill = themeColor;

      a.appendChild(text);
      svg.appendChild(a);
      wordEls.push({ el: text, wrap: a, term: t });
    });

    return { wordEls: wordEls };
  }

  function fillLegend(legend, data) {
    if (!legend) return;
    var order = data.themeOrder || Object.keys(data.themes || {});
    order.forEach(function (id) {
      var th = data.themes[id];
      if (!th) return;
      var li = document.createElement("li");
      var sw = document.createElement("span");
      sw.className = "wc-swatch";
      sw.style.background = th.color;
      li.appendChild(sw);
      li.appendChild(document.createTextNode(th.label));
      legend.appendChild(li);
    });
  }

  function init() {
    var root = document.getElementById("wordcloud");
    if (!root) return;
    var svg = root.querySelector("svg.wc");
    if (!svg) return;

    fetch(SOURCE)
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        var built = build(data, svg);
        if (!built) return;

        var cloud = root.querySelector(".wc-cloud");
        // Hover dims siblings (toggled via a class on the container).
        if (cloud) {
          built.wordEls.forEach(function (w) {
            w.wrap.addEventListener("mouseenter", function () { cloud.classList.add("is-hovering"); });
            w.wrap.addEventListener("mouseleave", function () { cloud.classList.remove("is-hovering"); });
            w.wrap.addEventListener("focus", function () { cloud.classList.add("is-hovering"); });
            w.wrap.addEventListener("blur", function () { cloud.classList.remove("is-hovering"); });
          });
        }

        fillLegend(root.querySelector(".wc-legend"), data);
        var legend = root.querySelector(".wc-legend");
        if (legend) legend.hidden = false;
      })
      .catch(function (err) {
        console.warn("Word cloud unavailable (" + SOURCE + "):", err.message);
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
