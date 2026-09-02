/*
 * Renders the "Collaboration Network" on the home page.
 *
 * Data comes from coauthors-data.json, precomputed by tools/build_coauthors.py:
 * an ego network with the site owner removed. Nodes are his most frequent
 * co-authors (sized by shared-paper count, shaded UVA blue->orange by length of
 * collaboration, labeled by surname with the full name as a hover popup); edges
 * weight how many papers two co-authors have published together across all their
 * work (copub.json), not just papers with the owner. Layout coordinates
 * (x, y, r) are precomputed there as the graph's RESTING arrangement; at rest
 * this script simply draws it. Interaction then adds a lightweight in-browser
 * force simulation so the pack feels alive (see setupInteraction).
 *
 * Progressive enhancement: if the fetch fails, JS is off, or the page is opened
 * over file:// (where fetch is blocked), the section keeps its heading and intro
 * and simply shows no graph.
 *
 * Design choices worth knowing:
 *  - SVG (not canvas) so every node is a real <a>, focusable and clickable; each
 *    links to its co-author's filtered publication list (publications.html?author=).
 *  - Edges are faint at rest; hovering/focusing a node lights up that node, its
 *    neighbors, and the ties between them while the rest recede -- the same
 *    "emphasis dims the siblings" idea the word cloud uses.
 *  - Zoom & pan: the wheel zooms toward the cursor and dragging empty space pans
 *    (double-click resets). All content lives in one <g> viewport whose transform
 *    is what zoom/pan move; node dragging maps through that same transform so it
 *    stays correct at any zoom.
 *  - Bubbles are draggable, and a drag is physical: the grabbed bubble is pinned
 *    to the pointer while a small force simulation (each node sprung toward its
 *    precomputed home, springs along edges, hard collisions) lets its neighbors
 *    jostle out of the way and then realign, settling back to the designed layout
 *    when released. Nothing is persisted -- reload restores the layout. The sim
 *    runs only while things are moving and stops once the pack is still, so it
 *    costs nothing at rest. Respects prefers-reduced-motion: there a drag just
 *    moves the one bubble, no jostle.
 */
