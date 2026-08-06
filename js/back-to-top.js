/*
 * Reveals a "back to top" control once the visitor has scrolled past a screenful.
 *
 * The button is built here rather than sitting in every page's markup: it is pure
 * convenience, and a control that scrolls you to content already above you has
 * nothing to offer a reader who cannot scroll. With JS off nothing is added and
 * no page loses anything — the same progressive-enhancement rule the rest of the
 * site follows.
 *
 * It is a real <a href="#top">, not a scroll-to button, so it works before this
 * script's listener attaches, lands focus on the top of the document for keyboard
 * users, and leaves a usable history entry. Smooth scrolling comes from the
 * stylesheet's `scroll-behavior`, which already honours prefers-reduced-motion.
 */
(function () {
  "use strict";

  // Roughly one screenful: below this the control would point at content still
  // in view, which is just clutter.
  var THRESHOLD = 600;

  var link = document.createElement("a");
  link.className = "to-top";
  link.href = "#top";
  link.hidden = true;
  // The arrow is decorative; the label is what assistive tech announces.
  link.setAttribute("aria-label", "Back to top");
  link.innerHTML = '<span aria-hidden="true">↑</span>';

  link.addEventListener("click", function () {
    // Anchor navigation alone does not move keyboard focus, so send it to the
    // header explicitly; otherwise the next Tab resumes from the footer.
    var header = document.querySelector(".site-header");
    if (header) {
      header.setAttribute("tabindex", "-1");
      header.focus({ preventScroll: true });
    }
  });

  document.body.appendChild(link);

  var ticking = false;
  function update() {
    link.hidden = (window.pageYOffset || document.documentElement.scrollTop) < THRESHOLD;
    ticking = false;
  }

  window.addEventListener("scroll", function () {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(update);
  }, { passive: true });

  update();
})();
