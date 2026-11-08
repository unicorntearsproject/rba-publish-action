// The Rusty Bucket site family (ADR-042): rustybucket.ai, crispdesktop.ai and crispcloud.ai.
// Loaded synchronously in <head> on rustybucket.ai and the software hosts. First-party,
// no inline handlers; CSP script-src 'self'.
//
// 1. Corporate mode is retired: ?mode=corporate, or the old rb-mode=corporate cookie, sends
//    the visitor to Crisp Desktop (the same page when it exists there) and clears the cookie.
// 2. One set of software pages serves software.rustybucket.ai, software.crispdesktop.ai and
//    software.crispcloud.ai: on a Crisp host the theme, the nav, the switch, the footer and the
//    canonical link follow the hostname, so a visitor stays on their family's domains.
(function () {
  "use strict";
  var host = location.hostname;
  var family = /(^|\.)crispdesktop\.ai$/.test(host) ? "crispdesktop" :
    /(^|\.)crispcloud\.ai$/.test(host) ? "crispcloud" : "rustybucket";
  var software = host.indexOf("software.") === 0;
  // The pages each site has; /hardware/ and /platforms/ are the same page in two editions
  var PAGES = {
    rustybucket: ["/", "/art/", "/bucketfs/", "/hardware/", "/jason/", "/library/", "/manual/", "/press/", "/process/", "/support/", "/videos/"],
    crispdesktop: ["/", "/art/", "/bucketfs/", "/hardware/", "/jason/", "/library/", "/press/", "/process/", "/support/"],
    crispcloud: ["/", "/art/", "/bucketfs/", "/jason/", "/library/", "/platforms/", "/press/", "/process/", "/support/"]
  };
  function page(path, site) {
    if (PAGES[site].indexOf(path) >= 0) return path;
    if (path === "/hardware/" && site === "crispcloud") return "/platforms/";
    if (path === "/platforms/" && site !== "crispcloud") return "/hardware/";
    return "/";
  }
  function domain(site) { return site === "rustybucket" ? "rustybucket.ai" : site + ".ai"; }

  if (family === "rustybucket") {
    var cookie = /(?:^|;\s*)rb-mode=corporate(?:;|$)/.test(document.cookie);
    if (cookie || /[?&]mode=corporate(?:&|#|$)/.exec(location.search)) {
      if (cookie) {
        document.cookie = "rb-mode=; Domain=.rustybucket.ai; Path=/; SameSite=Lax; Max-Age=0" +
          (location.protocol === "https:" ? "; Secure" : "");
      }
      location.replace(software ? "https://software.crispdesktop.ai" + location.pathname
        : "https://crispdesktop.ai" + page(location.pathname, "crispdesktop"));
    }
    return;
  }

  // A Crisp family host serving the shared software pages (the Crisp sites themselves are
  // built per site and don't load this script)
  var root = document.documentElement;
  root.classList.add("crisp", family === "crispdesktop" ? "crisp-desktop" : "crisp-cloud");
  document.addEventListener("DOMContentLoaded", function () {
    var name = family === "crispdesktop" ? "Crisp Desktop" : "Crisp Cloud";
    var links = document.querySelectorAll("a[href^='https://rustybucket.ai/'], a[href^='https://software.rustybucket.ai/']");
    for (var i = 0; i < links.length; i++) {
      var a = links[i], url = new URL(a.href);
      if (a.closest(".site-switch, .crisp-only")) continue;
      if (url.hostname === "software.rustybucket.ai") url.hostname = "software." + domain(family);
      else { url.pathname = page(url.pathname, family); url.hostname = domain(family); }
      a.href = url.href;
    }
    // The switch: the other two sites, the same software page
    var sw = document.querySelectorAll(".site-switch a");
    var others = family === "crispdesktop" ? [["rustybucket", "Home & Dev"], ["crispcloud", "Cloud Image"]]
      : [["crispdesktop", "Corporate Desktop"], ["rustybucket", "Home & Dev"]];
    for (var j = 0; j < sw.length && j < 2; j++) {
      sw[j].href = "https://" + (software ? "software." : "") + domain(others[j][0]) + location.pathname;
      sw[j].textContent = others[j][1];
    }
    document.title = document.title.replace("Rusty Bucket", name);
    var brand = document.querySelector(".nav-brand-name");
    if (brand) brand.textContent = name;
    var canonical = document.querySelector('link[rel="canonical"]');
    if (canonical) canonical.href = canonical.href.replace("software.rustybucket.ai", "software." + domain(family));
    var marks = document.querySelectorAll(".rb-only");
    for (var k = 0; k < marks.length; k++) marks[k].remove();
  });
})();