(function () {
  "use strict";

  var SOURCE = "coauthors-data.json";
  var SVGNS = "http://www.w3.org/2000/svg";

  var LABEL_MIN_FONT = 8;   // below this a label won't fit inside its bubble...
  var LABEL_MAX_FONT = 17;  // ...and above this it stops growing with the bubble
  var LABEL_BELOW_FONT = 11; // font of the full-name popup beneath a hovered bubble
  var DRAG_THRESHOLD = 3;   // svg units of movement before a press counts as a drag

  // --- force simulation tuning (logical/svg units per frame) -----------------
  var K_HOME = 0.02;   // spring pulling each node back to its precomputed home
  var K_EDGE = 0.02;   // spring along each edge toward its designed rest length
  var K_COLL = 0.35;   // fraction of a bubble overlap resolved per frame
  var COLL_PAD = 2;    // extra breathing gap enforced between two bubbles
  var DAMP = 0.85;     // velocity retained per frame (the rest bleeds off)
  var MAX_V = 6;       // per-frame speed cap, so a fast drag can't explode the pack
  var SETTLE_V = 0.08; // stop the loop once the fastest node is slower than this

  // --- zoom limits -----------------------------------------------------------
  var ZOOM_MIN = 1;    // 1 = the fitted view; never zoom out past it
  var ZOOM_MAX = 6;

  var REDUCE = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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
    nodes.forEach(function (n) {
      byId[n.id] = n;
      // Physics state: home is the precomputed resting position the pack realigns
      // to; x/y are the live position (start at home); vx/vy the velocity.
      n.hx = n.x; n.hy = n.y;
      n.vx = 0; n.vy = 0; n.fixed = false;
    });

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

    // Everything lives inside one viewport <g>; zoom/pan move its transform, and
    // node dragging maps pointer coordinates through this same group's CTM.
    var viewport = document.createElementNS(SVGNS, "g");
    viewport.setAttribute("class", "cn-viewport");
    svg.appendChild(viewport);

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
      // na/nb: did endpoint a / endpoint b nominate this tie (one of its own top-N)?
      // Used on hover to color the focused node's own picks vs. ties it accrued.
      // rest: designed separation of the two homes, the edge spring's rest length.
      edgeEls.push({ el: line, a: e.a, b: e.b, na: !!e.na, nb: !!e.nb,
                     nodeA: a, nodeB: b,
                     rest: Math.hypot(a.hx - b.hx, a.hy - b.hy) });
    });
    viewport.appendChild(edgeGroup);

    // A hidden measuring text node, reused for every label (as in wordcloud.js).
    var meas = document.createElementNS(SVGNS, "text");
    meas.setAttribute("x", "-9999");
    meas.setAttribute("y", "-9999");
    meas.style.fontFamily = "Georgia, 'Times New Roman', serif";
    meas.style.fontSize = "10px";
    viewport.appendChild(meas);
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
        n.name + ", " + n.papers +
        (n.papers === 1 ? " paper" : " papers") + " co-authored with me" +
        (n.inst ? ", " + n.inst : ""));

      var circle = document.createElementNS(SVGNS, "circle");
      circle.setAttribute("cx", n.x);
      circle.setAttribute("cy", n.y);
      circle.setAttribute("r", n.r);
      circle.setAttribute("class", "cn-circle");
      circle.style.fill = n.color;
      a.appendChild(circle);

      // Resting label: the surname inside the bubble (n.short, precomputed by
      // build_coauthors). Ambiguous alone ('Wen You' reads as a bubble labeled
      // 'You'), so the full name always appears in the hover popup below.
      var w10 = labelWidthAt10(n.short);
      var fitFont = (2 * n.r - 8) / w10 * 10;      // largest font that fits inside
      var label = null, labelDy = 0;
      if (fitFont >= LABEL_MIN_FONT) {
        label = document.createElementNS(SVGNS, "text");
        var font = Math.max(LABEL_MIN_FONT, Math.min(LABEL_MAX_FONT, fitFont));
        labelDy = font * 0.35;                     // optical vertical centering
        label.setAttribute("text-anchor", "middle");
        label.setAttribute("x", n.x);
        label.setAttribute("y", n.y + labelDy);
        label.setAttribute("font-size", font.toFixed(1));
        label.textContent = n.short;
        // Pale (short-tenure) fills can't carry white text; flip the label to dark
        // ink with a light halo instead (precomputed as n.pale in build_coauthors).
        label.setAttribute("class", n.pale ? "cn-label cn-label-dark" : "cn-label");
        a.appendChild(label);
      }

      // Full-name popup: every node reveals its complete name beneath the bubble
      // while hovered or keyboard-focused (CSS shows .cn-label-hover; surrounding
      // nodes dim at the same time, so the name stays legible over the pack).
      var popDy = n.r + LABEL_BELOW_FONT;
      var pop = document.createElementNS(SVGNS, "text");
      pop.setAttribute("text-anchor", "middle");
      pop.setAttribute("x", n.x);
      pop.setAttribute("y", n.y + popDy);
      pop.setAttribute("font-size", LABEL_BELOW_FONT);
      pop.setAttribute("class", "cn-label cn-label-below cn-label-hover");
      pop.textContent = n.name;
      a.appendChild(pop);

      viewport.appendChild(a);
      nodeEls.push({ el: a, node: n, circle: circle,
                     label: label, labelDy: labelDy, pop: pop, popDy: popDy });
    });

    viewport.removeChild(meas);

    return { viewport: viewport, nodes: nodes, byId: byId,
             nodeEls: nodeEls, edgeEls: edgeEls, neighbors: neighbors };
  }

  // Draw the current positions: circles, labels, and edge endpoints. Called every
  // simulation frame, and once for a rigid (reduced-motion) drag.
  function render(built) {
    built.nodeEls.forEach(function (ne) {
      var n = ne.node;
      ne.circle.setAttribute("cx", n.x.toFixed(2));
      ne.circle.setAttribute("cy", n.y.toFixed(2));
      if (ne.label) {
        ne.label.setAttribute("x", n.x.toFixed(2));
        ne.label.setAttribute("y", (n.y + ne.labelDy).toFixed(2));
      }
      ne.pop.setAttribute("x", n.x.toFixed(2));
      ne.pop.setAttribute("y", (n.y + ne.popDy).toFixed(2));
    });
    built.edgeEls.forEach(function (ee) {
      ee.el.setAttribute("x1", ee.nodeA.x.toFixed(2));
      ee.el.setAttribute("y1", ee.nodeA.y.toFixed(2));
      ee.el.setAttribute("x2", ee.nodeB.x.toFixed(2));
      ee.el.setAttribute("y2", ee.nodeB.y.toFixed(2));
    });
  }

  // The physics: home springs (realign to the designed layout), edge springs
  // (drag neighbors along), and pairwise collision (the visible jostle). One
  // semi-implicit Euler step per animation frame; a fixed (dragged) node is
  // teleported to its pointer target and never integrated.
  function makeSimulation(svg, built) {
    var nodes = built.nodes, edges = built.edgeEls;
    var running = false, raf = 0;

    function step() {
      var i, n, a, b, dx, dy, d, f, ux, uy, over;

      // Reset accumulators, seeding each with its home spring.
      for (i = 0; i < nodes.length; i++) {
        n = nodes[i];
        n.fx = K_HOME * (n.hx - n.x);
        n.fy = K_HOME * (n.hy - n.y);
      }

      // Edge springs toward each tie's designed rest length.
      for (i = 0; i < edges.length; i++) {
        a = edges[i].nodeA; b = edges[i].nodeB;
        dx = b.x - a.x; dy = b.y - a.y;
        d = Math.hypot(dx, dy) || 1e-6;
        f = K_EDGE * (d - edges[i].rest);
        ux = dx / d; uy = dy / d;
        a.fx += f * ux; a.fy += f * uy;
        b.fx -= f * ux; b.fy -= f * uy;
      }

      // Collision: push any overlapping pair apart (this is what "bounces").
      for (i = 0; i < nodes.length; i++) {
        a = nodes[i];
        for (var j = i + 1; j < nodes.length; j++) {
          b = nodes[j];
          dx = b.x - a.x; dy = b.y - a.y;
          var min = a.r + b.r + COLL_PAD;
          var d2 = dx * dx + dy * dy;
          if (d2 >= min * min) continue;
          d = Math.sqrt(d2);
          if (d < 1e-6) { dx = (Math.random() - 0.5); dy = (Math.random() - 0.5); d = 1e-6; }
          over = (min - d) * K_COLL;
          ux = dx / d; uy = dy / d;
          a.fx -= over * ux; a.fy -= over * uy;
          b.fx += over * ux; b.fy += over * uy;
        }
      }

      // Integrate, tracking the fastest node so the loop knows when to stop.
      var maxV = 0, anyFixed = false;
      for (i = 0; i < nodes.length; i++) {
        n = nodes[i];
        if (n.fixed) { n.x = n.tx; n.y = n.ty; n.vx = 0; n.vy = 0; anyFixed = true; continue; }
        n.vx = (n.vx + n.fx) * DAMP;
        n.vy = (n.vy + n.fy) * DAMP;
        var sp = Math.hypot(n.vx, n.vy);
        if (sp > MAX_V) { n.vx *= MAX_V / sp; n.vy *= MAX_V / sp; sp = MAX_V; }
        n.x += n.vx; n.y += n.vy;
        if (sp > maxV) maxV = sp;
      }

      render(built);

      if (anyFixed || maxV > SETTLE_V) {
        raf = requestAnimationFrame(step);
      } else {
        running = false;
      }
    }

    return {
      start: function () { if (!running) { running = true; raf = requestAnimationFrame(step); } }
    };
  }

  // Wheel-zoom toward the cursor and drag-to-pan of empty space, both moving one
  // viewport <g> transform. Pan is clamped so the pack can't be dragged off-panel.
  function setupZoomPan(svg, built) {
    var vp = built.viewport;
    var k = 1, tx = 0, ty = 0;

    function apply() {
      vp.setAttribute("transform", "translate(" + tx.toFixed(2) + "," + ty.toFixed(2) +
                                   ") scale(" + k.toFixed(4) + ")");
    }

    // Screen -> svg user space (viewBox coordinates), the space tx/ty/k live in.
    function toUser(evt) {
      var m = svg.getScreenCTM();
      if (!m) return null;
      var pt = svg.createSVGPoint();
      pt.x = evt.clientX; pt.y = evt.clientY;
      return pt.matrixTransform(m.inverse());
    }

    function clampPan() {
      if (k <= 1) { tx = 0; ty = 0; return; }
      var vb = svg.viewBox.baseVal;
      var minTx = (vb.x + vb.width) * (1 - k), maxTx = vb.x * (1 - k);
      var minTy = (vb.y + vb.height) * (1 - k), maxTy = vb.y * (1 - k);
      tx = Math.max(minTx, Math.min(maxTx, tx));
      ty = Math.max(minTy, Math.min(maxTy, ty));
    }

    svg.addEventListener("wheel", function (evt) {
      evt.preventDefault();
      var p = toUser(evt);
      if (!p) return;
      var wx = (p.x - tx) / k, wy = (p.y - ty) / k;   // world point under cursor
      var nk = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, k * Math.exp(-evt.deltaY * 0.0015)));
      k = nk;
      tx = p.x - wx * k; ty = p.y - wy * k;            // keep that point under cursor
      clampPan();
      apply();
    }, { passive: false });

    // Pan: pointerdown on the background (nodes stopPropagation their own presses).
    var pan = null;
    svg.addEventListener("pointerdown", function (evt) {
      if (k <= 1) return;                 // nothing to pan at the fitted view
      var p = toUser(evt);
      if (!p) return;
      pan = { sx: p.x, sy: p.y, tx0: tx, ty0: ty };
      svg.setPointerCapture(evt.pointerId);
      svg.classList.add("cn-panning");
    });
    svg.addEventListener("pointermove", function (evt) {
      if (!pan) return;
      var p = toUser(evt);
      if (!p) return;
      tx = pan.tx0 + (p.x - pan.sx); ty = pan.ty0 + (p.y - pan.sy);
      clampPan();
      apply();
    });
    function endPan() { pan = null; svg.classList.remove("cn-panning"); }
    svg.addEventListener("pointerup", endPan);
    svg.addEventListener("pointercancel", endPan);

    // Double-click empty space resets to the fitted view.
    svg.addEventListener("dblclick", function (evt) {
      if (evt.target.closest && evt.target.closest(".cn-node")) return;
      k = 1; tx = 0; ty = 0; apply();
    });
  }

  // Dragging a bubble pins it to the pointer and wakes the simulation, so its
  // neighbors jostle and the pack realigns on release. A real drag (past
  // DRAG_THRESHOLD) suppresses the click-through to the publications page. With
  // prefers-reduced-motion the sim is skipped and the one bubble moves rigidly.
  function setupDrag(svg, built, sim) {
    var vp = built.viewport;

    // Screen -> world (node) space: the viewport group's CTM already folds in the
    // viewBox and the current zoom/pan transform, so drags stay true at any zoom.
    function toWorld(evt) {
      var m = vp.getScreenCTM();
      if (!m) return null;
      var pt = svg.createSVGPoint();
      pt.x = evt.clientX; pt.y = evt.clientY;
      return pt.matrixTransform(m.inverse());
    }

    built.nodeEls.forEach(function (ne) {
      var n = ne.node;
      var drag = null;

      ne.el.addEventListener("pointerdown", function (evt) {
        if (evt.pointerType === "mouse" && evt.button !== 0) return;
        var p = toWorld(evt);
        if (!p) return;
        evt.stopPropagation();          // this press drags the node, it does not pan
        drag = { dx: n.x - p.x, dy: n.y - p.y, x0: n.x, y0: n.y, moved: false };
        n.fixed = true; n.tx = n.x; n.ty = n.y;
        ne.el.setPointerCapture(evt.pointerId);
        if (!REDUCE) sim.start();
      });

      ne.el.addEventListener("pointermove", function (evt) {
        if (!drag) return;
        var p = toWorld(evt);
        if (!p) return;
        var x = p.x + drag.dx, y = p.y + drag.dy;
        if (!drag.moved &&
            Math.hypot(x - drag.x0, y - drag.y0) < DRAG_THRESHOLD) return;
        drag.moved = true;
        n.tx = x; n.ty = y;
        if (REDUCE) { n.x = x; n.y = y; render(built); }   // no jostle: move just this one
        else sim.start();
      });

      function endDrag() {
        if (drag && drag.moved) ne.el.setAttribute("data-dragged", "1");
        if (drag) { n.fixed = false; if (!REDUCE) sim.start(); }   // let it realign
        drag = null;
      }
      ne.el.addEventListener("pointerup", endDrag);
      ne.el.addEventListener("pointercancel", endDrag);

      // A completed drag ends with a click on the same element; swallow that one
      // so letting go of a dragged bubble doesn't navigate to the publications page.
      ne.el.addEventListener("click", function (evt) {
        if (ne.el.getAttribute("data-dragged")) {
          ne.el.removeAttribute("data-dragged");
          evt.preventDefault();
        }
      });
    });
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
        ee.el.classList.remove("cn-nom-out", "cn-nom-in");
        if (on) {
          // Did the focused node nominate this tie (its own top-N pick, orange) or
          // merely accrue it because the neighbor nominated it (grey)?
          var mine = (ee.a === id) ? ee.na : ee.nb;
          ee.el.classList.add(mine ? "cn-nom-out" : "cn-nom-in");
        }
      });
    }

    function clear() {
      svg.classList.remove("cn-active");
      built.nodeEls.forEach(function (ne) {
        ne.el.classList.remove("cn-on", "cn-off");
      });
      built.edgeEls.forEach(function (ee) {
        ee.el.classList.remove("cn-on", "cn-off", "cn-nom-out", "cn-nom-in");
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
        var sim = makeSimulation(svg, built);
        setupHighlight(svg, built);
        setupZoomPan(svg, built);
        setupDrag(svg, built, sim);
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
