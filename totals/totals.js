// The page of totals: everything Metacheck counted in the preprints it
// checked, drawn from ../data/totals.json, which scripts/totals.py writes
// once a day from the full results. Every chart is drawn here, without a
// library, so the page loads nothing from other websites (as the rest of the
// site). Each section is drawn on its own: one that fails shows a line saying
// so, and the others are still drawn.

var NS = "http://www.w3.org/2000/svg";
var W = 640;            // the width of the chart being drawn: that of its box (fit())
var C = {               // colours: the report's traffic lights, the site's greens
  red: "#9B2C1F", yellow: "#C08A1E", fine: "#59935B", info: "#2C5577", na: "#DAD8D3",
  fail: "#262624", green: "#2F6F1C", greenLight: "#59935B", greenTint: "#E3ECDF",
  greenDark: "#1E4A10", s1: "#2a78d6", s2: "#eb6834", s3: "#1baf7a", grey: "#A8A6A0",
  mid: "#E4E2DE", surface: "#FCFCFB", text: "#262624"
};
var LIGHTS = [
  { key: "r", label: "To fix", color: C.red },
  { key: "y", label: "To check", color: C.yellow },
  { key: "i", label: "For information", color: C.info },
  { key: "g", label: "Fine", color: C.fine },
  { key: "n", label: "Not applicable", color: C.na },
  { key: "f", label: "The check failed", color: C.fail }
];
var LIGHT = {};
LIGHTS.forEach(function (l) { LIGHT[l.key] = l; });
var SECTION_NAME = { a: "abstract", i: "introduction", m: "method", r: "results", d: "discussion",
                     x: "appendix", f: "figure", t: "table", o: "elsewhere" };
var OUTCOME_NAME = {
  ran_ok: "ran through", errored: "stopped with an error", defines_functions: "only defines functions",
  needs_a_person: "waits for a person to type", run_by_import: "run by another script (import)",
  run_by_source: "run by another script (source)", needs_internet: "needs the internet",
  timed_out: "ran out of time", dependency_unavailable: "needs a package that could not be installed",
  not_parsed: "could not be read as code", not_analysis: "is not an analysis",
  jags_model: "is a JAGS model", not_r_content: "is not R code", python2: "is Python 2",
  out_of_memory: "ran out of memory", skipped_missing_inputs: "skipped: its input files are missing",
  not_downloaded: "could not be downloaded", skipped_time_limit: "skipped: no time left"
};
var REASON_NAME = {
  file: "a file it reads is missing", other: "another error", interactive: "it waits for a person",
  undefined: "something is not defined", package: "a package is missing", internet: "it needs the internet",
  time: "it ran out of time", syntax: "it could not be read as code", environment: "the computer ran out of something",
  download: "its files could not be downloaded", no_message: "it stopped without a message"
};
var NAMING_NAME = {
  "spaces": "spaces in the name", "filename-length-50": "a name longer than 50 characters",
  "unclassifiable": "a file of an unknown kind", "special-characters": "special characters in the name",
  "zero-padding": "numbers without leading zeros (1, 2, 10 sorts as 1, 10, 2)",
  "directory-length-100": "a folder path longer than 100 characters", "diacritics": "accented letters",
  "path-length-228": "a path longer than 228 characters"
};

var D, P, MODS;         // the file, its preprints, its checks
var tip = document.getElementById("tip");

// ---- small helpers -------------------------------------------------------

