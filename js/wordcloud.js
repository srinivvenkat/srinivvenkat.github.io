/*
 * Renders the interactive "Research Themes" word cloud on the home page.
 *
 * Data comes from wordcloud-data.json, precomputed by tools/build_wordcloud.py
 * (TF-IDF-style weights, per-era weights, theme, and the publication keys each
 * term appears in). This script does no text analysis — it only lays out and
 * animates what the precompute produced.
 *
 * Progressive enhancement: if the fetch fails, JS is off, or the page is opened
 * over file:// (where fetch is blocked), the section keeps its heading and intro
 * and simply shows no cloud. The controls/legend start hidden in the markup and
 * are revealed only after a successful render.
 *
 * Design choices worth knowing:
 *  - SVG (not canvas) so every word is a real <a>, focusable and clickable, and
 *    the click-through works even if this interaction layer errors after render.
 *  - The spiral layout runs ONCE, from all-time weights, and each word is packed
 *    at its worst-case size across all eras — so the time-lapse only rescales and
 *    fades words in place and can never cause overlap or reflow.
 */
(function () {
  "use strict";

  var SOURCE = "wordcloud-data.json";
  var SVGNS = "http://www.w3.org/2000/svg";

  // Font-size mapping. Area ~ weight, so radius (font size) ~ sqrt(weight).
  var FONT_MIN = 13;
  var FONT_MAX_DESKTOP = 54;
  var FONT_MAX_MOBILE = 40;
  var MOBILE_BP = 640;

  var GHOST_OPACITY = 0.12; // words absent from the selected era
  var PAD = 3;              // px padding around each word's box when packing
  var AUTOPLAY_MS = 1600;

  function isMobile() {
    return window.matchMedia("(max-width: " + MOBILE_BP + "px)").matches;
  }

  function prefersReducedMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function fontMax() {
    return isMobile() ? FONT_MAX_MOBILE : FONT_MAX_DESKTOP;
  }

  function sizeFor(weight, max) {
    return FONT_MIN + (max - FONT_MIN) * Math.sqrt(Math.max(0, weight));
  }

  function rectsOverlap(a, b) {
    return !(a.x + a.w < b.x || b.x + b.w < a.x || a.y + a.h < b.y || b.y + b.h < a.y);
  }

  // Archimedean-spiral placement: try the centre first, then walk outward until
  // the candidate box clears everything already placed.
  function placeWord(box, placed, cx, cy) {
    var step = 0.35;
    var a = 4; // spiral tightness (px per radian)
    for (var theta = 0; theta < 60 * Math.PI; theta += step) {
      var r = a * theta;
      var x = cx + r * Math.cos(theta) - box.w / 2;
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
      // Pack at the largest size this word ever reaches across all eras, so no
      // era can make it outgrow its slot.
      var peak = t.weight;
      (t.eraWeights || []).forEach(function (w) { if (w > peak) peak = w; });
      var packSize = sizeFor(peak, max);

      meas.style.fontSize = packSize + "px";
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
        packSize: packSize
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
      text.setAttribute("font-size", n.packSize);
      text.textContent = t.term;
      // Set the theme color inline from the data so word colors never depend on
      // the external stylesheet loading (or a stale cached copy of it).
      var themeColor = themes[t.theme] && themes[t.theme].color;
      if (themeColor) text.style.fill = themeColor;

      a.appendChild(text);
      svg.appendChild(a);
      wordEls.push({ el: text, wrap: a, term: t, packSize: n.packSize });
    });

    return { wordEls: wordEls, max: max };
  }

  // Apply an era's weights to already-placed words (rescale + fade in place).
  function applyEra(wordEls, max, eraIndex) {
    wordEls.forEach(function (w) {
      var t = w.term;
      var weight, present;
      if (eraIndex === 0) {
        weight = t.weight; present = true; // "All time"
      } else {
        weight = (t.eraWeights || [])[eraIndex - 1] || 0;
        present = weight > 0;
      }
      var size = present ? sizeFor(weight, max) : FONT_MIN;
      w.el.setAttribute("font-size", size);
      w.el.style.opacity = present ? "1" : String(GHOST_OPACITY);
    });
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

  function setupControls(root, data, wordEls, max) {
    var controls = root.querySelector(".wc-controls");
    var slider = root.querySelector(".wc-slider");
    var label = root.querySelector(".wc-era-label");
    var play = root.querySelector(".wc-play");
    if (!controls || !slider || !label) return;

    var eras = data.eras || [];
    // Slider stops: 0 = All time, then one per era.
    slider.min = "0";
    slider.max = String(eras.length);
    slider.value = "0";

    function labelFor(idx) {
      if (idx === 0) return { main: "All time", sub: "every era combined" };
      var e = eras[idx - 1];
      return { main: e.label, sub: e.sub };
    }

    function update(idx) {
      applyEra(wordEls, max, idx);
      var l = labelFor(idx);
      label.innerHTML = "";
      label.appendChild(document.createTextNode(l.main));
      var sub = document.createElement("span");
      sub.className = "wc-era-sub";
      sub.textContent = l.sub;
      label.appendChild(sub);
    }

    slider.addEventListener("input", function () {
      stop();
      update(parseInt(slider.value, 10));
    });

    var timer = null;
    function playing() { return timer !== null; }
    function stop() {
      if (timer) { clearInterval(timer); timer = null; }
      if (play) { play.setAttribute("aria-pressed", "false"); play.textContent = "▶ Play evolution"; }
    }
    function start() {
      if (playing()) return;
      if (play) { play.setAttribute("aria-pressed", "true"); play.textContent = "❚❚ Pause"; }
      timer = setInterval(function () {
        var next = (parseInt(slider.value, 10) + 1) % (eras.length + 1);
        slider.value = String(next);
        update(next);
      }, AUTOPLAY_MS);
    }

    if (play) {
      if (prefersReducedMotion()) {
        play.hidden = true; // no autoplay when motion is unwelcome
      } else {
        play.addEventListener("click", function () {
          if (playing()) stop(); else start();
        });
      }
    }

    controls.hidden = false;
    update(0);
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
        setupControls(root, data, built.wordEls, built.max);
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
