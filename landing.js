// Fills the counter in the top right from data/tally.json and the list of
// reports from data/index.json, which the scheduled run (scripts/update.py)
// writes.
fetch("data/tally.json")
  .then(function (r) { return r.json(); })
  .then(function (t) {
    document.getElementById("checked-count").textContent =
      t.reports.toLocaleString("en") + (t.reports === 1 ? " preprint checked" : " preprints checked");
  })
  .catch(function () {});

function el(tag, attrs, text) {
  var e = document.createElement(tag);
  for (var k in attrs) e.setAttribute(k, attrs[k]);
  if (text) e.textContent = text;
  return e;
}

// One line per checked preprint, newest first: the title links to the report
// page (<id>/, e.g. jc6rp_v1/), then the authors, the date, and the OSF page.
fetch("data/index.json")
  .then(function (r) { return r.json(); })
  .then(function (idx) {
    var list = document.getElementById("report-list");
    idx.papers.forEach(function (p) {
      var li = el("li");
      // greyed out when no check applied to the paper (every module "na")
      var lights = Object.keys(p.lights || {}).map(function (k) { return p.lights[k]; });
      if (lights.length && lights.every(function (l) { return l === "na"; })) li.className = "not-applicable";
      var title = p.report_page ? el("a", { href: p.id + "/" }, p.title) : el("span", {}, p.title);
      title.className = "report-title";
      li.appendChild(title);
      var meta = el("p", { class: "note" });
      var authors = p.authors || [];
      meta.appendChild(document.createTextNode(
        (authors.length > 3 ? authors.slice(0, 3).join(", ") + " et al." : authors.join(", ")) +
        " · " + (p.published || "").slice(0, 10) + " · " + p.id + " · "));
      meta.appendChild(el("a", { href: p.url, target: "_blank", rel: "noopener" }, "OSF"));
      li.appendChild(meta);
      li.setAttribute("data-search", fold([p.title, authors.join(" "), p.id].join(" ")));
      list.appendChild(li);
    });
    search();
  })
  .catch(function () {});

// Lower case, without accents (é -> e), for the search; also the letters that
// are not a letter with an accent (ł -> l, ø -> o, ß -> ss, ...)
var PLAIN = { "ł": "l", "ø": "o", "đ": "d", "ß": "ss", "æ": "ae", "œ": "oe" };
function fold(s) {
  return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
    .replace(/[łøđßæœ]/g, function (c) { return PLAIN[c]; });
}

// Shows only the preprints whose title, authors or OSF id contain every word
// typed in the search field
function search() {
  var words = fold(document.getElementById("report-search").value).split(/\s+/).filter(Boolean);
  var items = document.querySelectorAll("#report-list li");
  var shown = 0;
  items.forEach(function (li) {
    var text = li.getAttribute("data-search") || "";
    var match = words.every(function (w) { return text.indexOf(w) !== -1; });
    li.hidden = !match;
    if (match) shown++;
  });
  document.getElementById("no-match").hidden = shown > 0 || items.length === 0;
}
document.getElementById("report-search").addEventListener("input", search);
