/*
 * Adds a "Copy" button to each bio block on press.html.
 *
 * Every block marked [data-copy] gets one button; the text copied is the block's
 * own textContent, so the bios live in the HTML and there is no second copy of
 * them here to drift out of sync. Editing a bio needs no change to this file.
 *
 * The clipboard path mirrors js/pub-bibtex.js: navigator.clipboard where it is
 * available, and a hidden-textarea + execCommand fallback for non-secure
 * contexts (file://, plain http), where navigator.clipboard is undefined.
 *
 * Progressive enhancement: with JS off, or if this script fails, the bios are
 * still on the page as ordinary selectable text. The button is the convenience,
 * not the content.
 */
(function () {
  "use strict";

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
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

  function attach(block) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "bib-copy press-copy";
    btn.textContent = "Copy";

    // The button labels itself: no separate live region to announce, and the
    // label reverts so a second copy reads the same as the first.
    btn.addEventListener("click", function () {
      var text = block.textContent.replace(/\s+/g, " ").trim();
      copyText(text).then(function () {
        btn.textContent = "Copied";
        btn.classList.add("is-copied");
      }).catch(function () {
        btn.textContent = "Press ⌘C";
      });
      setTimeout(function () {
        btn.textContent = "Copy";
        btn.classList.remove("is-copied");
      }, 2000);
    });

    block.appendChild(btn);
  }

  var blocks = document.querySelectorAll("[data-copy]");
  for (var i = 0; i < blocks.length; i++) attach(blocks[i]);
})();
