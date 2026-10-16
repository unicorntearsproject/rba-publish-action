// Fun mode and Corporate mode (ADR-039). Loaded synchronously in <head>, before
// the stylesheet, so html[data-mode] is set before the first paint (no flash).
// First-party, no inline handlers; CSP script-src 'self'. Without JavaScript the
// page simply stays in fun mode.
//
// The choice is remembered across rustybucket.ai and software.rustybucket.ai by a
// functional first-party cookie on .rustybucket.ai (rb-mode=corporate, SameSite=Lax,
// one year; the default, fun, needs no cookie). ?mode=corporate or ?mode=fun sets it
// from a link.
(function () {
  "use strict";
  var root = document.documentElement;

  function readCookie() {
    var m = /(?:^|;\s*)rb-mode=(corporate|fun)(?:;|$)/.exec(document.cookie);
    return m ? m[1] : null;
  }

  function writeCookie(mode) {
    var shared = /(^|\.)rustybucket\.ai$/.test(location.hostname) ? "; Domain=.rustybucket.ai" : "";
    var secure = location.protocol === "https:" ? "; Secure" : "";
    var age = mode === "corporate" ? 31536000 : 0;   // fun is the default: clear the cookie
    document.cookie = "rb-mode=" + (mode === "corporate" ? "corporate" : "") + shared +
      "; Path=/; SameSite=Lax; Max-Age=" + age + secure;
  }

  // The browser's own colour scheme and theme colour follow the mode
  function paint(mode) {
    root.setAttribute("data-mode", mode);
    var scheme = document.querySelector('meta[name="color-scheme"]');
    var theme = document.querySelector('meta[name="theme-color"]');
    if (scheme) scheme.setAttribute("content", mode === "corporate" ? "light" : "dark");
    if (theme) theme.setAttribute("content", mode === "corporate" ? "#ffffff" : "#00111a");
  }

  var link = /[?&]mode=(corporate|fun)(?:&|#|$)/.exec(location.search);
  var mode = link ? link[1] : (readCookie() || "fun");
  if (link) writeCookie(mode);
  paint(mode);

  document.addEventListener("DOMContentLoaded", function () {
    var toggle = document.querySelector(".mode-toggle");
    if (!toggle) return;
    toggle.hidden = false;   // it does nothing without this script, so it starts hidden
    toggle.setAttribute("aria-pressed", mode === "corporate" ? "true" : "false");
    toggle.addEventListener("click", function () {
      mode = mode === "corporate" ? "fun" : "corporate";
      writeCookie(mode);
      paint(mode);
      toggle.setAttribute("aria-pressed", mode === "corporate" ? "true" : "false");
    });
  });
})();
