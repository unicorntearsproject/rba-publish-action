// The Crisp sites' light and dark themes (ADR-043, ADR-044). Loaded synchronously in <head>, so
// the theme is set before the first paint. Crisp Desktop is light by default and Crisp Cloud
// dark (navy); the sun/moon toggle in the nav switches, and the choice is remembered in
// localStorage. Without storage (private windows, blocked site data) the toggle still works for
// the visit; without JavaScript each site shows its default. rustybucket.ai is untouched.
// First-party, no inline handlers; CSP script-src 'self'.
(function () {
  "use strict";
  var root = document.documentElement;
  var cloud = root.classList.contains("crisp-cloud");
  if (!cloud && !root.classList.contains("crisp-desktop")) return;
  var KEY = "crisp-theme";

  function saved() {
    try { return window.localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function remember(theme) {
    try { window.localStorage.setItem(KEY, theme); } catch (e) { /* the page works without it */ }
  }
  function apply(dark) {
    root.classList.toggle("theme-dark", dark);
    root.classList.toggle("theme-light", !dark);
    var scheme = document.querySelector('meta[name="color-scheme"]');
    var color = document.querySelector('meta[name="theme-color"]');
    if (scheme) scheme.setAttribute("content", dark ? "dark" : "light");
    if (color) color.setAttribute("content", dark ? "#020b23" : "#ffffff");
  }

  var choice = saved();
  var dark = choice ? choice === "dark" : cloud;   // the site's own default
  apply(dark);

  document.addEventListener("DOMContentLoaded", function () {
    var toggle = document.querySelector(".theme-toggle");
    if (!toggle) return;
    function label() {
      toggle.setAttribute("aria-pressed", dark ? "true" : "false");
      toggle.setAttribute("aria-label", "Dark theme");
      toggle.title = dark ? "Switch to the light theme" : "Switch to the dark theme";
    }
    toggle.hidden = false;   // it does nothing without this script, so it starts hidden
    label();
    toggle.addEventListener("click", function () {
      dark = !dark;
      apply(dark);
      remember(dark ? "dark" : "light");
      label();
    });
  });
})();
