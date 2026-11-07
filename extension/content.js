// Metacheck reports for PsyArXiv: on a PsyArXiv preprint page, a button in
// the bottom right corner that opens Metacheck's report on that preprint, when
// the site https://lakens.github.io/psyarxiv-reproducibility/ has one (it
// reads the site's data/index.json). Nothing is shown otherwise.
//
// Pages: osf.io/preprints/psyarxiv/<id>, next.psyarxiv.org/preprints/<id>,
// and OSF's short links osf.io/<id>; <id> with or without its version ending
// (jc6rp_v1 or jc6rp). These sites change the address without loading a new
// page, so the address is checked every second.
(function () {
  "use strict";

  var SITE = "https://lakens.github.io/psyarxiv-reproducibility/";

  // The preprint in an address: {base: "jc6rp", version: 1}, version null
  // when the address has none; null when the address is not a preprint's.
  function preprintId(href) {
    var u;
    try { u = new URL(href); } catch (e) { return null; }
    var path = u.pathname, m = null;
    if (u.hostname === "osf.io") {
      m = path.match(/^\/preprints\/psyarxiv\/([a-z0-9]+)(?:_v(\d+))?(?:\/|$)/i) ||
          path.match(/^\/([a-z0-9]{5})(?:_v(\d+))?\/?$/i);
    } else if (u.hostname === "next.psyarxiv.org") {
      m = path.match(/^\/preprints\/([a-z0-9]+)(?:_v(\d+))?(?:\/|$)/i);
    }
    if (!m) return null;
    return { base: m[1].toLowerCase(), version: m[2] ? parseInt(m[2], 10) : null };
  }

  // The report for a preprint in the site's list: that version's when there
  // is one, else the newest version checked. {paper, exact} or null.
  function findReport(papers, id) {
    var same = (papers || []).filter(function (p) {
      return (p.base_id || String(p.id).split("_v")[0]) === id.base;
    });
    if (!same.length) return null;
    if (id.version !== null) {
      var exact = same.filter(function (p) { return p.version === id.version; })[0];
      if (exact) return { paper: exact, exact: true };
    }
    same.sort(function (a, b) { return b.version - a.version; });
    return { paper: same[0], exact: id.version === null };
  }

  // No check applied to the paper: every module's light "na" (grey on the site)
  function noneApplied(p) {
    var lights = Object.keys(p.lights || {}).map(function (k) { return p.lights[k]; });
    return lights.length > 0 && lights.every(function (l) { return l === "na"; });
  }

  // for the tests (node), which have no page
  if (typeof document === "undefined") {
    if (typeof module !== "undefined") {
      module.exports = { preprintId: preprintId, findReport: findReport, noneApplied: noneApplied };
    }
    return;
  }

  var index = null;      // the site's list, read once per page
  var shownFor = null;   // the address the button is for
  var hidden = {};       // addresses where the button was closed

  function list() {
    if (!index) {
      index = fetch(SITE + "data/index.json")
        .then(function (r) { return r.ok ? r.json() : { papers: [] }; })
        .then(function (d) { return d.papers || []; })
        .catch(function () { index = null; return []; });
    }
    return index;
  }

  function removeButton() {
    var old = document.getElementById("metacheck-psyarxiv-button");
    if (old) old.remove();
  }

  function showButton(found, href) {
    removeButton();
    var p = found.paper, grey = noneApplied(p);
    var host = document.createElement("div");
    host.id = "metacheck-psyarxiv-button";
    // a shadow root keeps the page's styles out of the button, and the button's out of the page
    var root = host.attachShadow({ mode: "open" });
    var colour = grey ? "#8A8884" : "#2F6F1C", dark = grey ? "#6E6C68" : "#1E4A10";
    root.innerHTML =
      "<style>" +
      ".box{position:fixed;right:20px;bottom:20px;z-index:2147483647;display:flex;align-items:stretch;" +
      "font:600 15px/1.2 'Segoe UI',Arial,sans-serif;box-shadow:0 2px 10px rgba(0,0,0,.25);border-radius:6px;overflow:hidden}" +
      "a{display:flex;align-items:center;gap:8px;padding:9px 14px;background:" + colour + ";color:#fff;text-decoration:none}" +
      "a:hover{background:" + dark + "}" +
      "img{height:22px;width:auto;background:#fff;border-radius:3px;padding:1px}" +
      "button{border:0;background:" + dark + ";color:#fff;font:inherit;cursor:pointer;padding:0 10px}" +
      "</style>" +
      "<div class='box'><a target='_blank' rel='noopener'><img alt=''><span></span></a>" +
      "<button type='button' aria-label='Hide' title='Hide'>×</button></div>";
    var a = root.querySelector("a");
    a.href = SITE + p.id + "/";
    a.title = grey ? "None of the Metacheck modules applied to this preprint"
                   : "Open Metacheck's report on this preprint";
    root.querySelector("img").src = SITE + "images/logo.png";
    root.querySelector("span").textContent =
      found.exact ? "Metacheck report" : "Metacheck report (version " + p.version + ")";
    root.querySelector("button").addEventListener("click", function () {
      hidden[href] = true;
      removeButton();
    });
    document.documentElement.appendChild(host);
  }

  function check() {
    var href = location.href;
    if (href === shownFor) return;
    shownFor = href;
    var id = preprintId(href);
    if (!id || hidden[href]) { removeButton(); return; }
    list().then(function (papers) {
      if (location.href !== href) return;          // the page changed meanwhile
      var found = findReport(papers, id);
      if (found) showButton(found, href); else removeButton();
    });
  }

  check();
  setInterval(check, 1000);
})();
