// The page of findings per check: one tab per check. Each tab reads the file
// ../data/modules/<check>.json, which the scheduled run (scripts/update.py)
// writes from the full results. The address ends in #<check> for each tab,
// so a tab can be linked to (modules/#stat_check).

// every check, in the order of the report, with the check's own title
var TABS = [
  { id: "ethics_check", label: "Ethics Approval Check" },
  { id: "power", label: "Power Analysis Check" },
  { id: "prereg_check", label: "Preregistration Check" },
  { id: "marginal", label: "Marginal Significance" },
  { id: "stat_check", label: "StatCheck", render: renderStatCheck },
  { id: "stat_p_exact", label: "Exact P-Values" },
  { id: "stat_p_nonsig", label: "Non-Significant P Value Check" },
  { id: "stat_effect_size", label: "Effect Sizes in t-tests and F-tests" },
  { id: "codebook_check", label: "Codebook Check" },
  { id: "repo_check", label: "Repository Check" },
  { id: "code_check", label: "Code Check" },
  { id: "data_check", label: "Data Check", render: renderDataCheck },
  { id: "reproducibility_check", label: "Reproducibility Check", render: renderReproducibility },
  { id: "ref_pubpeer", label: "PubPeer Comments" },
  { id: "ref_retraction", label: "RetractionWatch" },
  { id: "ref_replication", label: "Replication Check" }
];
TABS.forEach(function (t) { if (!t.render) t.render = renderSummary; });

function el(tag, attrs, text) {
  var e = document.createElement(tag);
  for (var k in attrs) e.setAttribute(k, attrs[k]);
  if (text) e.textContent = text;
  return e;
}

// "p = .011" or "p < .001", as APA writes it
function pText(x) {
  if (x === null || x === undefined || isNaN(x)) return "p unknown";
  if (x < 0.001) return "p < .001";
  return "p = " + x.toFixed(3).replace(/^0/, "");
}

// the paper's own p-value, as the test was written: "p = .174", "p < 0.05"
function reportedText(f) {
  var all = (f.test || "").match(/p\s*[<>=≤≥]\s*[0-9.]+/gi);
  if (all) return all[all.length - 1].replace(/\s*([<>=≤≥])\s*/, " $1 ");
  return "p " + (f.p_comp || "=") + " " + f.reported_p;
}

// the line naming the preprint: its title links to its report, then its OSF id
// and its OSF page
function source(p) {
  var line = el("p", { class: "note source" });
  var title = p.report_page ? el("a", { href: "../" + p.id + "/" }, p.title) : el("span", {}, p.title);
  title.className = "paper-title";
  line.appendChild(title);
  line.appendChild(document.createTextNode(" · " + p.id + " · "));
  line.appendChild(el("a", { href: p.url, target: "_blank", rel: "noopener" }, "OSF"));
  return line;
}

// the sentence, with the test that was checked marked
function sentence(text, part) {
  var q = el("blockquote", { class: "sentence" });
  var i = part ? text.indexOf(part) : -1;
  if (i < 0) { q.textContent = text; return q; }
  q.appendChild(document.createTextNode(text.slice(0, i)));
  q.appendChild(el("mark", {}, part));
  q.appendChild(document.createTextNode(text.slice(i + part.length)));
  return q;
}

