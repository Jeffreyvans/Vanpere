/* VanPere Digital — site shell behaviour.
   Loaded as a classic blocking script in <head> so the .js class lands before
   first paint (reveal/hide styles are gated behind html.js). Everything else
   waits for DOMContentLoaded. CSP: script-src 'self' — no inline code. */
(function () {
  "use strict";

  var root = document.documentElement;
  root.classList.add("js");

  var reduce = window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)")
    : { matches: false };

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  }

  ready(function () {
    var header = document.querySelector("header.site");
    var progress = document.querySelector(".site-progress");
    var bar = document.querySelector(".header-bar");

    /* sticky header state + reading progress (CSSOM only) */
    var ticking = false;
    function onScroll() {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(function () {
        var y = window.pageYOffset || root.scrollTop || 0;
        if (header) header.classList.toggle("is-scrolled", y > 8);
        var max = Math.max(1, root.scrollHeight - window.innerHeight);
        var pct = Math.min(100, (y / max) * 100);
        if (progress) progress.style.width = pct + "%";
        if (bar) bar.style.setProperty("--progress", pct + "%");
        ticking = false;
      });
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    onScroll();

    /* reveal-on-scroll */
    var reveals = root.querySelectorAll("[data-reveal]");
    if (!reveals.length) {
      /* nothing to do */
    } else if (!("IntersectionObserver" in window) || reduce.matches) {
      Array.prototype.forEach.call(reveals, function (el) {
        el.classList.add("is-visible");
      });
    } else {
      var io = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (entry.isIntersecting) {
              entry.target.classList.add("is-visible");
              io.unobserve(entry.target);
            }
          });
        },
        { rootMargin: "0px 0px -6% 0px", threshold: 0.08 }
      );
      Array.prototype.forEach.call(reveals, function (el) { io.observe(el); });
    }

    /* photograph load-in (images that never load still become visible) */
    var shots = document.querySelectorAll(".media img");
    Array.prototype.forEach.call(shots, function (img) {
      function show() { img.classList.add("is-loaded"); }
      if (img.complete) {
        show();
      } else {
        img.addEventListener("load", show, { once: true });
        img.addEventListener("error", show, { once: true });
      }
    });

    /* mobile navigation: checkbox-driven, close it deliberately */
    var toggle = document.getElementById("nav-open");
    if (toggle) {
      var nav = document.querySelector("header.site nav");
      if (nav) {
        nav.addEventListener("click", function (e) {
          var target = e.target;
          while (target && target !== nav) {
            if (target.tagName === "A") { toggle.checked = false; break; }
            target = target.parentNode;
          }
        });
      }
      document.addEventListener("keydown", function (e) {
        if ((e.key === "Escape" || e.key === "Esc") && toggle.checked) {
          toggle.checked = false;
          var label = document.querySelector(".nav-toggle");
          if (label) label.focus();
        }
      });
      var wide = window.matchMedia("(min-width: 761px)");
      var reset = function (e) { if (e.matches) toggle.checked = false; };
      if (wide.addEventListener) wide.addEventListener("change", reset);
      else if (wide.addListener) wide.addListener(reset);
    }
  });
})();
