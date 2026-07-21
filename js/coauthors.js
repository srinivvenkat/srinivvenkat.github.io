/*
 * Renders the "Collaboration Network" on the home page.
 *
 * Data comes from coauthors-data.json, precomputed by tools/build_coauthors.py:
 * an ego network with the site owner removed. Nodes are his most frequent
 * co-authors (sized by shared-paper count, shaded light->dark by length of
 * collaboration); edges weight
 * how many papers two co-authors share with each other. Layout coordinates
 * (x, y, r) are precomputed there — this script does no simulation, it only draws
 * what the precompute produced and wires up interaction, mirroring wordcloud.js.
 *
 * Progressive enhancement: if the fetch fails, JS is off, or the page is opened
 * over file:// (where fetch is blocked), the section keeps its heading and intro
 * and simply shows no graph.
 *
 * Design choices worth knowing:
 *  - SVG (not canvas) so every node is a real <a>, focusable and clickable; each
 *    links to its co-author's filtered publication list (publications.html?author=).
 *  - Edges are faint at rest; hovering/focusing a node lights up that node, its
 *    neighbors, and the ties between them while the rest recede — the same
 *    "emphasis dims the siblings" idea the word cloud uses.
 */
(function () {
  "use strict";

  var SOURCE = "coauthors-data.json";
  var SVGNS = "http://www.w3.org/2000/svg";

  var LABEL_MIN_FONT = 8;   // below this a label won't fit inside its bubble...
  var LABEL_MAX_FONT = 17;  // ...and above this it stops growing with the bubble
  var LABEL_BELOW_FONT = 11; // font used when a label is dropped beneath a bubble

  function edgeWidth(w) {
    return 0.6 + Math.sqrt(w) * 0.25;
  }

  // Measure a label once at a reference size, then scale: getBBox width is linear
  // in font-size, so the largest font that fits a given pixel width is derivable
  // from a single measurement.
  function build(data, svg) {
    var nodes = data.nodes || [];
    var edges = data.edges || [];
    if (!nodes.length) return null;

    var byId = {};
    nodes.forEach(function (n) { byId[n.id] = n; });

    // Adjacency, so a hovered node can light up its neighbors.
    var neighbors = {};
    nodes.forEach(function (n) { neighbors[n.id] = {}; });
    edges.forEach(function (e) {
      if (neighbors[e.a] && neighbors[e.b]) {
        neighbors[e.a][e.b] = true;
        neighbors[e.b][e.a] = true;
      }
    });

    // viewBox from node extents (including radii) plus a margin.
    var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    nodes.forEach(function (n) {
      minX = Math.min(minX, n.x - n.r); minY = Math.min(minY, n.y - n.r);
      maxX = Math.max(maxX, n.x + n.r); maxY = Math.max(maxY, n.y + n.r);
    });
    var m = 14;
    svg.setAttribute("viewBox",
      (minX - m) + " " + (minY - m) + " " +
      (maxX - minX + 2 * m) + " " + (maxY - minY + 2 * m));

    // --- edges (drawn first, so nodes sit on top) ---------------------------
    var edgeGroup = document.createElementNS(SVGNS, "g");
    edgeGroup.setAttribute("class", "cn-edges");
    var edgeEls = [];
    edges.forEach(function (e) {
      var a = byId[e.a], b = byId[e.b];
      if (!a || !b) return;
      var line = document.createElementNS(SVGNS, "line");
      line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
      line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
      line.setAttribute("stroke-width", edgeWidth(e.w).toFixed(2));
      line.setAttribute("class", "cn-edge");
      edgeGroup.appendChild(line);
      edgeEls.push({ el: line, a: e.a, b: e.b });
    });
    svg.appendChild(edgeGroup);

    // A hidden measuring text node, reused for every label (as in wordcloud.js).
    var meas = document.createElementNS(SVGNS, "text");
    meas.setAttribute("x", "-9999");
    meas.setAttribute("y", "-9999");
    meas.style.fontFamily = "Georgia, 'Times New Roman', serif";
    meas.style.fontSize = "10px";
    svg.appendChild(meas);
    function labelWidthAt10(text) {
      meas.textContent = text;
      return meas.getBBox().width || 1;
    }

    // --- nodes --------------------------------------------------------------
    var nodeEls = [];
    nodes.forEach(function (n) {
      var a = document.createElementNS(SVGNS, "a");
      a.setAttribute("href", "publications.html?author=" + encodeURIComponent(n.id));
      a.setAttribute("class", "cn-node");
      a.setAttribute("data-id", n.id);
      a.setAttribute("role", "link");
      a.setAttribute("aria-label",
        n.name + " — " + n.papers +
        (n.papers === 1 ? " paper" : " papers") + " co-authored with me" +
        (n.inst ? ", " + n.inst : ""));

      var circle = document.createElementNS(SVGNS, "circle");
      circle.setAttribute("cx", n.x);
      circle.setAttribute("cy", n.y);
      circle.setAttribute("r", n.r);
      circle.setAttribute("class", "cn-circle");
      circle.style.fill = n.color;
      a.appendChild(circle);

      // Label: fit the last name inside the bubble; if even the minimum font is
      // too wide, drop it just beneath the bubble instead.
      var w10 = labelWidthAt10(n.short);
      var fitFont = (2 * n.r - 8) / w10 * 10;      // largest font that fits inside
      var text = document.createElementNS(SVGNS, "text");
      text.setAttribute("class", "cn-label");
      text.setAttribute("text-anchor", "middle");
      text.textContent = n.short;

      if (fitFont >= LABEL_MIN_FONT) {
        var font = Math.max(LABEL_MIN_FONT, Math.min(LABEL_MAX_FONT, fitFont));
        text.setAttribute("x", n.x);
        text.setAttribute("y", n.y + font * 0.35); // optical vertical centering
        text.setAttribute("font-size", font.toFixed(1));
        // Pale (short-tenure) fills can't carry white text; flip the label to dark
        // ink with a light halo instead (precomputed as n.pale in build_coauthors).
        if (n.pale) text.setAttribute("class", "cn-label cn-label-dark");
      } else {
        text.setAttribute("x", n.x);
        text.setAttribute("y", n.y + n.r + LABEL_BELOW_FONT);
        text.setAttribute("font-size", LABEL_BELOW_FONT);
        text.setAttribute("class", "cn-label cn-label-below");
      }
      a.appendChild(text);

      svg.appendChild(a);
      nodeEls.push({ el: a, node: n });
    });

    svg.removeChild(meas);

    return { nodeEls: nodeEls, edgeEls: edgeEls, neighbors: neighbors };
  }

  // Hovering/focusing a node emphasizes it, its neighbors, and the ties between
  // them; everything else recedes (toggled via a class on the SVG root).
  function setupHighlight(svg, built) {
    var neighbors = built.neighbors;

    function focusNode(id) {
      svg.classList.add("cn-active");
      built.nodeEls.forEach(function (ne) {
        var on = ne.node.id === id || neighbors[id][ne.node.id];
        ne.el.classList.toggle("cn-on", on);
        ne.el.classList.toggle("cn-off", !on);
      });
      built.edgeEls.forEach(function (ee) {
        var on = ee.a === id || ee.b === id;
        ee.el.classList.toggle("cn-on", on);
        ee.el.classList.toggle("cn-off", !on);
      });
    }

    function clear() {
      svg.classList.remove("cn-active");
      built.nodeEls.forEach(function (ne) {
        ne.el.classList.remove("cn-on", "cn-off");
      });
      built.edgeEls.forEach(function (ee) {
        ee.el.classList.remove("cn-on", "cn-off");
      });
    }

    built.nodeEls.forEach(function (ne) {
      var id = ne.node.id;
      ne.el.addEventListener("mouseenter", function () { focusNode(id); });
      ne.el.addEventListener("focus", function () { focusNode(id); });
      ne.el.addEventListener("mouseleave", clear);
      ne.el.addEventListener("blur", clear);
    });
  }

  function init() {
    var root = document.getElementById("coauthors");
    if (!root) return;
    var svg = root.querySelector("svg.cn");
    if (!svg) return;

    fetch(SOURCE)
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        var built = build(data, svg);
        if (!built) return;
        setupHighlight(svg, built);
      })
      .catch(function (err) {
        console.warn("Co-author network unavailable (" + SOURCE + "):", err.message);
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