function renderStatCheck(panel, data) {
  var changes = [], other = [];
  data.papers.forEach(function (p) {
    p.findings.forEach(function (f) { (f.decision_error ? changes : other).push({ paper: p, f: f }); });
  });
  var n = changes.length + other.length;
  panel.appendChild(el("h2", {}, "P-values that do not match their test"));
  panel.appendChild(el("p", {},
    "Metacheck computes each p-value again from the test statistic and the degrees of freedom " +
    "reported with it, for t-tests and F-tests. These are the p-values that differ from the " +
    "computed value: " + n + " in " + data.papers.length +
    (data.papers.length === 1 ? " preprint." : " preprints.")));
  [["The conclusion changes", "the reported and the computed p-value are on different sides of .05", changes],
   ["The p-value differs, the conclusion does not", "", other]].forEach(function (g) {
    if (!g[2].length) return;
    var h = el("h3", {}, g[0] + " (" + g[2].length + ")");
    panel.appendChild(h);
    if (g[1]) panel.appendChild(el("p", { class: "note" }, g[1].charAt(0).toUpperCase() + g[1].slice(1) + "."));
    var list = el("ol", { class: "findings" });
    g[2].forEach(function (x) {
      var li = el("li");
      li.appendChild(sentence(x.f.sentence, x.f.test));
      var nums = "Reported: " + reportedText(x.f) + ". Computed from " + x.f.test.replace(/,?\s*p\s*[<>=≤≥].*$/i, "") +
        ": " + pText(x.f.computed_p) + ".";
      if (x.f.one_tailed_in_text) nums += " The paper mentions a one-tailed test, which halves the p-value.";
      li.appendChild(el("p", { class: "numbers" }, nums));
      li.appendChild(source(x.paper));
      list.appendChild(li);
    });
    panel.appendChild(list);
  });
  if (!n) panel.appendChild(el("p", { class: "note" }, "No mismatches found yet."));
}

// Why a script did not run through: metacheck's `reason` (its
// .repro_failure_reason()). The first kinds are in the code itself; the last
// are limits of the check, which the code may not have on the authors' computer.
var IN_THE_CODE = [
  ["file", "A file the code reads or writes is not where the code looks for it"],
  ["undefined", "The code uses an object or function it does not create"],
  ["syntax", "The code could not be read"],
  ["other", "The code stopped with another error"]
];
var NOT_CHECKED = [
  ["package", "A package could not be installed"],
  ["environment", "The code needs software that our computer does not have"],
  ["internet", "The code needs the internet, which the check does not give it"],
  ["time", "The code ran longer than the time limit"],
  ["interactive", "The code waits for a person to answer"],
  ["download", "A file was too large to download"]
];
var SHOW_SCRIPTS = 3;    // scripts shown per entry; the others behind "more"

function scriptItem(f) {
  var li = el("li");
  li.appendChild(el("code", { class: "file" }, f.file));
  if (f.message) {
    li.appendChild(document.createTextNode(": "));
    li.appendChild(el("code", { class: "message" }, f.message));
  } else if (f.reason === "time") {
    li.appendChild(document.createTextNode(": still running at the time limit."));
  }
  if (f.missing_files) {
    li.appendChild(el("span", { class: "note missing" }, "Files it reads that are not in the repository: " + f.missing_files));
  }
  return li;
}

function renderReproducibility(panel, data) {
  var nScripts = 0;
  data.papers.forEach(function (p) { nScripts += p.findings.length; });
  panel.appendChild(el("h2", {}, "Code that did not run"));
  panel.appendChild(el("p", {},
    "Metacheck runs the R and Python code in the repositories a preprint links to: each script on its own " +
    "in an isolated container, with a time limit, using the current versions of the packages. These are " +
    "the scripts that did not run through: " + nScripts + " in " + data.papers.length +
    (data.papers.length === 1 ? " preprint" : " preprints") + ", grouped by why they stopped. A preprint can " +
    "appear under more than one reason. A script can also stop because a package works differently " +
    "now than in the version the authors used."));

  function group(kinds, heading, note) {
    var any = false;
    kinds.forEach(function (k) {
      // one entry per preprint with scripts of this kind, newest preprint first
      var entries = data.papers.map(function (p) {
        return { paper: p, scripts: p.findings.filter(function (f) { return f.reason === k[0]; }) };
      }).filter(function (e) { return e.scripts.length; });
      if (!entries.length) return;
      if (!any && heading) {
        panel.appendChild(el("h2", { class: "subgroup" }, heading));
        if (note) panel.appendChild(el("p", { class: "note" }, note));
      }
      any = true;
      panel.appendChild(el("h3", {}, k[1] + " (" + entries.length +
        (entries.length === 1 ? " preprint)" : " preprints)")));
      var list = el("ol", { class: "findings" });
      entries.forEach(function (e) {
        var li = el("li");
        var src = source(e.paper);
        src.appendChild(document.createTextNode(" · " + e.paper.findings.length + " of " + e.paper.scripts +
          (e.paper.scripts === 1 ? " script" : " scripts") + " did not run through"));
        li.appendChild(src);
        var ul = el("ul", { class: "scripts" });
        e.scripts.slice(0, SHOW_SCRIPTS).forEach(function (f) { ul.appendChild(scriptItem(f)); });
        li.appendChild(ul);
        if (e.scripts.length > SHOW_SCRIPTS) {
          var more = el("details", { class: "more" });
          var rest = e.scripts.length - SHOW_SCRIPTS;
          more.appendChild(el("summary", {}, rest + (rest === 1 ? " more script" : " more scripts")));
          var ul2 = el("ul", { class: "scripts" });
          e.scripts.slice(SHOW_SCRIPTS).forEach(function (f) { ul2.appendChild(scriptItem(f)); });
          more.appendChild(ul2);
          li.appendChild(more);
        }
        list.appendChild(li);
      });
      panel.appendChild(list);
    });
  }
  group(IN_THE_CODE, "", "");
  group(NOT_CHECKED, "Could not be checked",
    "These scripts stopped on a limit of the check itself, so they may well run on the authors' computer.");
  if (!data.papers.length) panel.appendChild(el("p", { class: "note" }, "No scripts that did not run found yet."));
}

