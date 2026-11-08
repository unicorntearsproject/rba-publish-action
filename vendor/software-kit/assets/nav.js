// The site menu (ADR-035, ADR-045). First-party, no inline handlers; CSP script-src 'self'.
// The drop-downs open on hover and keyboard focus with CSS alone; this adds tap (and click) to
// open and close them, Esc to close one and return focus, a click outside to close, and keeps
// aria-expanded true to what's shown. Without it the menu still works by hover and focus.
(function () {
  "use strict";
  var items = document.querySelectorAll(".nav-item");
  function set(item, open) {
    var button = item.querySelector(".nav-group");
    if (!button) return;
    item.classList.toggle("open", open);
    if (open) item.classList.remove("shut");
    button.setAttribute("aria-expanded", open ? "true" : "false");
  }
  function closeAll(except) {
    for (var i = 0; i < items.length; i++) if (items[i] !== except) set(items[i], false);
  }
  for (var i = 0; i < items.length; i++) {
    (function (item) {
      var button = item.querySelector(".nav-group");
      if (!button) return;
      button.addEventListener("click", function () {
        var open = !item.classList.contains("open");
        closeAll(item);
        set(item, open);
        if (!open) item.classList.add("shut");   // a second tap closes it even under the pointer
      });
      item.addEventListener("mouseenter", function () { item.classList.remove("shut"); });
      item.addEventListener("mouseleave", function () { if (item.classList.contains("open")) set(item, false); });
      item.addEventListener("focusout", function (e) {
        if (item.contains(e.relatedTarget)) return;
        set(item, false);
        item.classList.remove("shut");   // focus left: the next visit opens it again
      });
      item.addEventListener("keydown", function (e) {
        if (e.key !== "Escape") return;
        set(item, false);
        item.classList.add("shut");
        button.focus();
      });
    })(items[i]);
  }
  document.addEventListener("click", function (e) {
    if (!e.target.closest || !e.target.closest(".nav-item")) closeAll(null);
  });
})();