function el(tag, attrs, text) {
  var e = document.createElement(tag);
  for (var k in attrs) e.setAttribute(k, attrs[k]);
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}
function sv(tag, attrs, parent) {
  var e = document.createElementNS(NS, tag);
  for (var k in attrs) if (attrs[k] !== undefined && attrs[k] !== null) e.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(e);
  return e;
}
function txt(parent, x, y, s, attrs) {
  var t = sv("text", Object.assign({ x: x, y: y }, attrs || {}), parent);
  t.textContent = s;
  return t;
}
// each chart is drawn at the width of the box it is in, so its text has the
// same size in a narrow card as in a wide one
function fit(c) {
  var cs = window.getComputedStyle(c);
  var w = c.clientWidth - parseFloat(cs.paddingLeft || 0) - parseFloat(cs.paddingRight || 0);
  W = Math.max(260, Math.floor(w || 640));
}
function svgOf(h, label) {
  return sv("svg", { viewBox: "0 0 " + W + " " + h, role: "img", "aria-label": label || "" });
}
function esc(s) {
  return String(s === undefined || s === null ? "" : s).replace(/[&<>"]/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
  });
}
function clip(s, n) { s = String(s); return s.length > n ? s.slice(0, n - 1) + "…" : s; }
function fmt(n) {
  if (n === null || n === undefined || isNaN(n)) return "–";
  if (Math.abs(n) < 10 && n % 1) return n.toFixed(Math.abs(n) < 1 ? 2 : 1);
  return Math.round(n).toLocaleString("en-US");
}
function big(n) {
  if (n >= 1e9) return (n / 1e9).toFixed(1).replace(/\.0$/, "") + " billion";
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + " million";
  return fmt(n);
}
function pc(a, b) { return b ? Math.round(100 * a / b) + "%" : "–"; }
function bytes(n) {
  var u = ["bytes", "KB", "MB", "GB", "TB"], k = 0;
  while (n >= 1000 && k < u.length - 1) { n /= 1000; k++; }
  return (k ? n.toFixed(n < 10 ? 1 : 0) : Math.round(n)) + " " + u[k];
}
function sum(a) { var s = 0; a.forEach(function (v) { if (v) s += v; }); return s; }
function mean(a) { return a.length ? sum(a) / a.length : null; }
function sorted(a) { return a.filter(function (v) { return v !== null && v !== undefined && !isNaN(v); }).sort(function (x, y) { return x - y; }); }
function quantile(a, q) {
  var s = sorted(a); if (!s.length) return null;
  var i = (s.length - 1) * q, lo = Math.floor(i), hi = Math.ceil(i);
  return s[lo] + (s[hi] - s[lo]) * (i - lo);
}
function median(a) { return quantile(a, 0.5); }
function maxOf(a) { var m = -Infinity; a.forEach(function (v) { if (v > m) m = v; }); return m; }
function minOf(a) { var m = Infinity; a.forEach(function (v) { if (v < m) m = v; }); return m; }
function count(a, f) { var n = 0; a.forEach(function (v, i) { if (f(v, i)) n++; }); return n; }
function tally(a, f) {
  var c = {};
  a.forEach(function (v) { var k = f(v); if (k !== null && k !== undefined) c[k] = (c[k] || 0) + 1; });
  return c;
}
function toDate(s) {
  if (!s) return null;
  // the OSF's times have no time zone: they are UTC
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z");
}
var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function day(d) { return d.getUTCDate() + " " + MONTHS[d.getUTCMonth()]; }
function dayYear(d) { return day(d) + " " + d.getUTCFullYear(); }
// a label on a time axis: with the hour when the axis spans less than 4 days
function timeTick(t, span) {
  var d = new Date(t);
  return span < 4 * 864e5 ? day(d) + " " + String(d.getUTCHours()).padStart(2, "0") + ":00" : day(d);
}
function ranks(a) {
  var idx = a.map(function (v, i) { return i; }).sort(function (x, y) { return a[x] - a[y]; });
  var r = new Array(a.length), i = 0;
  while (i < idx.length) {
    var j = i;
    while (j + 1 < idx.length && a[idx[j + 1]] === a[idx[i]]) j++;
    for (var k = i; k <= j; k++) r[idx[k]] = (i + j) / 2 + 1;
    i = j + 1;
  }
  return r;
}
function pearson(x, y) {
  var n = x.length; if (n < 3) return null;
  var mx = mean(x), my = mean(y), sxy = 0, sxx = 0, syy = 0;
  for (var i = 0; i < n; i++) { sxy += (x[i] - mx) * (y[i] - my); sxx += (x[i] - mx) * (x[i] - mx); syy += (y[i] - my) * (y[i] - my); }
  return sxx && syy ? sxy / Math.sqrt(sxx * syy) : null;
}
function spearman(x, y) {
  var xs = [], ys = [];
  x.forEach(function (v, i) { if (v !== null && y[i] !== null && !isNaN(v) && !isNaN(y[i])) { xs.push(v); ys.push(y[i]); } });
  return { r: pearson(ranks(xs), ranks(ys)), n: xs.length };
}
function mix(a, b, t) {
  function p(h) { return [1, 3, 5].map(function (i) { return parseInt(h.substr(i, 2), 16); }); }
  var x = p(a), y = p(b);
  return "#" + x.map(function (v, i) { return Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0"); }).join("");
}
function diverging(r) {      // blue for below zero, orange for above, grey at zero
  if (r === null || isNaN(r)) return C.surface;
  return r < 0 ? mix(C.mid, C.s1, Math.min(1, -r)) : mix(C.mid, C.s2, Math.min(1, r));
}
function sequential(t) { return mix(C.greenTint, C.greenDark, Math.max(0, Math.min(1, t))); }
function paperTip(p, extra) {
  return "<b>" + esc(clip(p.t || p.id, 110)) + "</b><br>" + esc(p.id) + (extra ? "<br>" + extra : "");
}
function link(p) { return "../" + p.id + "/"; }

// ---- the box that names what the pointer is on --------------------------

function showTip(e) {
  var t = e.target && e.target.closest ? e.target.closest("[data-tip]") : null;
  if (!t) { tip.hidden = true; return; }
  tip.innerHTML = t.getAttribute("data-tip");
  tip.hidden = false;
  var r = tip.getBoundingClientRect(), x = e.clientX + 14, y = e.clientY + 14;
  if (x + r.width > window.innerWidth - 8) x = Math.max(8, e.clientX - r.width - 14);
  if (y + r.height > window.innerHeight - 8) y = Math.max(8, e.clientY - r.height - 14);
  tip.style.left = x + "px";
  tip.style.top = y + "px";
}
document.addEventListener("pointermove", showTip);
document.addEventListener("pointerdown", showTip);
window.addEventListener("scroll", function () { tip.hidden = true; }, { passive: true });

// ---- scales and axes ------------------------------------------------------

function niceTicks(lo, hi, n) {
  var span = hi - lo;
  if (!(span > 0)) return [lo];
  var step = Math.pow(10, Math.floor(Math.log10(span / n))), err = span / n / step;
  if (err >= 7.5) step *= 10; else if (err >= 3.5) step *= 5; else if (err >= 1.5) step *= 2;
  var t = [];
  for (var v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) t.push(+v.toFixed(10));
  return t;
}
var SUP = { "-": "⁻", 0: "⁰", 1: "¹", 2: "²", 3: "³", 4: "⁴", 5: "⁵", 6: "⁶", 7: "⁷", 8: "⁸", 9: "⁹" };
function tickText(v, mode) {
  if (mode === "log" && v < 0.01) return "10" + String(Math.round(Math.log10(v))).split("").map(function (c) { return SUP[c]; }).join("");
  if (v >= 1e6) return (v / 1e6) + "M";
  if (v >= 1e3) return (v / 1e3) + "k";
  if (v > 0 && v < 1) return String(+v.toPrecision(3)).replace(/^0/, "");
  return String(v);
}
// a scale from values to positions: mode "lin", "log" (values above 0), or
// "log1p" (counts with zeros: the position of log10(1 + value))
function makeScale(vals, mode, r0, r1, dom) {
  var T = mode === "log" ? Math.log10 : mode === "log1p" ? function (v) { return Math.log10(1 + v); } : function (v) { return v; };
  var ok = vals.filter(function (v) { return v !== null && !isNaN(v) && (mode !== "log" || v > 0); });
  var lo = dom ? dom[0] : (ok.length ? minOf(ok) : 0), hi = dom ? dom[1] : (ok.length ? maxOf(ok) : 1);
  if (mode === "log1p" && !dom && lo < 1) lo = 0;
  if (mode === "lin" && !dom && lo > 0 && lo < hi / 3) lo = 0;
  if (hi === lo) { if (mode === "log") { lo /= 10; hi *= 10; } else hi = lo + 1; }
  var a = T(lo), b = T(hi);
  var f = function (v) {
    if (mode === "log") v = Math.max(v, lo);
    return r0 + (T(v) - a) / (b - a) * (r1 - r0);
  };
  var ticks;
  if (mode === "lin") ticks = niceTicks(lo, hi, 5);
  else {
    var e0 = Math.ceil(Math.log10(mode === "log" ? lo : 1) - 1e-9), e1 = Math.floor(Math.log10(Math.max(hi, 1)) + 1e-9);
    if (mode === "log") e1 = Math.floor(Math.log10(hi) + 1e-9);
    var every = Math.max(1, Math.ceil((e1 - e0 + 1) / 7));
    ticks = [];
    for (var e = e0 - 1; e <= e1; e += every) {
      ticks.push(Math.pow(10, e));
      // less than three powers of ten: also 2 and 5 times each
      if (e1 - e0 < 2) ticks.push(2 * Math.pow(10, e), 5 * Math.pow(10, e));
    }
    if (mode === "log1p") ticks.unshift(0);
  }
  ticks = ticks.filter(function (v) { return v >= lo - 1e-12 && v <= hi * (1 + 1e-9) && (mode !== "log1p" || v === 0 || v >= 1); })
               .map(function (v) { return +v.toPrecision(6); }).sort(function (a, b) { return a - b; });
  f.ticks = ticks; f.lo = lo; f.hi = hi; f.mode = mode;
  return f;
}
function xAxis(s, x, y0, top, opt) {
  var g = sv("g", { class: "axis" }, s);
  x.ticks.forEach(function (t) {
    var px = x(t);
    sv("line", { x1: px, x2: px, y1: top, y2: y0 }, g);
    txt(g, px, y0 + 14, opt && opt.fmt ? opt.fmt(t) : tickText(t, x.mode), { "text-anchor": "middle" });
  });
  if (opt && opt.label) txt(g, (x(x.lo) + x(x.hi)) / 2, y0 + 30, opt.label, { "text-anchor": "middle" });
}
function yAxis(s, y, x0, right, opt) {
  var g = sv("g", { class: "axis" }, s);
  y.ticks.forEach(function (t) {
    var py = y(t);
    sv("line", { x1: x0, x2: right, y1: py, y2: py }, g);
    txt(g, x0 - 6, py + 4, opt && opt.fmt ? opt.fmt(t) : tickText(t, y.mode), { "text-anchor": "end" });
  });
  if (opt && opt.label) {
    var mid = (y(y.lo) + y(y.hi)) / 2;
    txt(g, 11, mid, opt.label, { "text-anchor": "middle", transform: "rotate(-90 11 " + mid + ")" });
  }
}

// ---- the page's parts -----------------------------------------------------

var contents = document.getElementById("contents");
var sectionsBox = document.getElementById("sections");

function section(id, title, lede, draw) {
  var s = el("section", { class: "section", id: id });
  s.appendChild(el("h2", {}, title));
  if (lede) s.appendChild(el("p", { class: "lede" }, lede));
  var cards = el("div", { class: "cards" });
  s.appendChild(cards);
  sectionsBox.appendChild(s);
  contents.appendChild(el("a", { href: "#" + id }, title));
  try { draw(cards); } catch (err) {
    cards.appendChild(el("p", { class: "note" }, "This section could not be drawn: " + err.message));
    if (window.console) console.error(err);
  }
}
function card(parent, title, note, wide) {
  var c = el("div", { class: "card" + (wide ? " wide" : "") });
  c.appendChild(el("h3", {}, title));
  if (note) c.appendChild(el("p", { class: "note" }, note));
  parent.appendChild(c);
  return c;
}
function say(c, s) { c.appendChild(el("p", { class: "say" }, s)); }
function tiles(parent, list) {
  var box = el("div", { class: "tiles" });
  list.forEach(function (t) {
    if (!t) return;
    var d = el("div", { class: "tile" + (t.kind ? " " + t.kind : "") });
    d.appendChild(el("b", {}, t.value));
    d.appendChild(el("span", {}, t.label));
    if (t.tip) d.setAttribute("data-tip", t.tip);
    box.appendChild(d);
  });
  parent.appendChild(box);
  return box;
}
function legend(c, keys, dot) {
  var l = el("div", { class: "legend" });
  keys.forEach(function (k) {
    var s = el("span", {});
    var i = el("i", { class: dot ? "dot" : "" });
    i.style.background = k.color;
    s.appendChild(i);
    s.appendChild(document.createTextNode(k.label));
    l.appendChild(s);
  });
  c.appendChild(l);
}
function tableView(c, head, rows) {
  var d = el("details", { class: "table-view" });
  d.appendChild(el("summary", {}, "Show as a table"));
  var box = el("div", { class: "scroll" }), t = el("table", {}), tr = el("tr", {});
  head.forEach(function (h) { tr.appendChild(el("th", {}, h)); });
  t.appendChild(tr);
  rows.forEach(function (r) {
    var tr = el("tr", {});
    r.forEach(function (v, i) { tr.appendChild(el("td", i ? { class: "n" } : {}, typeof v === "number" ? fmt(v) : v)); });
    t.appendChild(tr);
  });
  box.appendChild(t);
  d.appendChild(box);
  c.appendChild(d);
}

// ---- charts ----------------------------------------------------------------

// horizontal bars: items {label, value, tip, color}; o {total, fmt, labelW, clip}
function hbars(c, items, o) {
  o = o || {};
  if (!items.length) { c.appendChild(el("p", { class: "note" }, "Nothing to count yet.")); return; }
  fit(c);
  var lw = Math.min(o.labelW || 210, Math.round(W * 0.48)), rh = 22, vw = o.total ? 100 : 60;
  var longest = maxOf(items.map(function (i) { return String(i.label).length; }));
  // in a narrow card, labels that would be cut short go above their bars
  var above = longest * 6.2 > lw - 8 && W < 560;
  if (above) { lw = 0; rh = 36; }
  var h = items.length * rh + 4;
  var s = svgOf(h, o.aria), max = o.max || Math.max(1, maxOf(items.map(function (i) { return i.value; })));
  items.forEach(function (it, k) {
    var y = k * rh + 2, g = sv("g", {}, s), by = above ? y + 18 : y + 4, ty = above ? y + 29 : y + 15;
    if (above) txt(g, 0, y + 12, clip(it.label, Math.floor(W / 6.2)), { "font-size": 12 });
    else txt(g, lw - 8, y + 15, clip(it.label, Math.min(o.clip || 34, Math.floor(lw / 6.3))), { "text-anchor": "end", "font-size": 12 });
    var bw = it.value > 0 ? Math.max(2, (W - lw - vw) * it.value / max) : 0;
    sv("rect", { x: lw, y: by, width: bw, height: 13, rx: 3, fill: it.color || o.color || C.greenLight }, g);
    txt(g, lw + bw + 6, ty, (o.fmt || fmt)(it.value) + (o.total ? " (" + pc(it.value, o.total) + ")" : ""),
        { "font-size": 11.5, class: "muted" });
    sv("rect", { x: 0, y: y, width: W, height: rh, class: "hit",
                 "data-tip": it.tip || "<b>" + esc(it.label) + "</b><br>" + (o.fmt || fmt)(it.value) +
                   (o.total ? " of " + fmt(o.total) + " (" + pc(it.value, o.total) + ")" : "") }, g);
  });
  c.appendChild(s);
  if (o.table !== false) tableView(c, [o.what || "", o.unit || "Number"], items.map(function (i) { return [i.label, i.value]; }));
}

// vertical bars: items {label, value, tip}; o {height, color, every, ref, refLabel, ylabel}
function columns(c, items, o) {
  o = o || {};
  if (!items.length) { c.appendChild(el("p", { class: "note" }, "Nothing to count yet.")); return; }
  fit(c);
  var h = o.height || 180, l = 44, r = o.hlineLabel ? 70 : 8, t = 12, b = o.xlabel ? 42 : 26;
  var s = svgOf(h, o.aria), max = Math.max(1, maxOf(items.map(function (i) { return i.value; })));
  var y = makeScale([0, max], "lin", h - b, t, [0, max * 1.05]);
  yAxis(s, y, l, W - r, { label: o.ylabel, fmt: function (v) { return v % 1 ? "" : tickText(v); } });
  var bw = (W - l - r) / items.length, gap = Math.min(2, bw * 0.2);
  // a label at least every 34 units, so the labels do not touch
  var every = Math.max(o.every || 1, Math.ceil(34 / bw));
  if (!o.every) every = Math.max(every, Math.ceil(items.length / 12));
  items.forEach(function (it, k) {
    var x = l + k * bw, py = y(it.value), g = sv("g", {}, s);
    if (it.value > 0) sv("rect", { x: x + gap / 2, y: py, width: Math.max(1, bw - gap), height: Math.max(1, h - b - py),
                                   rx: Math.min(3, bw / 4), fill: it.color || o.color || C.greenLight }, g);
    if (k % every === 0) txt(g, x + bw / 2, h - b + 14, it.label, { "text-anchor": "middle", "font-size": 11, class: "muted" });
    sv("rect", { x: x, y: t, width: bw, height: h - b - t, class: "hit",
                 "data-tip": it.tip || "<b>" + esc(it.label) + "</b><br>" + fmt(it.value) }, g);
  });
  if (o.ref !== undefined) {
    var rx = l + o.ref * bw;
    sv("line", { x1: rx, x2: rx, y1: t - 4, y2: h - b, class: "ref" }, s);
    if (o.refLabel) txt(s, rx + 4, t + 6, o.refLabel, { "font-size": 11 });
  }
  if (o.hline !== undefined) {
    var hy = y(o.hline);
    sv("line", { x1: l, x2: W - r, y1: hy, y2: hy, class: "ref" }, s);
    if (o.hlineLabel) txt(s, W - r + 4, hy + 4, o.hlineLabel, { "font-size": 11 });
  }
  if (o.xlabel) txt(s, (l + W - r) / 2, h - 6, o.xlabel, { "text-anchor": "middle", "font-size": 11, class: "muted" });
  c.appendChild(s);
  if (o.table !== false) tableView(c, [o.what || "", o.unit || "Number"], items.map(function (i) { return [i.label, i.value]; }));
}

// a histogram of numbers: bins from lo to hi of width step (the last bin also
// holds the values above hi)
function histogram(c, vals, lo, hi, step, o) {
  o = o || {};
  var n = Math.round((hi - lo) / step), bins = [];
  for (var i = 0; i < n; i++) bins.push(0);
  vals.forEach(function (v) {
    if (v === null || isNaN(v) || v < lo) return;
    bins[Math.min(n - 1, Math.floor((v - lo) / step + 1e-9))]++;
  });
  var lab = o.label || function (a) { return tickText(a); };
  columns(c, bins.map(function (v, k) {
    var a = +(lo + k * step).toFixed(6), b = +(lo + (k + 1) * step).toFixed(6);
    var name = o.binName ? o.binName(a, b, k === n - 1) : (k === n - 1 && o.open ? lab(a) + " or more" : lab(a) + " to " + lab(b));
    return { label: lab(a), value: v, tip: "<b>" + esc(name) + "</b><br>" + fmt(v) + " " + (o.unit || "") + (o.total ? " (" + pc(v, o.total) + ")" : "") };
  }), Object.assign({ table: false }, o));
}

// a line through time: series [{name, color, pts: [[ms, y]]}]; a line follows the pointer
function timeLine(c, series, o) {
  o = o || {};
  fit(c);
  var h = o.height || 200, l = 48, r = 12, t = 12, b = 26, w = W;
  var xs = [], ys = [0];
  series.forEach(function (sr) { sr.pts.forEach(function (p) { xs.push(p[0]); ys.push(p[1]); }); });
  if (!xs.length) { c.appendChild(el("p", { class: "note" }, "Nothing to count yet.")); return; }
  var s = svgOf(h, o.aria);
  var x = makeScale(xs, "lin", l, W - r, [minOf(xs), Math.max(maxOf(xs), minOf(xs) + 864e5)]);
  var y = makeScale(ys, "lin", h - b, t, [0, maxOf(ys) * 1.05 || 1]);
  yAxis(s, y, l, W - r, { label: o.ylabel });
  var g = sv("g", { class: "axis" }, s);
  for (var k = 0; k <= 4; k++) {
    var tv = x.lo + (x.hi - x.lo) * k / 4;
    txt(g, x(tv), h - b + 15, timeTick(tv, x.hi - x.lo), { "text-anchor": k === 0 ? "start" : k === 4 ? "end" : "middle" });
  }
  series.forEach(function (sr) {
    var d = sr.pts.map(function (p, i) { return (i ? "L" : "M") + x(p[0]).toFixed(1) + " " + y(p[1]).toFixed(1); }).join("");
    if (o.area) sv("path", { d: d + "L" + x(sr.pts[sr.pts.length - 1][0]) + " " + y(0) + "L" + x(sr.pts[0][0]) + " " + y(0) + "Z",
                             fill: sr.color, "fill-opacity": 0.12 }, s);
    sv("path", { d: d, fill: "none", stroke: sr.color, "stroke-width": 2, "stroke-linejoin": "round" }, s);
  });
  var cross = sv("line", { y1: t, y2: h - b, stroke: C.text, "stroke-width": 1, visibility: "hidden" }, s);
  var dots = series.map(function (sr) { return sv("circle", { r: 4, fill: sr.color, stroke: C.surface, "stroke-width": 2, visibility: "hidden" }, s); });
  var hit = sv("rect", { x: l, y: t, width: W - l - r, height: h - b - t, class: "hit", "data-tip": "" }, s);
  function move(e) {
    var box = s.getBoundingClientRect(), px = (e.clientX - box.left) * w / box.width, at = x.lo + (px - l) / (w - l - r) * (x.hi - x.lo);
    var lines = [];
    series.forEach(function (sr, i) {
      var best = sr.pts[0];
      sr.pts.forEach(function (p) { if (Math.abs(p[0] - at) < Math.abs(best[0] - at)) best = p; });
      dots[i].setAttribute("cx", x(best[0])); dots[i].setAttribute("cy", y(best[1])); dots[i].setAttribute("visibility", "visible");
      cross.setAttribute("x1", x(best[0])); cross.setAttribute("x2", x(best[0]));
      lines.push((series.length > 1 ? esc(sr.name) + ": " : "") + "<b>" + fmt(best[1]) + "</b>" + (o.unit ? " " + o.unit : ""));
      if (i === 0) lines.unshift("<b>" + (o.when ? o.when(best[0]) : dayYear(new Date(best[0]))) + "</b>");
    });
    cross.setAttribute("visibility", "visible");
    hit.setAttribute("data-tip", lines.join("<br>"));
  }
  hit.addEventListener("pointermove", move);
  hit.addEventListener("pointerdown", move);
  hit.addEventListener("pointerleave", function () {
    cross.setAttribute("visibility", "hidden");
    dots.forEach(function (d) { d.setAttribute("visibility", "hidden"); });
  });
  c.appendChild(s);
}

// dots: pts {x, y, color, tip, href}; o {xmode, ymode, xdom, ydom, xlabel, ylabel,
// diag, line ([[x, y]]), xtime, height}
function scatter(c, pts, o) {
  o = o || {};
  fit(c);
  var h = o.height || 300, l = 52, r = 12, t = 10, b = 40;
  var s = svgOf(h, o.aria);
  var x = makeScale(pts.map(function (p) { return p.x; }), o.xmode || "lin", l, W - r, o.xdom);
  var y = makeScale(pts.map(function (p) { return p.y; }), o.ymode || "lin", h - b, t, o.ydom);
  if (o.xtime) {
    var g = sv("g", { class: "axis" }, s);
    for (var k = 0; k <= 4; k++) {
      var tv = x.lo + (x.hi - x.lo) * k / 4;
      sv("line", { x1: x(tv), x2: x(tv), y1: t, y2: h - b }, g);
      txt(g, x(tv), h - b + 14, timeTick(tv, x.hi - x.lo), { "text-anchor": k === 0 ? "start" : k === 4 ? "end" : "middle" });
    }
    if (o.xlabel) txt(g, (l + W - r) / 2, h - b + 30, o.xlabel, { "text-anchor": "middle" });
  } else xAxis(s, x, h - b, t, { label: o.xlabel, fmt: o.xfmt });
  yAxis(s, y, l, W - r, { label: o.ylabel, fmt: o.yfmt });
  if (o.diag) {
    var lo = Math.max(x.lo, y.lo), hi = Math.min(x.hi, y.hi);
    sv("line", { x1: x(lo), y1: y(lo), x2: x(hi), y2: y(hi), class: "ref" }, s);
  }
  if (o.hline !== undefined) sv("line", { x1: l, x2: W - r, y1: y(o.hline), y2: y(o.hline), class: "ref" }, s);
  if (o.vline !== undefined) sv("line", { x1: x(o.vline), x2: x(o.vline), y1: t, y2: h - b, class: "ref" }, s);
  var inside = function (p) { return p.x !== null && p.y !== null && !isNaN(p.x) && !isNaN(p.y); };
  // the coloured dots last, so they lie on top of the grey ones
  pts.filter(inside).sort(function (a, b) { return (a.z || 0) - (b.z || 0); }).forEach(function (p) {
    var parent = p.href ? sv("a", { href: p.href }, s) : s;
    // a dot outside a fixed range is drawn at its edge
    var px = o.xdom ? Math.min(Math.max(p.x, o.xdom[0]), o.xdom[1]) : p.x, py = o.ydom ? Math.min(Math.max(p.y, o.ydom[0]), o.ydom[1]) : p.y;
    sv("circle", { cx: x(px).toFixed(1), cy: y(py).toFixed(1), r: p.r || 4.5, fill: p.color || C.s1,
                   "fill-opacity": p.opacity || 0.8, stroke: C.surface, "stroke-width": 1, "data-tip": p.tip }, parent);
  });
  if (o.line && o.line.length > 1) {
    sv("path", { d: o.line.map(function (p, i) { return (i ? "L" : "M") + x(p[0]).toFixed(1) + " " + y(p[1]).toFixed(1); }).join(""),
                 fill: "none", stroke: o.lineColor || C.text, "stroke-width": 2, "pointer-events": "none" }, s);
  }
  c.appendChild(s);
  return s;
}

// one row of dots per value, spread up and down so they do not hide each
// other, with the median marked; vals {v, tip, href}; o {mode, label, fmt}
function strip(c, vals, o) {
  o = o || {};
  vals = vals.filter(function (d) { return d.v !== null && d.v !== undefined && !isNaN(d.v); });
  if (!vals.length) { c.appendChild(el("p", { class: "note" }, "Nothing to count yet.")); return; }
  fit(c);
  var h = o.height || 130, l = 16, r = 16, t = 22, b = 34;
  var s = svgOf(h, o.aria);
  var x = makeScale(vals.map(function (d) { return d.v; }), o.mode || "lin", l, W - r, o.dom);
  xAxis(s, x, h - b, t, { label: o.label, fmt: o.fmt });
  var band = h - b - t - 12;
  vals.forEach(function (d, k) {
    var j = ((k * 0.6180339887) % 1) - 0.5;
    var parent = d.href ? sv("a", { href: d.href }, s) : s;
    sv("circle", { cx: x(d.v).toFixed(1), cy: (t + 6 + band / 2 + j * band).toFixed(1), r: 4, fill: d.color || o.color || C.s1,
                   "fill-opacity": 0.7, stroke: C.surface, "stroke-width": 1, "data-tip": d.tip }, parent);
  });
  var m = median(vals.map(function (d) { return d.v; }));
  sv("line", { x1: x(m), x2: x(m), y1: t - 4, y2: h - b, stroke: C.red, "stroke-width": 2 }, s);
  txt(s, x(m) + (x(m) > W - 120 ? -4 : 4), t - 8, "median " + (o.vfmt || fmt)(m), { "font-size": 11, fill: C.red, "text-anchor": x(m) > W - 120 ? "end" : "start" });
  c.appendChild(s);
}

// bars split into parts that add up to 100%: rows {label, counts {key: n}};
// keys [{key, label, color}]
function stack100(c, rows, keys, o) {
  o = o || {};
  legend(c, keys);
  fit(c);
  var lw = Math.min(o.labelW || 210, Math.round(W * 0.45)), rh = o.rowH || 22, h = rows.length * rh + 4, s = svgOf(h, o.aria);
  rows.forEach(function (row, k) {
    var y = k * rh + 2, total = sum(keys.map(function (q) { return row.counts[q.key] || 0; })), x = lw;
    txt(s, lw - 8, y + 15, clip(row.label, Math.min(o.clip || 34, Math.floor(lw / 6.3))), { "text-anchor": "end", "font-size": 12 });
    keys.forEach(function (q) {
      var n = row.counts[q.key] || 0;
      if (!n) return;
      var w = (W - lw - 4) * n / total;
      sv("rect", { x: x, y: y + 3, width: Math.max(0.5, w - 2), height: rh - 7, rx: 2, fill: q.color,
                   "data-tip": "<b>" + esc(row.label) + "</b><br>" + esc(q.label) + ": " + fmt(n) + " of " + fmt(total) + " (" + pc(n, total) + ")" }, s);
      x += w;
    });
  });
  c.appendChild(s);
  tableView(c, [""].concat(keys.map(function (q) { return q.label; })),
            rows.map(function (row) { return [row.label].concat(keys.map(function (q) { return row.counts[q.key] || 0; })); }));
}

// a grid of cells: cell(row, col) gives {fill, tip, href}
function grid(c, nRows, nCols, cell, o) {
  fit(c);
  var lw = Math.min(o.labelW || 0, Math.round(W * 0.45)), top = o.top || 0, cw = (W - lw) / nCols, ch = o.cellH || cw;
  var h = top + nRows * ch + (o.bottom || 0) + 2, s = svgOf(h, o.aria), gap = o.gap === undefined ? (cw > 6 ? 1 : 0) : o.gap;
  for (var i = 0; i < nRows; i++) {
    if (o.rowLabel) txt(s, lw - 6, top + i * ch + ch / 2 + 4, clip(o.rowLabel(i), Math.floor(lw / 5.6)), { "text-anchor": "end", "font-size": o.font || 11.5 });
    for (var j = 0; j < nCols; j++) {
      var q = cell(i, j);
      if (!q) continue;
      var parent = q.href ? sv("a", { href: q.href }, s) : s;
      sv("rect", { x: (lw + j * cw).toFixed(2), y: (top + i * ch).toFixed(2), width: Math.max(0.6, cw - gap).toFixed(2),
                   height: Math.max(0.6, ch - gap).toFixed(2), rx: cw > 8 ? 2 : 0, fill: q.fill, "data-tip": q.tip }, parent);
      if (q.label) txt(s, lw + j * cw + cw / 2, top + i * ch + ch / 2 + 4, q.label,
                       { "text-anchor": "middle", "font-size": 10.5, fill: q.dark ? "#fff" : C.text, "pointer-events": "none" });
    }
  }
  if (o.colLabel) for (var k = 0; k < nCols; k++) {
    var lab = o.colLabel(k);
    if (lab) txt(s, lw + k * cw + cw / 2, top - 6, lab, { "text-anchor": "middle", "font-size": 11, class: "muted" });
  }
  if (o.bottomLabel) for (var m = 0; m < nCols; m++) {
    var bl = o.bottomLabel(m);
    if (bl) txt(s, lw + m * cw + cw / 2, top + nRows * ch + 14, bl, { "text-anchor": "middle", "font-size": 11, class: "muted" });
  }
  c.appendChild(s);
  s.geometry = { lw: lw, top: top, cw: cw, ch: ch, w: W };
  return s;
}

// two dots per row joined by a line: rows {label, a, b, tipA, tipB}
function dumbbell(c, rows, keys, o) {
  o = o || {};
  legend(c, keys, true);
  fit(c);
  var lw = Math.min(o.labelW || 210, Math.round(W * 0.45)), rh = 24, h = rows.length * rh + 36, s = svgOf(h, o.aria);
  var vals = []; rows.forEach(function (r) { vals.push(r.a, r.b); });
  var x = makeScale(vals.concat([0]), "lin", lw, W - 16, o.dom);
  xAxis(s, x, h - 32, 0, { label: o.xlabel });
  rows.forEach(function (r, k) {
    var y = k * rh + 12;
    txt(s, lw - 8, y + 4, clip(r.label, Math.floor(lw / 6.3)), { "text-anchor": "end", "font-size": 12 });
    sv("line", { x1: x(r.a), x2: x(r.b), y1: y, y2: y, stroke: C.grey, "stroke-width": 2 }, s);
    sv("circle", { cx: x(r.a), cy: y, r: 5, fill: keys[0].color, stroke: C.surface, "stroke-width": 1.5, "data-tip": r.tipA }, s);
    sv("circle", { cx: x(r.b), cy: y, r: 5, fill: keys[1].color, stroke: C.surface, "stroke-width": 1.5, "data-tip": r.tipB }, s);
  });
  c.appendChild(s);
}

// words sized by how often they occur
function words(c, list, o) {
  o = o || {};
  if (!list.length) { c.appendChild(el("p", { class: "note" }, "Nothing to count yet.")); return; }
  var box = el("div", { class: "words" }), max = list[0][1], min = list[list.length - 1][1];
  list.forEach(function (w) {
    var t = max === min ? 0.5 : (w[1] - min) / (max - min);
    var sp = el("span", { "data-tip": "<b>" + esc(w[0]) + "</b><br>" + fmt(w[1]) + " " + (o.unit || "") }, w[0]);
    sp.style.fontSize = (0.8 + 1.5 * Math.sqrt(t)).toFixed(2) + "rem";
    sp.style.opacity = (0.55 + 0.45 * t).toFixed(2);
    box.appendChild(sp);
  });
  c.appendChild(box);
}

// ---- the sections ----------------------------------------------------------

var SHORT = { ethics_check: "Ethics", power: "Power", prereg_check: "Preregistration", marginal: "Marginal",
              stat_check: "StatCheck", stat_p_exact: "Exact p", stat_p_nonsig: "Non-significant p",
              stat_effect_size: "Effect sizes", codebook_check: "Codebook", repo_check: "Repository",
              code_check: "Code", data_check: "Data", reproducibility_check: "Reproducibility",
              ref_pubpeer: "PubPeer", ref_retraction: "RetractionWatch", ref_replication: "Replication" };
function short(k) { return SHORT[MODS[k].id] || MODS[k].title; }
function L(p, k) { return p.L.charAt(k); }
function flagged(ch) { return ch === "r" || ch === "y"; }
function modTitle(k) { return MODS[k].title; }
function total(key) { return sum(P.map(function (p) { return p[key]; })); }
function share(f) { return pc(count(P, f), P.length); }
function vals(key, f) {
  return P.filter(f || function () { return true; }).map(function (p) {
    return { v: p[key], tip: paperTip(p, fmt(p[key])), href: link(p) };
  });
}
function list(pairs, name, color) {
  return pairs.map(function (q) { return { label: name ? name(q[0]) : q[0], value: q[1], color: color }; });
}

function drawNumbers(cards) {
  var box = el("div", { class: "card wide" });
  cards.appendChild(box);
  var reds = sum(P.map(function (p) { return p.reds; })), yellows = sum(P.map(function (p) { return p.yellows; }));
  tiles(box, [
    { value: fmt(P.length), label: "preprints checked" + (D.preprints_on_psyarxiv ? ", of " + fmt(D.preprints_on_psyarxiv) + " on PsyArXiv" : "") },
    { value: fmt(P.length * MODS.length), label: "checks run (" + MODS.length + " on each preprint)" },
    { value: fmt(reds), label: "red lights: to fix", kind: "red" },
    { value: fmt(yellows), label: "yellow lights: to check", kind: "yellow" },
    { value: big(total("words")), label: "words read" },
    { value: fmt(total("paras")), label: "paragraphs" },
    { value: fmt(total("auth")), label: "authors listed" },
    { value: fmt(D.counts.countries.length), label: "countries in the affiliations" },
    { value: fmt(total("refs")), label: "references read" },
    { value: fmt(total("refdoi")), label: "references with a DOI, looked up in PubPeer, RetractionWatch and FLoRA" },
    { value: fmt(total("p")), label: "p values found" },
    { value: fmt(total("pimp")), label: "p values reported imprecisely", kind: "yellow" },
    { value: fmt(total("nonsig")), label: "non-significant p values" },
    { value: fmt(total("sc")), label: "t- and F-tests recomputed by StatCheck" },
    { value: fmt(total("scerr")), label: "tests whose p value does not match", kind: "yellow" },
    { value: fmt(total("scdec")), label: "of which the conclusion about significance changes", kind: "red" },
    { value: fmt(total("pow")), label: "power analyses" },
    { value: fmt(total("prereg")), label: "preregistrations read" },
    { value: fmt(total("repos")), label: "repositories" },
    { value: fmt(total("files")), label: "files in the repositories" },
    { value: bytes(total("bytes")), label: "in those files" },
    { value: fmt(total("code")), label: "code files" },
    { value: big(total("loc")), label: "lines of code read" },
    { value: fmt(total("scr")), label: "scripts run" },
    { value: fmt(total("ran")), label: "scripts that ran through" },
    { value: fmt(total("broke")), label: "scripts that did not run through", kind: "red" },
    { value: fmt(total("dfiles")), label: "data files" },
    { value: fmt(total("cols")), label: "data columns examined" },
    { value: fmt(total("dissues")), label: "possible problems in the data", kind: "yellow" },
    { value: fmt(total("pubpeer")), label: "cited works with comments on PubPeer" },
    { value: fmt(total("ppcom")), label: "PubPeer comments on them" },
    { value: fmt(total("repl")), label: "cited works that were replicated (FLoRA)" },
    { value: fmt(total("retract")), label: "cited works with a retraction notice or correction" },
    { value: fmt(total("figs")), label: "figures" },
    { value: fmt(total("eqs")), label: "equations and statistics in the text" },
    D.waiting ? { value: fmt(D.waiting), label: "preprints waiting to be checked" } : null
  ]);
}

function wallOrder(how) {
  var idx = P.map(function (p, i) { return i; });
  var rank = { r: 0, y: 1, i: 2, g: 3, f: 4, n: 5 };
  if (how === "date") idx.sort(function (a, b) { return P[a].cdate - P[b].cdate; });
  else if (how === "red") idx.sort(function (a, b) { return P[b].reds - P[a].reds || P[b].flags - P[a].flags; });
  else if (how === "flags") idx.sort(function (a, b) { return P[b].flags - P[a].flags || P[b].reds - P[a].reds; });
  else idx.sort(function (a, b) {
    for (var k = 0; k < MODS.length; k++) {
      var d = rank[L(P[a], k)] - rank[L(P[b], k)];
      if (d) return d;
    }
    return 0;
  });
  return idx;
}

function drawWall(cards) {
  var c = card(cards, "Every check on every preprint",
    "One column per preprint, one row per check, coloured by the check's traffic light. Point at a square to see the preprint and the check; click it to open the report.", true);
  legend(c, LIGHTS.filter(function (l) { return P.some(function (p) { return p.L.indexOf(l.key) >= 0; }); }));
  var bar = el("div", { class: "buttons" }), box = el("div", {});
  var orders = [["date", "In the order they were checked"], ["flags", "Most red and yellow first"], ["red", "Most red first"], ["pattern", "Grouped by pattern"]];
  function draw(how) {
    box.innerHTML = "";
    Array.prototype.forEach.call(bar.children, function (b) { b.setAttribute("aria-pressed", b.value === how ? "true" : "false"); });
    var idx = wallOrder(how);
    grid(box, MODS.length, idx.length, function (i, j) {
      var p = P[idx[j]], l = LIGHT[L(p, i)] || LIGHT.n;
      return { fill: l.color, href: link(p), tip: paperTip(p, esc(modTitle(i)) + ": <b>" + esc(l.label) + "</b>") };
    }, { labelW: 200, cellH: 15, rowLabel: function (i) { return clip(modTitle(i), 30); }, font: 11 });
  }
  orders.forEach(function (o) {
    var b = el("button", { type: "button", value: o[0] }, o[1]);
    b.addEventListener("click", function () { draw(o[0]); });
    bar.appendChild(b);
  });
  c.appendChild(bar);
  c.appendChild(box);
  draw("date");

  var c2 = card(cards, "Each check's lights", "How often each check gave each light, over all preprints; the checks with the most red first.", true);
  var rows = MODS.map(function (m, k) {
    return { label: m.title, counts: tally(P, function (p) { return L(p, k); }) };
  }).sort(function (a, b) { return (b.counts.r || 0) - (a.counts.r || 0) || (b.counts.y || 0) - (a.counts.y || 0); });
  stack100(c2, rows, LIGHTS.filter(function (l) { return rows.some(function (r) { return r.counts[l.key]; }); }));

  var c3 = card(cards, "Red and yellow lights per preprint", "How many of the " + MODS.length + " checks gave a preprint a red or a yellow light.");
  var maxF = Math.max(1, maxOf(P.map(function (p) { return p.flags; })));
  var byF = [];
  for (var f = 0; f <= maxF; f++) byF.push({ label: String(f), value: count(P, function (p) { return p.flags === f; }) });
  byF.forEach(function (b) { b.tip = "<b>" + b.label + " checks red or yellow</b><br>" + fmt(b.value) + " preprints (" + pc(b.value, P.length) + ")"; });
  columns(c3, byF, { xlabel: "checks with a red or yellow light", ylabel: "preprints", every: 1, what: "Checks red or yellow", unit: "Preprints" });
  var clean = count(P, function (p) { return p.flags === 0; });
  say(c3, "The median preprint has " + fmt(median(P.map(function (p) { return p.flags; }))) + " checks red or yellow; " +
      fmt(clean) + " preprints (" + pc(clean, P.length) + ") have none.");

  var c4 = card(cards, "Red lights per preprint", "Only the checks that say: to fix.");
  var maxR = Math.max(1, maxOf(P.map(function (p) { return p.reds; }))), byR = [];
  for (var q = 0; q <= maxR; q++) byR.push({ label: String(q), value: count(P, function (p) { return p.reds === q; }), color: C.red });
  byR.forEach(function (b) { b.tip = "<b>" + b.label + " red lights</b><br>" + fmt(b.value) + " preprints (" + pc(b.value, P.length) + ")"; });
  columns(c4, byR, { xlabel: "checks with a red light", ylabel: "preprints", every: 1, what: "Red lights", unit: "Preprints" });

  var c5 = card(cards, "How many checks had something to check", "A check that finds nothing to look at (no code, no power analysis) gives no light. This counts the checks that did give one.");
  var byA = [];
  for (var a = 0; a <= MODS.length; a++) byA.push({ label: String(a), value: count(P, function (p) { return p.applied === a; }) });
  byA.forEach(function (b) { b.tip = "<b>" + b.label + " checks</b><br>" + fmt(b.value) + " preprints"; });
  columns(c5, byA, { xlabel: "checks that had something to check", ylabel: "preprints", every: 2, what: "Checks", unit: "Preprints" });
}

function drawRelations(cards) {
  var n = MODS.length, F = MODS.map(function (m, k) { return P.map(function (p) { return flagged(L(p, k)) ? 1 : 0; }); });
  var A = MODS.map(function (m, k) { return P.map(function (p) { return L(p, k) !== "n" && L(p, k) !== "f"; }); });
  var keep = [];
  for (var k = 0; k < n; k++) if (sum(F[k]) >= 3 && sum(F[k]) < P.length) keep.push(k);
  var stats = {};
  keep = keep.filter(function (a) { return keep.some(function (b) { return a !== b && pair(a, b).r !== null; }); });

  var c = card(cards, "Which problems come together",
    "For each pair of checks, the correlation (φ) between being flagged red or yellow by the one and by the other, counted over the preprints where both checks had something to check. Orange: flagged together more often than chance; blue: less often. Empty: fewer than 10 such preprints.", true);
  function pair(a, b) {
    var key = a + "," + b;
    if (stats[key]) return stats[key];
    var x = [], y = [], both = 0;
    for (var i = 0; i < P.length; i++) if (A[a][i] && A[b][i]) { x.push(F[a][i]); y.push(F[b][i]); if (F[a][i] && F[b][i]) both++; }
    return (stats[key] = { r: x.length >= 10 ? pearson(x, y) : null, n: x.length, fa: sum(x), fb: sum(y), both: both });
  }
  legend(c, [{ label: "together less often", color: C.s1 }, { label: "no relation", color: C.mid }, { label: "together more often", color: C.s2 }]);
  grid(c, keep.length, keep.length, function (i, j) {
    var a = keep[i], b = keep[j];
    if (a === b) return { fill: C.surface, label: String(i + 1), tip: "<b>" + esc(modTitle(a)) + "</b><br>flagged in " + fmt(sum(F[a])) + " preprints" };
    var s = pair(a, b);
    return { fill: s.r === null ? C.surface : diverging(s.r), label: s.r === null ? "" : s.r.toFixed(2).replace(/^(-?)0/, "$1"), dark: s.r !== null && Math.abs(s.r) > 0.6,
             tip: "<b>" + esc(modTitle(a)) + "</b> and <b>" + esc(modTitle(b)) + "</b><br>" +
                  (s.r === null ? "too few preprints where both had something to check (" + s.n + ")" :
                   "φ = " + s.r.toFixed(2) + "<br>of " + fmt(s.n) + " preprints where both applied: " + fmt(s.fa) + " flagged by the first, " +
                   fmt(s.fb) + " by the second, " + fmt(s.both) + " by both") };
  }, { labelW: 230, top: 20, cellH: 28, rowLabel: function (i) { return (i + 1) + "  " + clip(modTitle(keep[i]), 28); },
       colLabel: function (j) { return String(j + 1); }, gap: 2 });

  var c2 = card(cards, "The pairs flagged together most often", "Preprints flagged red or yellow by both checks.");
  var pairs = [];
  for (var i = 0; i < keep.length; i++) for (var j = i + 1; j < keep.length; j++) {
    var s = pair(keep[i], keep[j]);
    if (s.both) pairs.push({ label: short(keep[i]) + " + " + short(keep[j]), value: s.both,
                             tip: "<b>" + esc(modTitle(keep[i])) + " + " + esc(modTitle(keep[j])) + "</b><br>" + fmt(s.both) + " preprints flagged by both" });
  }
  pairs.sort(function (a, b) { return b.value - a.value; });
  hbars(c2, pairs.slice(0, 14), { labelW: 250, clip: 40, color: C.yellow, what: "Pair", unit: "Preprints" });

  var c3 = card(cards, "One problem, more problems?",
    "For each check: the average number of OTHER checks flagged red or yellow, in preprints this check flagged and in those it did not.");
  var rows = keep.map(function (k) {
    var yes = [], no = [];
    P.forEach(function (p, i) { var others = p.flags - F[k][i]; (F[k][i] ? yes : no).push(others); });
    return { label: modTitle(k), a: mean(no), b: mean(yes),
             tipA: "<b>" + esc(modTitle(k)) + "</b>: not flagged<br>" + fmt(no.length) + " preprints, on average " + mean(no).toFixed(2) + " other checks flagged",
             tipB: "<b>" + esc(modTitle(k)) + "</b>: flagged<br>" + fmt(yes.length) + " preprints, on average " + mean(yes).toFixed(2) + " other checks flagged" };
  }).sort(function (a, b) { return (b.b - b.a) - (a.b - a.a); });
  dumbbell(c3, rows, [{ label: "not flagged by this check", color: C.grey }, { label: "flagged by this check", color: C.red }], { xlabel: "other checks flagged, on average" });

  var c4 = card(cards, "Long papers, more flags?", "Each dot is a preprint: the words in its text, and how many checks flagged it. The line follows the average.");
  var pts = P.map(function (p) { return { x: p.words, y: p.flags + (((p.i * 0.618) % 1) - 0.5) * 0.4, tip: paperTip(p, fmt(p.words) + " words, " + p.flags + " checks red or yellow"), href: link(p), color: C.s1 }; });
  scatter(c4, pts, { xmode: "log", xlabel: "words (log scale)", ylabel: "checks red or yellow", line: trend(P, "words", "flags", true), height: 260 });
  var sp = spearman(P.map(function (p) { return p.words; }), P.map(function (p) { return p.flags; }));
  say(c4, "Rank correlation (Spearman): " + (sp.r === null ? "–" : sp.r.toFixed(2)) + ", over " + sp.n + " preprints.");
}

// the average of y over the preprints sorted by x, in about 8 groups
function trend(rows, xk, yk, logx) {
  var s = rows.filter(function (p) { return p[xk] !== null && p[yk] !== null && (!logx || p[xk] > 0); })
              .slice().sort(function (a, b) { return a[xk] - b[xk]; });
  if (s.length < 10) return null;
  var g = Math.max(5, Math.round(s.length / 8)), out = [];
  for (var i = 0; i < s.length; i += g) {
    var part = s.slice(i, i + g);
    if (part.length < 3) break;
    out.push([logx ? Math.pow(10, mean(part.map(function (p) { return Math.log10(p[xk]); }))) : mean(part.map(function (p) { return p[xk]; })),
              mean(part.map(function (p) { return p[yk]; }))]);
  }
  return out;
}

function drawTime(cards) {
  var byCheck = P.filter(function (p) { return p.cdate; }).slice().sort(function (a, b) { return a.cdate - b.cdate; });
  var c = card(cards, "Reports over time", "The number of preprints checked, counted up as they were checked.", true);
  timeLine(c, [{ name: "preprints checked", color: C.green, pts: byCheck.map(function (p, i) { return [+p.cdate, i + 1]; }) }],
           { area: true, ylabel: "preprints checked", unit: "preprints checked", when: function (t) { var d = new Date(t); return dayYear(d) + ", " + String(d.getUTCHours()).padStart(2, "0") + ":" + String(d.getUTCMinutes()).padStart(2, "0") + " UTC"; } });

  var c2 = card(cards, "Checked per day", "Preprints checked on each day (UTC).");
  var perDay = tally(byCheck, function (p) { return p.chk.slice(0, 10); }), days = Object.keys(perDay).sort();
  columns(c2, days.map(function (d) { return { label: day(toDate(d)), value: perDay[d], tip: "<b>" + dayYear(toDate(d)) + "</b><br>" + perDay[d] + " preprints checked" }; }),
          { ylabel: "preprints", what: "Day", unit: "Preprints" });

  var c3 = card(cards, "When preprints are posted", "The day of the week and the hour (UTC) at which each preprint was published on PsyArXiv. Darker: more preprints.", true);
  var wd = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"], cnt = [];
  for (var i = 0; i < 7; i++) { cnt.push([]); for (var h = 0; h < 24; h++) cnt[i].push(0); }
  P.forEach(function (p) { if (p.date) cnt[(p.date.getUTCDay() + 6) % 7][p.date.getUTCHours()]++; });
  var mx = Math.max(1, maxOf([].concat.apply([], cnt)));
  grid(c3, 7, 24, function (i, j) {
    var v = cnt[i][j];
    return { fill: v ? sequential(0.15 + 0.85 * v / mx) : C.surface, tip: "<b>" + wd[i] + ", " + j + ":00–" + (j + 1) + ":00 UTC</b><br>" + v + " preprints" };
  }, { labelW: 90, cellH: 20, top: 2, bottom: 18, rowLabel: function (i) { return wd[i]; }, bottomLabel: function (j) { return j % 3 ? "" : j + ":00"; }, gap: 2 });

  var c4 = card(cards, "Flags by publication date", "Each dot is a preprint: when it was published, and how many checks flagged it. The line follows the average.");
  var pub = P.filter(function (p) { return p.date; });
  scatter(c4, pub.map(function (p) {
    return { x: +p.date, y: p.flags + (((p.i * 0.618) % 1) - 0.5) * 0.4, color: p.reds ? C.red : C.yellow, href: link(p),
             tip: paperTip(p, "published " + dayYear(p.date) + "<br>" + p.flags + " checks red or yellow, " + p.reds + " red") };
  }), { xtime: true, ylabel: "checks red or yellow", line: trend(pub.map(function (p) { return { x: +p.date, y: p.flags }; }), "x", "y"), height: 250 });
  legend(c4, [{ label: "at least one red light", color: C.red }, { label: "no red light", color: C.yellow }], true);

  var c5 = card(cards, "Metacheck's versions", "The version of Metacheck that checked each preprint. Metacheck changes almost every day; the newer versions check more.");
  var ver = tally(P, function (p) { return p.mc || "unknown"; });
  var vs = Object.keys(ver).sort(function (a, b) {
    var x = a.split(".").map(Number), y = b.split(".").map(Number);
    for (var i = 0; i < Math.max(x.length, y.length); i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) - (y[i] || 0);
    return 0;
  });
  hbars(c5, vs.map(function (v) {
    var ps = P.filter(function (p) { return (p.mc || "unknown") === v; });
    return { label: v, value: ver[v], tip: "<b>Metacheck " + esc(v) + "</b><br>" + ver[v] + " preprints<br>on average " +
             mean(ps.map(function (p) { return p.flags; })).toFixed(1) + " checks red or yellow" };
  }), { total: P.length, what: "Version", unit: "Preprints" });

  var c6 = card(cards, "Versions of the preprints", "Which version of the preprint Metacheck checked (the newest when it was checked).");
  var pv = tally(P, function (p) { return p.v; });
  columns(c6, Object.keys(pv).sort(function (a, b) { return a - b; }).map(function (v) {
    return { label: "v" + v, value: pv[v], tip: "<b>Version " + v + "</b><br>" + pv[v] + " preprints" };
  }), { every: 1, ylabel: "preprints", what: "Version", unit: "Preprints" });
}

function drawP(cards) {
  var ps = D.p.map(function (r) { return { p: r[0], comp: r[1], sec: r[2], imp: r[3], i: r[4], dig: r[5] }; });
  var exact = ps.filter(function (r) { return r.comp === "="; });

  var c = card(cards, "Exact p values between 0 and .10",
    "Every p value reported as p = …, in steps of .0025. The line marks .05. A pile just below the line is what selective reporting can leave behind; a few values cannot show it.", true);
  var low = exact.filter(function (r) { return r.p <= 0.1; });
  histogram(c, low.map(function (r) { return r.p; }), 0, 0.1, 0.0025, {
    ref: 20, refLabel: ".05", every: 4, unit: "p values", xlabel: "p value", ylabel: "p values",
    label: function (a) { return a ? String(+a.toFixed(4)).replace(/^0/, "") : "0"; },
    binName: function (a, b) { return "p from " + String(+a.toFixed(4)).replace(/^0/, "") + " to " + String(+b.toFixed(4)).replace(/^0/, ""); }
  });
  var below = count(exact, function (r) { return r.p > 0.04 && r.p < 0.05; }), at = count(exact, function (r) { return r.p === 0.05; }),
      above = count(exact, function (r) { return r.p > 0.05 && r.p <= 0.06; });
  tiles(c, [{ value: fmt(below), label: "between .04 and .05" }, { value: fmt(at), label: "exactly .05" }, { value: fmt(above), label: "above .05, up to .06" }]);

  var c2 = card(cards, "All exact p values", "From 0 to 1, in steps of .05.");
  histogram(c2, exact.map(function (r) { return r.p; }), 0, 1, 0.05, { every: 4, unit: "p values", xlabel: "p value", ylabel: "p values",
    label: function (a) { return a ? String(+a.toFixed(2)).replace(/^0/, "") : "0"; } });
  say(c2, fmt(count(exact, function (r) { return r.p < 0.05; })) + " of " + fmt(exact.length) + " exact p values (" +
      pc(count(exact, function (r) { return r.p < 0.05; }), exact.length) + ") are below .05.");

  var c3 = card(cards, "How p values are written", "The sign between p and the number.");
  var comps = tally(ps, function (r) { return r.comp; });
  hbars(c3, Object.keys(comps).sort(function (a, b) { return comps[b] - comps[a]; }).map(function (k) {
    return { label: "p " + k + " …", value: comps[k] };
  }), { total: ps.length, labelW: 120, what: "Sign", unit: "P values" });

  var c4 = card(cards, "The numbers after p <", "When a paper writes p < something: which something.");
  var th = tally(ps.filter(function (r) { return r.comp === "<" || r.comp === "≤"; }), function (r) { return String(r.p).replace(/^0/, ""); });
  hbars(c4, Object.keys(th).sort(function (a, b) { return th[b] - th[a]; }).slice(0, 10).map(function (k) {
    return { label: "p < " + k, value: th[k] };
  }), { labelW: 120, color: C.s1, what: "Threshold", unit: "P values" });

  var c5 = card(cards, "Decimals", "How many decimals each p value has, as the paper wrote it. The APA asks for two or three; and for p < .001 rather than p = .000.");
  var dg = tally(ps.filter(function (r) { return r.dig; }), function (r) { return Math.min(r.dig.length, 5); });
  columns(c5, [1, 2, 3, 4, 5].map(function (k) {
    return { label: k === 5 ? "5+" : String(k), value: dg[k] || 0, tip: "<b>" + (k === 5 ? "5 or more" : k) + " decimals</b><br>" + fmt(dg[k] || 0) + " p values" };
  }), { every: 1, xlabel: "decimals", ylabel: "p values", what: "Decimals", unit: "P values" });

  var c6 = card(cards, "The last digit", "The last digit of exact p values with three decimals (p = .xyz). If the last digit were random, each would be about one tenth, at the line.");
  var three = exact.filter(function (r) { return r.dig && r.dig.length === 3; });
  var ld = tally(three, function (r) { return r.dig.charAt(2); });
  columns(c6, "0123456789".split("").map(function (d) {
    return { label: d, value: ld[d] || 0, color: C.s1, tip: "<b>last digit " + d + "</b><br>" + fmt(ld[d] || 0) + " of " + fmt(three.length) + " (" + pc(ld[d] || 0, three.length) + ")" };
  }), { every: 1, hline: three.length / 10, hlineLabel: "one tenth", ylabel: "p values", what: "Last digit", unit: "P values" });

  var c7 = card(cards, "Where the p values are", "The part of the paper in which each p value was found.");
  var sec = tally(ps, function (r) { return r.sec; });
  hbars(c7, Object.keys(sec).sort(function (a, b) { return sec[b] - sec[a]; }).map(function (k) {
    var imp = count(ps, function (r) { return r.sec === k && r.imp; });
    return { label: SECTION_NAME[k] || k, value: sec[k], tip: "<b>" + esc(SECTION_NAME[k] || k) + "</b><br>" + fmt(sec[k]) + " p values, " + fmt(imp) + " of them imprecise" };
  }), { total: ps.length, labelW: 120, what: "Part", unit: "P values" });

  var c8 = card(cards, "P values per preprint", "Each dot is a preprint (log scale).");
  strip(c8, vals("p"), { mode: "log1p", label: "p values in the preprint" });
  say(c8, fmt(count(P, function (p) { return p.p === 0; })) + " preprints report no p value at all.");

  var c9 = card(cards, "Imprecise p values", "The share of a preprint's p values that are reported imprecisely (such as p < .05 where an exact value is possible), for preprints with at least 5 p values.");
  strip(c9, P.filter(function (p) { return p.p >= 5; }).map(function (p) {
    return { v: p.pimp / p.p, tip: paperTip(p, p.pimp + " of " + p.p + " imprecise"), href: link(p), color: C.yellow };
  }), { label: "share imprecise", fmt: function (v) { return Math.round(v * 100) + "%"; }, vfmt: function (v) { return Math.round(v * 100) + "%"; } });

  var c10 = card(cards, "Non-significant p values", "P values above .05, which the check asks to be interpreted with care (absence of evidence is not evidence of absence).");
  strip(c10, vals("nonsig"), { mode: "log1p", label: "non-significant p values in the preprint", color: C.s2 });
  say(c10, fmt(total("nonsig")) + " in total; " + share(function (p) { return p.nonsig > 0; }) + " of the preprints report at least one.");
}

function drawStatcheck(cards) {
  var sc = D.statcheck.map(function (r) { return { rep: r[0], comp: r[1], cmp: r[2], type: r[3], err: r[4], dec: r[5], df1: r[6], df2: r[7], i: r[8] }; });
  var c = card(cards, "Reported against recomputed",
    "Each dot is a t- or F-test. StatCheck recomputes the p value from the test statistic and degrees of freedom. On the line, the two agree; far from it, they do not. Point at a dot to see the test.", true);
  legend(c, [{ label: "consistent", color: C.grey }, { label: "inconsistent", color: C.yellow }, { label: "inconsistent, and the conclusion about significance changes", color: C.red }], true);
  scatter(c, sc.map(function (r) {
    var p = P[r.i];
    return { x: Math.max(r.comp, 1e-16), y: Math.max(r.rep, 1e-16), z: r.dec ? 2 : r.err ? 1 : 0,
             color: r.dec ? C.red : r.err ? C.yellow : C.grey, opacity: r.err ? 0.95 : 0.45, href: p ? link(p) : null,
             tip: (p ? paperTip(p) + "<br>" : "") + esc((r.type || "") + " test") + "<br>reported p " + esc(r.cmp) + " " + fmt(r.rep) +
                  "<br>recomputed p = " + (r.comp < 0.0001 ? r.comp.toExponential(1) : fmt(r.comp)) + (r.dec ? "<br><b>decision error</b>" : r.err ? "<br><b>inconsistent</b>" : "") };
  }), { xmode: "log", ymode: "log", diag: true, xdom: [1e-16, 1], ydom: [1e-6, 1], xlabel: "recomputed p (log scale; below 10⁻¹⁶ at the left edge)", ylabel: "reported p", height: 340 });
  tiles(c, [{ value: fmt(sc.length), label: "tests recomputed" },
            { value: fmt(count(sc, function (r) { return r.err; })), label: "inconsistent (" + pc(count(sc, function (r) { return r.err; }), sc.length) + ")", kind: "yellow" },
            { value: fmt(count(sc, function (r) { return r.dec; })), label: "decision errors (" + pc(count(sc, function (r) { return r.dec; }), sc.length) + ")", kind: "red" },
            { value: share(function (p) { return p.sc > 0; }), label: "of the preprints have a test StatCheck can read" },
            { value: pc(count(P, function (p) { return p.scerr > 0; }), count(P, function (p) { return p.sc > 0; })), label: "of those have at least one inconsistency" }]);

  var c2 = card(cards, "t-tests and F-tests", "How many of each, and how many of each were inconsistent.");
  var types = tally(sc, function (r) { return r.type || "other"; });
  stack100(c2, Object.keys(types).map(function (t) {
    return { label: t + "-tests (" + fmt(types[t]) + ")", counts: { ok: count(sc, function (r) { return (r.type || "other") === t && !r.err; }),
             err: count(sc, function (r) { return (r.type || "other") === t && r.err && !r.dec; }), dec: count(sc, function (r) { return (r.type || "other") === t && r.dec; }) } };
  }), [{ key: "ok", label: "consistent", color: C.grey }, { key: "err", label: "inconsistent", color: C.yellow }, { key: "dec", label: "decision error", color: C.red }], { labelW: 150 });

  var c3 = card(cards, "Degrees of freedom", "The (second) degrees of freedom of each test: a rough sign of the sample size (log scale).");
  strip(c3, sc.filter(function (r) { return r.df2 > 0; }).map(function (r) {
    var p = P[r.i];
    return { v: r.df2, tip: (p ? paperTip(p) + "<br>" : "") + "df = " + fmt(r.df2), color: r.err ? C.yellow : C.s1, href: p ? link(p) : null };
  }), { mode: "log", label: "degrees of freedom" });

  var c4 = card(cards, "Effect sizes with the tests", "Of the t- and F-tests in the text, how many come with an effect size.");
  var tests = total("es_t") + total("es_f"), none = total("es_no");
  tiles(c4, [{ value: fmt(tests), label: "t- and F-tests" }, { value: pc(tests - none, tests), label: "with an effect size" },
             { value: fmt(none), label: "without one", kind: "yellow" }]);
  hbars(c4, list(D.counts.es_symbols), { labelW: 80, color: C.s1, what: "Effect size", unit: "Times reported" });

  var c5 = card(cards, "Reported d against the d the test implies", "The size of Cohen's d as reported, and as computed from the t value and degrees of freedom (two equal groups), without the sign. Orange: more than 20% apart, worth a second look (or the design is not two equal groups).");
  scatter(c5, D.d_pairs.map(function (q) {
    var p = P[q[2]];
    var dr = Math.abs(q[0]), di = Math.abs(q[1]);
    return { x: di, y: dr, color: Math.abs(dr - di) > 0.2 * Math.max(di, 0.1) ? C.s2 : C.s1, href: p ? link(p) : null,
             tip: (p ? paperTip(p) + "<br>" : "") + "reported d = " + q[0] + "<br>implied d = " + q[1] };
  }), { diag: true, xdom: [0, 3], ydom: [0, 3], xlabel: "d implied by the test (above 3 at the edge)", ylabel: "d reported", height: 280 });
}

function drawPower(cards) {
  var pw = D.power.map(function (r) { return { power: r[0], alpha: r[1], metric: r[2], software: r[3], type: r[4], test: r[5], n: r[6], es: r[7], complete: r[8], i: r[9] }; });
  var c = card(cards, "Power analyses", "What the power analyses Metacheck found aim for.");
  tiles(c, [{ value: fmt(pw.length), label: "power analyses" }, { value: share(function (p) { return p.pow > 0; }), label: "of the preprints have one" },
            { value: pc(count(pw, function (r) { return r.complete; }), pw.length), label: "report everything needed to repeat them" }]);
  var targets = tally(pw.filter(function (r) { return r.power; }), function (r) { return Math.round(r.power * 100); });
  columns(c, Object.keys(targets).sort(function (a, b) { return a - b; }).map(function (k) {
    return { label: k + "%", value: targets[k], tip: "<b>power " + k + "%</b><br>" + targets[k] + " power analyses" };
  }), { every: 1, xlabel: "the power aimed for", ylabel: "analyses", what: "Power", unit: "Analyses" });

  var c2 = card(cards, "Kinds of power analysis", "");
  hbars(c2, list(ranked(tally(pw, function (r) { return r.type || "not stated"; })), function (k) {
    return { apriori: "a priori (to plan the sample)", sensitivity: "sensitivity (what the sample can detect)", unknown: "not clear" }[k] || k;
  }), { total: pw.length, what: "Kind", unit: "Analyses" });
  hbars(c2, list(ranked(tally(pw, function (r) { return r.software || "not stated"; }))), { total: pw.length, color: C.s1, what: "Software", unit: "Analyses" });

  var c3 = card(cards, "For which test, with which effect size", "");
  hbars(c3, list(ranked(tally(pw, function (r) { return r.test || "not stated"; }))), { total: pw.length, what: "Test", unit: "Analyses" });
  hbars(c3, list(ranked(tally(pw, function (r) { return r.metric || "not stated"; }))), { total: pw.length, color: C.s1, what: "Effect size", unit: "Analyses" });

  var c4 = card(cards, "The alpha level", "");
  hbars(c4, list(ranked(tally(pw, function (r) { return r.alpha === null ? "not stated" : String(r.alpha); }))), { total: pw.length, labelW: 120, what: "Alpha", unit: "Analyses" });

  var c5 = card(cards, "Planned sample sizes", "The sample size each power analysis gives (log scale).");
  strip(c5, pw.filter(function (r) { return r.n > 0; }).map(function (r) {
    var p = P[r.i];
    return { v: r.n, tip: (p ? paperTip(p) + "<br>" : "") + "N = " + fmt(r.n) + (r.power ? ", power " + Math.round(r.power * 100) + "%" : ""), href: p ? link(p) : null };
  }), { mode: "log", label: "sample size" });

  var c6 = card(cards, "The effect sizes they power for", "Cohen's d in power analyses that use it; the usual small, medium and large are .2, .5 and .8.");
  strip(c6, pw.filter(function (r) { return r.metric === "Cohen's d" && r.es > 0; }).map(function (r) {
    var p = P[r.i];
    return { v: r.es, tip: (p ? paperTip(p) + "<br>" : "") + "d = " + r.es, href: p ? link(p) : null, color: C.s2 };
  }), { label: "Cohen's d" });
}

function ranked(obj) {
  return Object.keys(obj).map(function (k) { return [k, obj[k]]; }).sort(function (a, b) { return b[1] - a[1]; });
}

function drawOpen(cards) {
  var c = card(cards, "From a paper to code that runs",
    "Each step counts the preprints that got that far. The last steps depend on the ones before: code can only be run when it is shared.", true);
  var steps = [
    ["preprints checked", function () { return true; }],
    ["link to a repository", function (p) { return p.repos > 0 || p.files > 0; }],
    ["share code", function (p) { return p.code > 0; }],
    ["have code Metacheck could run", function (p) { return p.scr > 0; }],
    ["all their scripts ran through", function (p) { return p.scr > 0 && p.broke === 0; }]
  ];
  hbars(c, steps.map(function (s, k) {
    return { label: s[0], value: count(P, s[1]), color: mix(C.greenTint, C.greenDark, 0.35 + 0.65 * (1 - k / steps.length)) };
  }), { total: P.length, labelW: 230, what: "Step", unit: "Preprints" });

  var c2 = card(cards, "Open science, at a glance", "The share of preprints with each.");
  tiles(c2, [
    { value: share(function (p) { return p.prereg > 0; }), label: "link to a preregistration" },
    { value: share(function (p) { return p.repos > 0 || p.files > 0; }), label: "link to a repository" },
    { value: share(function (p) { return p.f_data > 0 || p.dfiles > 0; }), label: "share data" },
    { value: share(function (p) { return p.code > 0; }), label: "share code" },
    { value: share(function (p) { return p.readme > 0; }), label: "have a readme in the repository" },
    { value: share(function (p) { return p.orcid > 0; }), label: "list an ORCID (as the converted text shows it)" },
    { value: share(function (p) { return p.email > 0; }), label: "give an email address" },
    { value: share(function (p) { return p.live > 0; }), label: "collected new data, by their text" },
    { value: pc(count(P, function (p) { return p.live > 0 && p.ethics > 0; }), count(P, function (p) { return p.live > 0; })), label: "of those mention ethics approval" }
  ]);

  var c3 = card(cards, "Preregistration templates", "The kinds of preregistration the preprints link to.");
  hbars(c3, list(D.counts.prereg_templates), { labelW: 260, clip: 44, what: "Template", unit: "Preregistrations" });

  var c4 = card(cards, "Do open preprints have fewer flags?", "The average number of checks flagged red or yellow, for preprints with and without each. (Sharing code adds checks that can flag it, so this is not a fair race.)");
  var feats = [["a preregistration", function (p) { return p.prereg > 0; }], ["a repository", function (p) { return p.repos > 0 || p.files > 0; }],
               ["shared data", function (p) { return p.f_data > 0 || p.dfiles > 0; }], ["shared code", function (p) { return p.code > 0; }],
               ["a power analysis", function (p) { return p.pow > 0; }], ["a question mark in the title", function (p) { return p.tq; }],
               ["a colon in the title", function (p) { return p.tc; }], ["more than 5 authors", function (p) { return p.auth > 5; }]];
  dumbbell(c4, feats.map(function (f) {
    var yes = P.filter(f[1]), no = P.filter(function (p) { return !f[1](p); });
    var my = yes.length ? mean(yes.map(function (p) { return p.flags; })) : null, mn = no.length ? mean(no.map(function (p) { return p.flags; })) : null;
    return { label: "with " + f[0], a: mn, b: my,
             tipA: "<b>without " + esc(f[0]) + "</b><br>" + no.length + " preprints, on average " + (mn === null ? "–" : mn.toFixed(2)) + " flags",
             tipB: "<b>with " + esc(f[0]) + "</b><br>" + yes.length + " preprints, on average " + (my === null ? "–" : my.toFixed(2)) + " flags" };
  }).filter(function (r) { return r.a !== null && r.b !== null; }),
  [{ label: "without", color: C.grey }, { label: "with", color: C.green }], { xlabel: "checks red or yellow, on average" });
}

function drawCode(cards) {
  var withCode = P.filter(function (p) { return p.code > 0; });
  var c = card(cards, "Languages", "The preprints with code in each language.");
  hbars(c, list(D.counts.languages), { total: withCode.length, labelW: 120, color: C.s1, what: "Language", unit: "Preprints" });
  tiles(c, [{ value: fmt(total("code")), label: "code files" }, { value: big(total("loc")), label: "lines of code" },
            { value: big(total("comments")), label: "lines of comments" }]);

  ["R", "Python"].forEach(function (lang) {
    var pk = (D.counts.packages || {})[lang] || [];
    if (!pk.length) return;
    var cc = card(cards, "The " + lang + " packages they load", "The number of preprints whose " + lang + " code loads each package.");
    hbars(cc, pk.slice(0, 20).map(function (q) { return { label: q[0], value: q[1], color: lang === "R" ? C.s1 : C.s3 }; }), { labelW: 130, what: "Package", unit: "Preprints" });
  });

  var c2 = card(cards, "Lines of code per preprint", "Each dot is a preprint that shares code (log scale).");
  strip(c2, vals("loc", function (p) { return p.code > 0; }), { mode: "log1p", label: "lines of code" });

  var c3 = card(cards, "How much of the code is comments", "Lines of comments as a share of all lines, per preprint with at least 20 lines of code.");
  strip(c3, P.filter(function (p) { return p.loc >= 20; }).map(function (p) {
    var s = p.comments / (p.loc + p.comments);
    return { v: s, tip: paperTip(p, Math.round(s * 100) + "% comments"), href: link(p), color: C.s3 };
  }), { dom: [0, 1], fmt: function (v) { return Math.round(v * 100) + "%"; }, vfmt: function (v) { return Math.round(v * 100) + "%"; }, label: "share of comment lines" });

  var c4 = card(cards, "Habits that break code on another computer", "Of the preprints that share code, how many have each in at least one file.");
  hbars(c4, [
    { label: "sets the working folder (setwd)", value: count(withCode, function (p) { return p.setwd > 0; }) },
    { label: "uses a path on the author's computer", value: count(withCode, function (p) { return p.abspath > 0; }) },
    { label: "installs packages when it runs", value: count(withCode, function (p) { return p.install > 0; }) },
    { label: "reads files that are not shared", value: count(withCode, function (p) { return p.missing_in > 0; }) }
  ], { total: withCode.length, labelW: 260, color: C.yellow, what: "Habit", unit: "Preprints" });
}

function drawRepro(cards) {
  var c = card(cards, "What happened to each script", "Metacheck runs the R and Python scripts it finds, each in an empty computer with the shared files.", true);
  var oc = D.counts.outcomes, ran = { ran_ok: 1, run_by_import: 1, run_by_source: 1, defines_functions: 1, not_analysis: 1, jags_model: 1, not_r_content: 1 };
  hbars(c, oc.map(function (q) { return { label: OUTCOME_NAME[q[0]] || q[0].replace(/_/g, " "), value: q[1], color: ran[q[0]] ? C.fine : C.red }; }),
        { total: sum(oc.map(function (q) { return q[1]; })), labelW: 300, clip: 46, what: "Outcome", unit: "Scripts" });

  var c2 = card(cards, "R against Python", "The scripts that ran through, per language.");
  var ol = D.counts.outcome_lang || {};
  stack100(c2, Object.keys(ol).map(function (l) { return { label: l + " (" + fmt(ol[l].ran + ol[l].broke) + " scripts)", counts: ol[l] }; }),
           [{ key: "ran", label: "ran through", color: C.fine }, { key: "broke", label: "did not", color: C.red }], { labelW: 170 });
  var c3 = card(cards, "Why scripts stopped", "From the error message of each script that did not run through.");
  hbars(c3, list(D.counts.message_kinds), { labelW: 280, clip: 44, color: C.red, what: "Why", unit: "Scripts" });

  var c4 = card(cards, "The most frequent error messages", "With file and object names replaced by '…'.", true);
  var ul = el("ul", { class: "messages" });
  D.counts.messages.slice(0, 15).forEach(function (m) {
    var li = el("li", {});
    li.appendChild(el("b", {}, fmt(m[1])));
    li.appendChild(el("code", {}, m[0]));
    ul.appendChild(li);
  });
  c4.appendChild(ul);

  if (D.counts.missing_packages.length) {
    var c5 = card(cards, "Packages that were missing", "Named in the error messages.");
    hbars(c5, list(D.counts.missing_packages, null, C.red), { labelW: 140, what: "Package", unit: "Scripts" });
  }

  var c6 = card(cards, "Share of scripts that ran, per preprint", "Each dot is a preprint with scripts Metacheck ran.");
  strip(c6, P.filter(function (p) { return p.scr > 0; }).map(function (p) {
    return { v: p.ran / p.scr, tip: paperTip(p, p.ran + " of " + p.scr + " scripts ran through"), href: link(p), color: p.broke ? C.red : C.fine };
  }), { dom: [0, 1], fmt: function (v) { return Math.round(v * 100) + "%"; }, vfmt: function (v) { return Math.round(v * 100) + "%"; }, label: "scripts that ran through" });
  var all = count(P, function (p) { return p.scr > 0 && p.broke === 0; }), some = count(P, function (p) { return p.scr > 0; });
  say(c6, "In " + fmt(all) + " of " + fmt(some) + " preprints (" + pc(all, some) + ") every script ran through.");
}

function drawData(cards) {
  var withData = P.filter(function (p) { return p.cols > 0; });
  var c = card(cards, "The data, column by column", "Every column of every data file Metacheck could read.");
  tiles(c, [{ value: fmt(total("dfiles")), label: "data files" }, { value: fmt(total("cols")), label: "columns" },
            { value: fmt(withData.length), label: "preprints with data Metacheck could read" }]);
  stack100(c, [{ label: "measurement level", counts: obj(D.counts.levels) }],
           [{ key: "ratio", label: "numbers", color: C.s1 }, { key: "ordinal", label: "ordered", color: C.s3 }, { key: "nominal", label: "categories", color: C.s2 }, { key: "unknown", label: "unknown", color: C.na }], { labelW: 130 });
  stack100(c, [{ label: "what a column is", counts: obj(D.counts.roles) }],
           [{ key: "measure", label: "a measure", color: C.s1 }, { key: "condition", label: "a condition", color: C.s2 }, { key: "identifier", label: "an identifier", color: C.s3 }, { key: "timestamp", label: "a time", color: C.yellow }], { labelW: 130 });
  stack100(c, [{ label: "content", counts: obj(D.counts.quality) }],
           [{ key: "ok", label: "varies", color: C.fine }, { key: "constant", label: "the same in every row", color: C.yellow }, { key: "empty", label: "empty", color: C.red }], { labelW: 130 });

  var c2 = card(cards, "Possible problems in the data", "What the data check flagged, by kind.");
  hbars(c2, list(D.counts.data_issues, null, C.yellow), { labelW: 250, clip: 40, what: "Problem", unit: "Times flagged" });

  var c3 = card(cards, "Columns per preprint", "Each dot is a preprint with data (log scale).");
  strip(c3, vals("cols", function (p) { return p.cols > 0; }), { mode: "log", label: "data columns" });

  var c4 = card(cards, "Missing values", "The average share of missing values in a preprint's columns.");
  strip(c4, P.filter(function (p) { return p.cmiss !== null; }).map(function (p) {
    return { v: p.cmiss, tip: paperTip(p, Math.round(p.cmiss * 100) + "% missing on average"), href: link(p), color: C.s2 };
  }), { dom: [0, 1], fmt: function (v) { return Math.round(v * 100) + "%"; }, vfmt: function (v) { return Math.round(v * 100) + "%"; }, label: "share missing" });

  var c5 = card(cards, "Codebooks", "Columns that have a label or a description in a codebook, and columns that do not.");
  var lab = total("cb_lab"), unl = total("cb_unlab");
  tiles(c5, [{ value: fmt(lab), label: "columns with a label" }, { value: fmt(unl), label: "columns without one", kind: "yellow" },
             { value: pc(lab, lab + unl), label: "labelled" }]);
  if (D.counts.careless_reasons.length) {
    say(c5, "Careless responding: " + fmt(total("careless")) + " respondents flagged (" +
        D.counts.careless_reasons.map(function (q) { return q[0] + ": " + q[1]; }).join(", ") + ").");
  }
}
function obj(pairs) { var o = {}; pairs.forEach(function (q) { o[q[0]] = q[1]; }); return o; }

function drawRepos(cards) {
  var c = card(cards, "What is in the repositories", "The file types, by the number of preprints whose repository has at least one.");
  hbars(c, list(D.counts.extensions.slice(0, 24), function (e) { return "." + e; }, C.s1), { labelW: 90, what: "Type", unit: "Preprints" });

  var c2 = card(cards, "File names that cause trouble", "The number of preprints with at least one file name of each kind.");
  hbars(c2, list(D.counts.naming_rules, function (r) { return NAMING_NAME[r] || r; }, C.yellow), { labelW: 300, clip: 48, what: "Name", unit: "Preprints" });

  var c3 = card(cards, "Files per preprint", "Each dot is a preprint with a repository (log scale).");
  strip(c3, vals("files", function (p) { return p.files > 0; }), { mode: "log", label: "files" });

  var c4 = card(cards, "The size of the repositories", "All files of a preprint together (log scale).");
  strip(c4, P.filter(function (p) { return p.bytes > 0; }).map(function (p) {
    return { v: p.bytes, tip: paperTip(p, bytes(p.bytes) + " in " + fmt(p.files) + " files"), href: link(p), color: C.s3 };
  }), { mode: "log", label: "bytes", fmt: function (v) { return bytes(v).replace(" bytes", " B"); }, vfmt: bytes });
}

function drawLiterature(cards) {
  var c = card(cards, "References per preprint", "");
  histogram(c, P.map(function (p) { return p.refs; }), 0, 200, 10, { open: true, every: 2, unit: "preprints", xlabel: "references", ylabel: "preprints" });
  say(c, "The median preprint cites " + fmt(median(P.map(function (p) { return p.refs; }))) + " works; " + fmt(total("refs")) + " references in total.");

  var c2 = card(cards, "When the cited works were published", "Every reference, by its year, from 1950 (older ones in the first bar).", true);
  var ys = D.counts.ref_years, byY = {}, now = new Date().getUTCFullYear();
  ys.forEach(function (q) { var y = Math.max(1950, q[0]); byY[y] = (byY[y] || 0) + q[1]; });
  var items = [];
  for (var y = 1950; y <= now; y++) items.push({ label: String(y), value: byY[y] || 0, color: C.s1,
    tip: "<b>" + (y === 1950 ? "1950 or before" : y) + "</b><br>" + fmt(byY[y] || 0) + " references" });
  columns(c2, items, { every: 10, ylabel: "references", what: "Year", unit: "References" });
  var oldest = ys.length ? ys[0][0] : null;
  if (oldest) say(c2, "The oldest cited work is from " + oldest + ".");

  var c3 = card(cards, "How old the cited works are", "The years between a cited work and the preprint, over all references (60 or more in the last bar).");
  columns(c3, D.counts.ref_ages.map(function (q) {
    return { label: String(q[0]), value: q[1], tip: "<b>" + q[0] + (q[0] === 60 ? " years or more" : " years") + "</b><br>" + fmt(q[1]) + " references" };
  }), { every: 10, xlabel: "years old", ylabel: "references", what: "Years old", unit: "References" });

  var c4 = card(cards, "The median age per preprint", "Each dot is a preprint: the median age of its references.");
  strip(c4, vals("refage", function (p) { return p.refage !== null; }), { label: "years" });

  var c5 = card(cards, "The works cited most", "Cited by several of the checked preprints.", true);
  var ol = el("ol", { class: "works" });
  D.counts.cited.forEach(function (w) {
    var li = el("li", {});
    li.appendChild(el("span", { class: "n" }, w.n + " preprints: "));
    var t = w.doi ? el("a", { href: /^https?:/.test(w.doi) ? w.doi : "https://doi.org/" + w.doi, target: "_blank", rel: "noopener" }, w.title || w.doi) : el("span", {}, w.title || "");
    li.appendChild(t);
    li.appendChild(el("span", { class: "where" }, " " + [w.journal, w.year].filter(Boolean).join(", ")));
    ol.appendChild(li);
  });
  c5.appendChild(ol);

  var c6 = card(cards, "The journals cited most", "References per journal, over all preprints.");
  hbars(c6, list(D.counts.journals.slice(0, 20), null, C.s1), { labelW: 270, clip: 42, what: "Journal", unit: "References" });

  var c7 = card(cards, "The literature's own problems", "What the reference checks found in the cited works.");
  tiles(c7, [{ value: fmt(total("pubpeer")), label: "cited works with PubPeer comments", tip: fmt(total("ppcom")) + " comments" },
             { value: share(function (p) { return p.pubpeer > 0; }), label: "of the preprints cite at least one" },
             { value: fmt(total("retract")), label: "cited works with a retraction notice or correction", kind: total("retract") ? "red" : "" },
             { value: fmt(total("repl")), label: "cited works that were replicated" }]);
  if (D.counts.replication_outcomes.length) {
    stack100(c7, [{ label: "replications", counts: obj(D.counts.replication_outcomes) }],
             [{ key: "successful", label: "successful", color: C.fine }, { key: "mixed", label: "mixed", color: C.yellow }, { key: "failed", label: "failed", color: C.red }], { labelW: 110 });
  }
  hbars(c7, list(D.counts.bib_types, function (t) { return { article: "articles", book: "books", incollection: "chapters", misc: "other" }[t] || t; }),
        { labelW: 100, what: "Kind", unit: "References" });
}

function drawPreprints(cards) {
  var c = card(cards, "Words per preprint", "The words in the text Metacheck read.");
  histogram(c, P.map(function (p) { return p.words / 1000; }), 0, 30, 1, { open: true, every: 5, unit: "preprints", xlabel: "thousand words", ylabel: "preprints",
    binName: function (a, b, last) { return last ? a + " thousand words or more" : a + " to " + b + " thousand words"; } });
  say(c, "The median preprint has " + fmt(median(P.map(function (p) { return p.words; }))) + " words.");

  var c2 = card(cards, "Authors per preprint", "");
  var au = tally(P, function (p) { return Math.min(p.auth, 15); });
  var items = [];
  for (var a = 1; a <= 15; a++) items.push({ label: a === 15 ? "15+" : String(a), value: au[a] || 0, tip: "<b>" + (a === 15 ? "15 or more" : a) + " authors</b><br>" + fmt(au[a] || 0) + " preprints" });
  columns(c2, items, { every: 1, xlabel: "authors", ylabel: "preprints", what: "Authors", unit: "Preprints" });
  var single = count(P, function (p) { return p.auth === 1; });
  say(c2, fmt(single) + " preprints have a single author; the largest team has " + fmt(maxOf(P.map(function (p) { return p.auth; }))) + ".");

  var c3 = card(cards, "Countries", "The preprints with at least one author affiliation in each country (as far as Metacheck can read the affiliation).");
  hbars(c3, list(D.counts.countries.slice(0, 20), null, C.s1), { labelW: 140, total: P.length, what: "Country", unit: "Preprints" });

  var c4 = card(cards, "The words in the titles", "Larger: in more titles.", true);
  words(c4, D.counts.title_words.slice(0, 60), { unit: "titles" });

  var c5 = card(cards, "Keywords", "The keywords the authors gave.", true);
  words(c5, D.counts.keywords, { unit: "preprints" });

  var c6 = card(cards, "Titles", "");
  tiles(c6, [{ value: fmt(median(P.map(function (p) { return p.tw; }))), label: "words in the median title" },
             { value: share(function (p) { return p.tq; }), label: "of the titles ask a question" },
             { value: share(function (p) { return p.tc; }), label: "have a colon" }]);
  var tw = tally(P, function (p) { return Math.min(p.tw, 30); }), tws = [];
  for (var k = 1; k <= 30; k++) tws.push({ label: String(k), value: tw[k] || 0, tip: "<b>" + k + " words</b><br>" + fmt(tw[k] || 0) + " titles" });
  columns(c6, tws, { every: 5, xlabel: "words in the title", ylabel: "preprints", height: 150, table: false });

  var c7 = card(cards, "The parts of the papers", "The sections Metacheck recognised, over all preprints.");
  hbars(c7, list(D.counts.section_types.slice(0, 14)), { labelW: 140, what: "Section", unit: "Sections" });

  var c8 = card(cards, "Where the links go", "The websites linked from the preprints' text.");
  hbars(c8, list(D.counts.domains.slice(0, 15), null, C.s1), { labelW: 230, clip: 36, what: "Website", unit: "Links" });

  var c9 = card(cards, "Figures, tables and equations", "");
  tiles(c9, [{ value: fmt(median(P.map(function (p) { return p.figs; }))), label: "figures in the median preprint" },
             { value: fmt(maxOf(P.map(function (p) { return p.figs; }))), label: "figures at most" },
             { value: fmt(median(P.map(function (p) { return p.eqs; }))), label: "equations and statistics in the median preprint" },
             { value: fmt(median(P.map(function (p) { return p.secs; }))), label: "sections in the median preprint" }]);
  strip(c9, vals("figs"), { label: "figures per preprint", color: C.s3 });

  var c10 = card(cards, "Authors with more than one preprint", "How many people are an author of one, two, three or more of the checked preprints.");
  columns(c10, D.counts.authors_per_count.map(function (q) {
    return { label: String(q[0]), value: q[1], tip: "<b>" + fmt(q[1]) + " people</b><br>are an author of " + q[0] + " preprint" + (q[0] > 1 ? "s" : "") };
  }), { every: 1, xlabel: "preprints", ylabel: "people", what: "Preprints", unit: "People" });
}

var VARS = [
  ["words", "words in the text"], ["refs", "references"], ["refage", "median age of the references"], ["auth", "authors"],
  ["tw", "words in the title"], ["figs", "figures"], ["eqs", "equations and statistics"], ["p", "p values"],
  ["pimp", "imprecise p values"], ["nonsig", "non-significant p values"], ["sc", "tests StatCheck read"],
  ["scerr", "StatCheck inconsistencies"], ["pow", "power analyses"], ["files", "files in the repository"],
  ["code", "code files"], ["loc", "lines of code"], ["scr", "scripts run"], ["broke", "scripts that did not run through"],
  ["cols", "data columns"], ["dissues", "data problems"], ["pubpeer", "cited works with PubPeer comments"],
  ["flags", "checks red or yellow"], ["reds", "checks red"]
];
function drawCorrelations(cards) {
  var c = card(cards, "Everything against everything",
    "The rank correlation (Spearman) between every two counts, over all preprints. Orange: the two go up together; blue: one goes up as the other goes down. Point at a square to see the pair; click it to plot the pair below.", true);
  var cols = VARS.map(function (v) { return P.map(function (p) { return p[v[0]] === undefined ? null : p[v[0]]; }); });
  legend(c, [{ label: "−1", color: C.s1 }, { label: "0", color: C.mid }, { label: "+1", color: C.s2 }]);
  var cache = {};
  function rho(i, j) {
    var k = i < j ? i + "," + j : j + "," + i;
    if (!(k in cache)) cache[k] = spearman(cols[i], cols[j]);
    return cache[k];
  }
  var s = grid(c, VARS.length, VARS.length, function (i, j) {
    if (i === j) return { fill: C.surface, tip: "<b>" + esc(VARS[i][1]) + "</b>" };
    var r = rho(i, j);
    return { fill: diverging(r.r), dark: r.r !== null && Math.abs(r.r) > 0.6,
             tip: "<b>" + esc(VARS[i][1]) + "</b><br>and <b>" + esc(VARS[j][1]) + "</b><br>ρ = " + (r.r === null ? "–" : r.r.toFixed(2)) + " over " + r.n + " preprints",
             label: r.r !== null && Math.abs(r.r) >= 0.5 ? r.r.toFixed(1).replace(/^(-?)0/, "$1") : "" };
  }, { labelW: 210, cellH: 19, top: 20, rowLabel: function (i) { return VARS[i][1]; }, colLabel: function (j) { return String(j + 1); }, font: 11, gap: 1 });
  s.addEventListener("click", function (e) {
    var t = e.target;
    if (t.tagName !== "rect") return;
    var gm = s.geometry, box = s.getBoundingClientRect(), x = (e.clientX - box.left) * gm.w / box.width, y = (e.clientY - box.top) * parseFloat(s.getAttribute("viewBox").split(" ")[3]) / box.height;
    var j = Math.floor((x - gm.lw) / gm.cw), i = Math.floor((y - gm.top) / gm.ch);
    if (i >= 0 && j >= 0 && i < VARS.length && j < VARS.length && i !== j) { selX.value = VARS[j][0]; selY.value = VARS[i][0]; plot(); c2.scrollIntoView({ behavior: "smooth", block: "center" }); }
  });
  // the numbers of the columns, under the names
  say(c, VARS.map(function (v, i) { return (i + 1) + " " + v[1]; }).join(" · "));

  var c2 = card(cards, "Make your own chart", "Choose any two counts. Each dot is a preprint; click one to open its report.", true);
  var ctl = el("div", { class: "controls" });
  function select(def) {
    var s = el("select", {});
    VARS.forEach(function (v) { var o = el("option", { value: v[0] }, v[1]); if (v[0] === def) o.selected = true; s.appendChild(o); });
    s.addEventListener("change", plot);
    return s;
  }
  var selX = select("words"), selY = select("flags");
  var logBox = el("input", { type: "checkbox" }); logBox.checked = true; logBox.addEventListener("change", plot);
  var lab = el("label", {}); lab.appendChild(logBox); lab.appendChild(document.createTextNode("log scales"));
  ctl.appendChild(document.createTextNode("Across: ")); ctl.appendChild(selX);
  ctl.appendChild(document.createTextNode(" Up: ")); ctl.appendChild(selY); ctl.appendChild(lab);
  c2.appendChild(ctl);
  var out = el("div", {}); c2.appendChild(out);
  function name(k) { return VARS.filter(function (v) { return v[0] === k; })[0][1]; }
  function plot() {
    out.innerHTML = "";
    var xk = selX.value, yk = selY.value, lg = logBox.checked;
    var pts = P.filter(function (p) { return p[xk] !== null && p[yk] !== null && p[xk] !== undefined && p[yk] !== undefined; }).map(function (p) {
      return { x: p[xk], y: p[yk], href: link(p), color: p.reds ? C.red : C.s1, tip: paperTip(p, esc(name(xk)) + ": " + fmt(p[xk]) + "<br>" + esc(name(yk)) + ": " + fmt(p[yk])) };
    });
    scatter(out, pts, { xmode: lg ? "log1p" : "lin", ymode: lg ? "log1p" : "lin", xlabel: name(xk), ylabel: name(yk), height: 340 });
    var r = spearman(pts.map(function (q) { return q.x; }), pts.map(function (q) { return q.y; }));
    say(out, "Spearman's ρ = " + (r.r === null ? "–" : r.r.toFixed(2)) + " over " + r.n + " preprints. Red dots: preprints with at least one red light.");
  }
  plot();
}

function drawRecords(cards) {
  var c = card(cards, "Records", "The extremes among the checked preprints. Click a title to open its report.", true);
  var ul = el("ul", { class: "records" });
  function rec(label, key, show, f) {
    var ps = P.filter(f || function (p) { return p[key] !== null && p[key] !== undefined; });
    if (!ps.length) return;
    var best = ps.reduce(function (a, b) { return b[key] > a[key] ? b : a; });
    if (!best[key]) return;
    var li = el("li", {});
    li.appendChild(document.createTextNode(label + ": "));
    li.appendChild(el("b", {}, show ? show(best[key]) : fmt(best[key])));
    li.appendChild(document.createTextNode(", in "));
    li.appendChild(el("a", { href: link(best) }, best.t || best.id));
    ul.appendChild(li);
  }
  rec("The longest text", "words", function (v) { return fmt(v) + " words"; });
  rec("The most references", "refs", function (v) { return fmt(v) + " references"; });
  rec("The oldest cited work", "refold", function (v) { return v + " years older than the preprint"; });
  rec("The most authors", "auth", function (v) { return fmt(v) + " authors"; });
  rec("The most p values", "p", function (v) { return fmt(v) + " p values"; });
  rec("The most tests StatCheck could read", "sc", function (v) { return fmt(v) + " tests"; });
  rec("The most power analyses", "pow", function (v) { return fmt(v) + " power analyses"; });
  rec("The most figures", "figs", function (v) { return fmt(v) + " figures"; });
  rec("The most equations and statistics", "eqs", function (v) { return fmt(v); });
  rec("The largest repository", "bytes", bytes);
  rec("The most files", "files", function (v) { return fmt(v) + " files"; });
  rec("The most lines of code", "loc", function (v) { return fmt(v) + " lines"; });
  rec("The most scripts run", "scr", function (v) { return fmt(v) + " scripts"; });
  rec("The most scripts that ran through", "ran", function (v) { return fmt(v) + " scripts"; });
  rec("The most data columns", "cols", function (v) { return fmt(v) + " columns"; });
  rec("The most links in the text", "urls", function (v) { return fmt(v) + " links"; });
  rec("The longest title", "tw", function (v) { return fmt(v) + " words"; });
  c.appendChild(ul);
}

// ---- start -------------------------------------------------------------------

fetch("../data/totals.json", { cache: "no-cache" })
  .then(function (r) { if (!r.ok) throw new Error("file not found (" + r.status + ")"); return r.json(); })
  .then(function (data) {
    D = data; P = D.papers; MODS = D.modules;
    P.forEach(function (p, i) {
      p.i = i; p.reds = 0; p.yellows = 0; p.applied = 0;
      for (var k = 0; k < MODS.length; k++) {
        var ch = p.L.charAt(k);
        if (ch === "r") p.reds++;
        if (ch === "y") p.yellows++;
        if (ch !== "n" && ch !== "f" && ch) p.applied++;
      }
      p.flags = p.reds + p.yellows;
      p.date = toDate(p.pub); p.cdate = toDate(p.chk);
    });
    var up = toDate(D.updated);
    document.getElementById("updated").textContent = fmt(P.length) + " preprints, counted on " + dayYear(up) + ".";
    sectionsBox.innerHTML = "";
    section("numbers", "In numbers", "Everything Metacheck counted, added up.", drawNumbers);
    section("lights", "The traffic lights", "Each check gives a preprint a light: red (to fix), yellow (to check), blue (for information), green (fine), or grey when it had nothing to check.", drawWall);
    section("relations", "How problems relate", "Do the flags of one check come with the flags of another?", drawRelations);
    section("time", "Over time", "", drawTime);
    section("pvalues", "P values", "Every p value Metacheck found in the text.", drawP);
    section("statcheck", "Tests and effect sizes", "", drawStatcheck);
    section("power", "Power analyses", "", drawPower);
    section("open", "Open science", "", drawOpen);
    section("code", "Code", "The code files in the preprints' repositories.", drawCode);
    section("repro", "Running the code", "", drawRepro);
    section("data", "Data", "", drawData);
    section("repos", "Repositories", "", drawRepos);
    section("literature", "The cited literature", "", drawLiterature);
    section("preprints", "The preprints themselves", "", drawPreprints);
    section("correlations", "Everything against everything", "", drawCorrelations);
    section("records", "Records", "", drawRecords);
  })
  .catch(function (err) {
    sectionsBox.innerHTML = "";
    sectionsBox.appendChild(el("p", { class: "warning" }, "The totals could not be loaded: " + err.message));
  });