// The check's summary, written in Markdown: lines starting with "-" become a
// list; ** and * (bold, italics) and backquotes are left out
function summary(text) {
  var box = el("div", { class: "summary" });
  var list = null;
  (text || "").split(/\n/).forEach(function (line) {
    var plain = line.replace(/\*\*|\*|`/g, "").trim();
    if (!plain) return;
    if (/^-\s*/.test(plain)) {
      if (!list) { list = el("ul"); box.appendChild(list); }
      list.appendChild(el("li", {}, plain.replace(/^-\s*/, "")));
    } else {
      list = null;
      box.appendChild(el("p", {}, plain));
    }
  });
  return box;
}

// one flagged sentence (with the flagged part marked) or cited reference
function findingItem(f) {
  var li = el("li");
  if (f.sentence) li.appendChild(sentence(f.sentence, f.mark || ""));
  if (f.reference) li.appendChild(el("p", { class: "reference" }, f.reference));
  if (f.note || f.link) {
    var p = el("p", { class: "note" }, f.note || "");
    if (f.link) {
      if (f.note) p.appendChild(document.createTextNode(" "));
      p.appendChild(el("a", { href: f.link, target: "_blank", rel: "noopener" }, "Link"));
    }
    li.appendChild(p);
  }
  return li;
}

// the first SHOW_SCRIPTS items of a list, the others behind "n more"
function capped(items, make, word) {
  var box = el("div");
  var ul = el("ul", { class: "scripts" });
  items.slice(0, SHOW_SCRIPTS).forEach(function (x) { ul.appendChild(make(x)); });
  box.appendChild(ul);
  if (items.length > SHOW_SCRIPTS) {
    var rest = items.length - SHOW_SCRIPTS;
    var more = el("details", { class: "more" });
    more.appendChild(el("summary", {}, rest + " more " + word + (rest === 1 ? "" : "s")));
    var ul2 = el("ul", { class: "scripts" });
    items.slice(SHOW_SCRIPTS).forEach(function (x) { ul2.appendChild(make(x)); });
    more.appendChild(ul2);
    box.appendChild(more);
  }
  return box;
}

var LIGHTS = [["red", "Red"], ["yellow", "Yellow"], ["info", "For information"]];

// the tab of a check: its preprints, by traffic light, each with the check's
// summary and the sentences or references it flagged
function renderSummary(panel, data, tab) {
  panel.appendChild(el("h2", {}, tab.label));
  panel.appendChild(el("p", {}, "The preprints where this check gave red, yellow or \"for information\": " +
    data.papers.length + ". Each with the check's summary, and the sentences or cited references it flagged, " +
    "if it flags those."));
  LIGHTS.forEach(function (l) {
    var papers = data.papers.filter(function (p) { return p.light === l[0]; });
    if (!papers.length) return;
    panel.appendChild(el("h3", { class: "light-" + l[0] }, l[1] + " (" + papers.length +
      (papers.length === 1 ? " preprint)" : " preprints)")));
    var list = el("ol", { class: "findings" });
    papers.forEach(function (p) {
      var li = el("li");
      li.appendChild(source(p));
      li.appendChild(summary(p.summary));
      if (p.findings && p.findings.length) {
        li.appendChild(capped(p.findings, findingItem, p.findings[0].reference ? "reference" : "sentence"));
      }
      list.appendChild(li);
    });
    panel.appendChild(list);
  });
  if (!data.papers.length) panel.appendChild(el("p", { class: "note" }, "Nothing flagged yet."));
}

// The data check: per preprint its summary, then the problems it found in the
// data files, grouped by kind, each as "file → column: detail"
function dataIssue(f) {
  var li = el("li");
  li.appendChild(el("code", { class: "file" }, f.file + (f.column ? " → " + f.column : "")));
  li.appendChild(document.createTextNode(": " + f.detail));
  return li;
}

function renderDataCheck(panel, data, tab) {
  panel.appendChild(el("h2", {}, tab.label));
  panel.appendChild(el("p", {}, "Metacheck reads the data files in the repositories a preprint links to, and " +
    "checks each column: empty columns, numbers stored as text, stray spaces, inconsistent capitals, " +
    "problematic column names, signs of personal information, spreadsheet formatting, and more. " +
    "The preprints where this check gave red, yellow or \"for information\": " + data.papers.length + "."));
  panel.appendChild(el("p", { class: "note" }, "The flags for personal information are pattern matches, " +
    "tuned to flag too much rather than too little: a column named \"email\" is flagged whether or not it " +
    "holds e-mail addresses. A flag means: look at this column. Where the data is already de-identified, " +
    "nothing needs to be done."));
  LIGHTS.forEach(function (l) {
    var papers = data.papers.filter(function (p) { return p.light === l[0]; });
    if (!papers.length) return;
    panel.appendChild(el("h3", { class: "light-" + l[0] }, l[1] + " (" + papers.length +
      (papers.length === 1 ? " preprint)" : " preprints)")));
    var list = el("ol", { class: "findings" });
    papers.forEach(function (p) {
      var li = el("li");
      li.appendChild(source(p));
      li.appendChild(summary(p.summary));
      // the kinds of problem, the most frequent first
      var kinds = {};
      (p.findings || []).forEach(function (f) { (kinds[f.label] = kinds[f.label] || []).push(f); });
      Object.keys(kinds).sort(function (a, b) { return kinds[b].length - kinds[a].length; })
        .forEach(function (k) {
          li.appendChild(el("p", { class: "issue-kind" }, k + " (" + kinds[k].length + ")"));
          li.appendChild(capped(kinds[k], dataIssue, "column"));
        });
      list.appendChild(li);
    });
    panel.appendChild(list);
  });
  if (!data.papers.length) panel.appendChild(el("p", { class: "note" }, "Nothing flagged yet."));
}

function show(id) {
  var tab = TABS.filter(function (t) { return t.id === id; })[0] || TABS[0];
  document.querySelectorAll("#tabs button").forEach(function (b) {
    b.setAttribute("aria-selected", b.getAttribute("data-id") === tab.id ? "true" : "false");
  });
  var panel = document.getElementById("panel");
  panel.textContent = "";
  panel.appendChild(el("p", { class: "note" }, "Loading…"));
  fetch("../data/modules/" + tab.id + ".json")
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (data) { panel.textContent = ""; tab.render(panel, data, tab); })
    .catch(function () {
      panel.textContent = "";
      panel.appendChild(el("p", { class: "note" }, "The findings could not be loaded."));
    });
}

TABS.forEach(function (t) {
  var b = el("button", { type: "button", role: "tab", "data-id": t.id }, t.label);
  b.addEventListener("click", function () { location.hash = t.id; });
  document.getElementById("tabs").appendChild(b);
});
window.addEventListener("hashchange", function () { show(location.hash.slice(1)); });
show(location.hash.slice(1));
