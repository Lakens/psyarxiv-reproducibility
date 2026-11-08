# The scheduled run: lists PsyArXiv preprints on the OSF, sends each one's file
# to the SURF server for metacheck's checks, and saves the results in data/.
# GitHub runs it every hour (.github/workflows/update.yml). Uses only the
# Python standard library.
#
#   python scripts/update.py [--minutes 50] [--max 0] [--data-dir data] [--site-dir .]
#   python scripts/update.py --redo jc6rp_v1 qgef5_v2   (check these again; their
#                     files are overwritten)
#
# Order: preprints published since the last run first, newest first. When none
# is waiting, older ones, one day at a time going back, until BACKFILL_LIMIT
# older preprints have been sent to the server. A preprint is checked in the
# version that is its newest when it is checked; the reports on its older
# versions stay.
#
# Each preprint, named by its OSF id with its version (e.g. jc6rp_v1):
#   <site-dir>/<id>/index.html  the server's checklist report, so its address
#                     ends in the id as the OSF's does; the font and logo it
#                     carries are linked to the site's identical copies
#   <data-dir>/papers/<id>.json  the OSF details and everything the server
#                     returned except the report page (saved above), with the
#                     paper as converted (`paper`: its full text, sections,
#                     references, tables), which metacheck can read again
#
# Other files in the data folder:
#   index.json        one line per checked preprint, for the list of reports
#   tally.json        the numbers on the landing page
#   modules/<module>.json  the findings of one check in every preprint, for
#                     the page of examples per check (modules/index.html),
#                     because the full results are not on the website
#   state.json       where the run is: the newest preprint listed, the next
#                     older day to list, the preprints waiting, and those
#                     skipped or failed

import argparse
import base64
import collections
import datetime as dt
import glob
from html import escape as html_escape, unescape as html_unescape
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from test_surf_jobs import post_job, SERVER

OSF = "https://api.osf.io/v2"
LIST = OSF + "/preprints/?filter[provider]=psyarxiv&page[size]=100"
UA = "psyarxiv_metacheck (github.com/Lakens/psyarxiv_metacheck)"
# the checks the SURF server runs for its regular report; with run_code=true the
# server adds reproducibility_check, which runs the paper's code in the sandbox
MODULES = ("power,marginal,prereg_check,ethics_check,ref_pubpeer,ref_retraction,"
           "ref_replication,stat_check,stat_p_exact,stat_p_nonsig,stat_effect_size,"
           "repo_check,code_check,data_check,codebook_check")
FILE_TYPES = {"pdf": "application/pdf",
              "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
MAX_BYTES = 50 * 1024 ** 2      # the server refuses larger files (api.R MAX_UPLOAD_BYTES)
JOB_WAIT_MINUTES = 75           # the server stops a paper's code after 60 minutes
MAX_TRIES = 2                   # a preprint whose job fails is tried this often
BACKFILL_LIMIT = 1000           # older preprints sent to the server, at most
FIRST_DAY = dt.date(2016, 9, 1)  # PsyArXiv's first preprints
# files the report page carries inside it that the site has too
SHARED_FILES = {"font/ttf": "fonts/Cabin.ttf", "image/png": "images/logo.png"}


# Keys (passwords for paid services) that authors left in their files can end
# up in metacheck's result, and GitHub refuses to store a file that contains
# one. So everything saved is searched for keys, and each key found is
# replaced by KEY_REMOVED. The rules are those of the secret scanner
# betterleaks (https://github.com/betterleaks/betterleaks, MIT licence, (c) the
# betterleaks authors, who also made gitleaks), as collected in
# key_patterns.json by make_key_patterns.py, which says which rules are taken
# and why. Each rule is tried only on text that contains one of its
# keywords, as betterleaks does. Of a match, only the key is replaced: the
# rule's group for it, else its first group that found text, else all of it.
# A find is kept out, as betterleaks does, when it is less random than the
# rule asks (its minimum entropy) or is a placeholder (such as ${API_KEY}).
KEY_REMOVED = "[key removed]"
KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "key_patterns.json")
KEY_PATTERNS = None     # read on first use
KEY_IGNORE = None


def key_patterns():
    global KEY_PATTERNS, KEY_IGNORE
    if KEY_PATTERNS is None:
        with open(KEY_FILE, encoding="utf-8") as f:
            d = json.load(f)
        KEY_PATTERNS = [{"name": p["name"], "re": re.compile(p["regex"]), "keywords": p["keywords"],
                         "group": p.get("group"), "entropy": p.get("entropy")} for p in d["patterns"]]
        KEY_IGNORE = {"patterns": [re.compile(x) for x in d["ignore"]["patterns"]],
                      "texts": d["ignore"]["texts"]}
    return KEY_PATTERNS


def not_a_key(secret, p):
    # betterleaks' filters: too little entropy for this rule, or a placeholder
    e = p["entropy"]
    if e and (entropy(secret) <= e["min"] if e["strict"] else entropy(secret) < e["min"]):
        return True
    return (any(x.search(secret) for x in KEY_IGNORE["patterns"])
            or any(t in secret for t in KEY_IGNORE["texts"]))


def entropy(s):
    # Shannon entropy in bits per character, as betterleaks computes it
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in collections.Counter(s).values()) if n else 0


KEY_WINDOW = 5000   # characters searched on either side of a keyword


def windows(low, keywords):
    # the stretches of text within KEY_WINDOW characters of a keyword, joined
    # where they overlap. TruffleHog likewise tries a detector's patterns on
    # each piece of about 10,000 characters that contains one of its
    # keywords. It also keeps a long text fast: Python's searches are much
    # slower than those of Go, the language betterleaks is written in.
    if len(low) <= 2 * KEY_WINDOW:
        return [(0, len(low))] if any(k in low for k in keywords) else []
    spans = []
    for k in keywords:
        i = low.find(k)
        while i != -1:
            spans.append((max(0, i - KEY_WINDOW), min(len(low), i + len(k) + KEY_WINDOW)))
            i = low.find(k, i + 1)
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def key_spans(text, patterns):
    # (start, end, pattern name) of each key the patterns find in text
    low = text.lower()
    spans = []
    for p in patterns:
        parts = windows(low, p["keywords"]) if p["keywords"] else [(0, len(text))]
        for a, b in parts:
            for m in p["re"].finditer(text, a, b):
                g = p["group"] or next((i for i in range(1, (m.re.groups or 0) + 1) if m.group(i)), 0)
                if not_a_key(m.group(g), p):
                    continue
                if m.end(g) > m.start(g):
                    spans.append((m.start(g), m.end(g), p["name"]))
    return spans


def remove_keys(obj, found):
    # obj (a result: dictionaries, lists, text) with every key in its text
    # replaced by KEY_REMOVED, in the names of dictionary entries too;
    # `found` counts the keys removed, by pattern
    whole = json.dumps(obj, ensure_ascii=False).lower()
    # only the patterns with a keyword somewhere in obj, tried on each text
    patterns = [p for p in key_patterns()
                if not p["keywords"] or any(k in whole for k in p["keywords"])]
    if not patterns:
        return obj

    def clean(text):
        spans = sorted(key_spans(text, patterns))
        if not spans:
            return text
        out, pos = [], 0
        for start, end, name in spans:
            if start < pos:              # inside a key already replaced
                if end > pos:
                    pos = end
                continue
            found[name] = found.get(name, 0) + 1
            out += [text[pos:start], KEY_REMOVED]
            pos = end
        return "".join(out) + text[pos:]

    def walk(x):
        if isinstance(x, str):
            return clean(x)
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, dict):
            return {walk(k): walk(v) for k, v in x.items()}
        return x
    return walk(obj)


class ServerDown(Exception):
    pass


class NotStored(Exception):
    # GitHub could not be reached, or refused for another reason than a key
    pass


def get(url, raw=False, tries=4):
    url = urllib.parse.quote(url, safe=":/?&=[]%,._-~")
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=300) as r:
                data = r.read()
            return data if raw else json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code == 404 or i == tries - 1:
                raise
            time.sleep(60 if e.code == 429 else 10)   # 429: the OSF asks to slow down
        except (urllib.error.URLError, TimeoutError):
            if i == tries - 1:
                raise
            time.sleep(10)


def list_all(url):
    # every preprint of a listing, following its pages
    out = []
    while url:
        page = get(url)
        out += page["data"]
        url = page["links"].get("next")
    return out


def entry(p, source):
    return {"id": p["id"], "published": p["attributes"]["date_published"], "source": source}


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:   # the same on Windows
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def split_id(osf_id):
    base, _, v = osf_id.partition("_v")
    return base, int(v) if v.isdigit() else 1


def reported(index, osf_id):
    # this version, or a newer version of the same preprint, has a report
    base, version = split_id(osf_id)
    return any(p["base_id"] == base and p["version"] >= version for p in index.values())


def known(state, index, osf_id):
    # waiting, skipped, failed, or reported
    if osf_id in state["skipped"] or osf_id in state["failed"]:
        return True
    if any(q["id"] == osf_id for q in state["queue"]):
        return True
    return reported(index, osf_id)


def list_new(state, index):
    # preprints published since the newest one listed, newest first, before
    # the preprints already waiting
    if state["newest"] is None:
        page = get(LIST)["data"]
        state["newest"] = max(p["attributes"]["date_published"] for p in page)
        state["backfill_day"] = state["newest"][:10]
        new = page
    else:
        new = list_all(LIST + "&filter[date_published][gt]=" + state["newest"])
    if not new:
        return
    state["newest"] = max([state["newest"]] + [p["attributes"]["date_published"] for p in new])
    new = [p for p in new if not known(state, index, p["id"])]
    new.sort(key=lambda p: p["attributes"]["date_published"], reverse=True)
    state["queue"] = [entry(p, "new") for p in new] + state["queue"]


def list_older_day(state, index):
    # all preprints published on the next older day, newest first, after the
    # preprints already waiting; False when there is no older day left
    day = dt.date.fromisoformat(state["backfill_day"])
    if day < FIRST_DAY:
        return False
    nxt = day + dt.timedelta(days=1)
    found = list_all(LIST + f"&filter[date_published][gte]={day}T00:00:00"
                     f"&filter[date_published][lt]={nxt}T00:00:00")
    found = [p for p in found if not known(state, index, p["id"])]
    found.sort(key=lambda p: p["attributes"]["date_published"], reverse=True)
    state["queue"] += [entry(p, "older") for p in found]
    state["backfill_day"] = str(day - dt.timedelta(days=1))
    return True


def authors_of(osf_id):
    data = get(f"{OSF}/preprints/{osf_id}/bibliographic_contributors/?embed=users&page[size]=100")["data"]
    data.sort(key=lambda c: c["attributes"].get("index", 0))
    return [c["embeds"]["users"]["data"]["attributes"]["full_name"]
            for c in data if "data" in c.get("embeds", {}).get("users", {})]


def run_job(name, data, ctype):
    # a check returns the JSON result; report=true adds the report page
    # (report_html), paper=true the paper as converted (`paper`: its full text,
    # sections, references, tables, ..., as metacheck reads it)
    fields = {"kind": "check", "report": "true", "paper": "true", "report_type": "checklist",
              "modules": MODULES, "run_code": "true", "crossref": "true"}
    try:
        job = post_job(fields, file=(name, data, ctype))
    except urllib.error.HTTPError as e:
        if e.code >= 500:
            raise ServerDown(f"the server answered {e.code}")
        return None, f"the server refused the file ({e.code}): {e.read().decode(errors='replace')[:300]}"
    except (urllib.error.URLError, TimeoutError) as e:
        raise ServerDown(str(e))
    remember_job(job["id"])
    end = time.time() + JOB_WAIT_MINUTES * 60
    while time.time() < end:
        time.sleep(15)
        try:
            status = get(f"{SERVER}/jobs/{job['id']}")
        except (urllib.error.URLError, TimeoutError) as e:
            raise ServerDown(str(e))
        if status.get("status") == "done":
            result = get(f"{SERVER}/jobs/{job['id']}/result")
            remember_job(None)
            return result, None
        if status.get("status") == "failed":
            remember_job(None)
            return None, status.get("error") or "the job failed"
    # still on the server: stop here rather than send a second job next to it
    raise ServerDown(f"job {job['id']} still running after {JOB_WAIT_MINUTES} minutes")


# One preprint at a time on the server, so that one of its two places stays
# free for other people: the job this script has on the server is kept in
# <data-dir>/current_job.json (committed with the data, so the next run sees
# it, even when GitHub stopped this one), and no job is sent while it runs.
CURRENT_JOB = os.path.join("data", "current_job.json")   # set in main()


def remember_job(job_id):
    save(CURRENT_JOB, {"id": job_id, "sent": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
         if job_id else {})


def server_idle():
    # True when the server answers and has no job running or waiting (also
    # not one of ours left by an earlier run, whose record is cleared once it
    # has finished); False otherwise, also when it cannot be reached
    try:
        if previous_job_running():
            return False
        health = get(f"{SERVER}/health", tries=1)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False
    return (health.get("status") == "ok" and not health.get("jobs_running")
            and not health.get("jobs_waiting"))


def pause(stop_at, seconds):
    # waits `seconds`, but not past stop_at; False when the run's time is up
    left = stop_at - time.time()
    if left <= 0:
        return False
    time.sleep(min(seconds, left))
    return time.time() < stop_at


def previous_job_running():
    job_id = load(CURRENT_JOB, {}).get("id")
    if not job_id:
        return False
    try:
        status = get(f"{SERVER}/jobs/{job_id}")
    except urllib.error.HTTPError as e:
        if e.code == 404:                    # finished over an hour ago: gone
            remember_job(None)
            return False
        raise
    if status.get("status") in ("done", "failed"):
        remember_job(None)
        return False
    return True


def drop_converter_note(html):
    # the line the server puts at the top of a report saying what converted
    # the file (worker.R, .add_converter_note()); the converter is kept in the
    # result file (`converter`)
    return re.sub(r'<div class="metacheck-converter"[^>]*>.*?</div>', "", html, count=1, flags=re.S)


def full_text_html(paper):
    # the paper's text as metacheck read it (the converted paper's `text`, one
    # row per sentence), as a folded block like the report's own: each
    # section's heading, then its paragraphs. Headings of sections without
    # text of their own (such as "Methods" above "Data") are kept, in order.
    rows = (paper or {}).get("text") or []
    if not rows:
        return ""
    headers = {}
    for s in (paper.get("section") or []):
        try:
            headers[int(s["section_id"])] = s.get("header") or ""
        except (KeyError, TypeError, ValueError):
            pass
    out, para, last_sec, last_par = [], [], None, None

    def end_paragraph():
        if para:
            out.append("<p>" + html_escape(" ".join(para)) + "</p>")
            para.clear()

    for r in rows:
        try:
            sec = int(r.get("section_id"))
        except (TypeError, ValueError):
            sec = last_sec
        if sec != last_sec and sec is not None:
            end_paragraph()
            # going forward: also the headings of the sections in between
            first = last_sec + 1 if last_sec is not None and sec > last_sec else sec
            for s in range(first, sec + 1):
                if headers.get(s):
                    out.append("<h3>" + html_escape(headers[s]) + "</h3>")
            last_sec, last_par = sec, None
        if r.get("paragraph_id") != last_par:
            end_paragraph()
            last_par = r.get("paragraph_id")
        if r.get("text"):
            para.append(str(r["text"]))
    end_paragraph()
    return ('<details id="full-text">\n<summary>\nFull text\n</summary>\n<div class="fold">\n'
            + "\n".join(out) + "\n</div>\n</details>\n")


def add_full_text(html, paper):
    # the full text as the last folded block of the report's "More detail"
    # section (before the two closing </div>s ahead of the footer); before the
    # footer when the page is laid out differently. Once only.
    block = full_text_html(paper)
    if not block or 'id="full-text"' in html:
        return html
    new, n = re.subn(r"(</div>\s*</div>\s*<footer>)", lambda m: block + m.group(1), html, count=1)
    if n == 0:
        new, n = re.subn(r"(<footer>|</body>)", lambda m: block + m.group(1), html, count=1)
    return new


BACK_STYLE = ('<style>.back-to-main{display:inline-block;padding:4px 12px;border:1px solid var(--green,#2F6F1C);'
              'border-radius:3px;background:#fff;color:var(--green,#2F6F1C);font-size:0.9rem;font-weight:600;'
              'text-decoration:none}.back-to-main:hover{background:var(--green,#2F6F1C);color:#fff}'
              '.back-bar{max-width:900px;margin:14px auto 0;padding:0 16px}'
              '@media print{.back-bar{display:none}}</style>')
BACK_BAR = ('<p class="back-bar"><a class="back-to-main" id="back-to-main" href="../">'
            '← Back to the main page</a></p>')


def add_way_back(html):
    # a link to the site's main page above the report's title, and the
    # Metacheck logo (the first logo in the header) as a link there too. Once only.
    if 'id="back-to-main"' not in html:
        html = re.sub(r"</head>", lambda m: BACK_STYLE + m.group(0), html, count=1)
        html = re.sub(r"<body[^>]*>", lambda m: m.group(0) + BACK_BAR, html, count=1)
    if 'class="logo-home"' not in html:
        html = re.sub(r'(<div class="logos">\s*)(<img[^>]*>)',
                      lambda m: m.group(1) + '<a class="logo-home" href="../" aria-label="Back to the main page">'
                      + m.group(2) + "</a>", html, count=1)
    return html


# The checklist report called a yellow result "To improve"; "To check" says
# better that it may well be fine (Daniel, 8 November 2026; metacheck says so
# itself from version 0.4.3.20, scienceverse/metacheck#618). Only the label's
# three places in the markup: the heading, each check's tag, and the count at
# the top, so text quoted from a paper or its data is left as it is.
OLD_LABEL = [
    (re.compile(r'(<h[1-6] id="improve">)To improve'), r"\1To check"),
    (re.compile(r'(<span class="tag improve">)To improve(</span>)'), r"\1To check\2"),
    (re.compile(r'(<span class="count improve[^"]*"><b>\d+</b><span>)to improve(</span>)'), r"\1to check\2"),
]


def relabel(html):
    for pattern, new in OLD_LABEL:
        html = pattern.sub(new, html)
    return html


def has_old_label(html):
    return any(pattern.search(html) for pattern, _ in OLD_LABEL)


def decorate_page(html, paper):
    # this site's changes to the server's report page
    return relabel(add_way_back(add_full_text(drop_converter_note(html), paper)))


def refresh_pages(site_dir, data_dir):
    # gives every report page this site's changes it does not have yet (such
    # as pages made before a change to this script); returns how many changed
    changed = 0
    for path in glob.glob(os.path.join(site_dir, "*_v*", "index.html")):
        with open(path, encoding="utf-8", newline="") as f:
            html = f.read()
        if ('id="back-to-main"' in html and 'class="logo-home"' in html and 'id="full-text"' in html
                and not has_old_label(html)):
            continue
        osf_id = os.path.basename(os.path.dirname(path))
        paper = load(os.path.join(data_dir, "papers", osf_id + ".json"), {}).get("paper")
        new = decorate_page(html, paper)
        if new != html:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(new)
            changed += 1
    return changed


def save_page(html, site_dir, osf_id, paper=None):
    # the report page in <site_dir>/<osf_id>/index.html; a font or image it
    # carries inside it is linked to the site's copy when the two are the same
    # file, byte for byte, and kept inside the page otherwise
    def link(m):
        rel = SHARED_FILES.get(m.group(1))
        if rel:
            with open(os.path.join(site_dir, rel), "rb") as f:
                if base64.b64decode(m.group(2)) == f.read():
                    return "../" + rel
        return m.group(0)
    html = re.sub(r"data:(font/ttf|image/png);base64,([A-Za-z0-9+/=]+)", link, html)
    html = decorate_page(html, paper)
    folder = os.path.join(site_dir, osf_id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "index.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(html)


def fail(state, osf_id, error):
    # one more failed try; after MAX_TRIES the preprint is listed as failed
    state["tries"][osf_id] = state["tries"].get(osf_id, 0) + 1
    print(f"{osf_id}: failed (try {state['tries'][osf_id]}): {error}", flush=True)
    if state["tries"][osf_id] >= MAX_TRIES:
        state["failed"][osf_id] = error
        del state["tries"][osf_id]
    return "failed"


def check_one(item, state, index, papers_dir, site_dir):
    # returns "done", "skipped", or "failed"
    osf_id = item["id"]
    try:
        rec = get(f"{OSF}/preprints/{osf_id}/")["data"]
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            state["skipped"][osf_id] = "not on the OSF"
            return "skipped"
        raise
    a = rec["attributes"]
    if a.get("date_withdrawn"):
        state["skipped"][osf_id] = "withdrawn"
        return "skipped"
    redo = item["source"] == "redo"         # --redo: this version, whatever else is there
    if not a.get("is_latest_version") and not redo:
        state["skipped"][osf_id] = "not the newest version"
        return "skipped"
    base, version = split_id(osf_id)
    if reported(index, osf_id) and not redo:
        return "skipped"

    finfo = get(rec["relationships"]["primary_file"]["links"]["related"]["href"])["data"]
    name = finfo["attributes"]["name"]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in FILE_TYPES:
        state["skipped"][osf_id] = f"file type .{ext}" if ext else "file without a type"
        return "skipped"
    if (finfo["attributes"].get("size") or 0) > MAX_BYTES:
        state["skipped"][osf_id] = "file larger than 50 MB"
        return "skipped"
    data = get(finfo["links"]["download"], raw=True)

    print(f"{osf_id}: sending {name} ({len(data) // 1024} KB)", flush=True)
    result, error = run_job(name, data, FILE_TYPES[ext])
    if item["source"] == "older" and osf_id not in state["tries"]:
        state["backfill_sent"] += 1
    if error:
        return fail(state, osf_id, error)
    state["tries"].pop(osf_id, None)
    keys = {}
    result = remove_keys(result, keys)
    if keys:
        print(f"{osf_id}: removed {sum(keys.values())} key(s) from the result: {keys}", flush=True)

    # the report page goes in its own file; the server renders it as the
    # metacheck site does, and leaves it empty when it could not render it
    html = result.pop("report_html", "") or ""
    if html:
        save_page(html, site_dir, osf_id, result.get("paper"))
    modules = result.get("modules", {})
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    preprint = {
        "id": base, "version": version, "osf_id": osf_id,
        "url": rec["links"].get("html"), "doi": rec["links"].get("preprint_doi"),
        "article_doi": a.get("doi"), "title": a.get("title"),
        "authors": authors_of(osf_id), "published": a.get("date_published"), "file": name,
    }
    paper = {
        "preprint": preprint,
        "checked": now,
        "metacheck_version": result.get("metacheck_version"),
        "converter": result.get("converter"),
        "run_code": True,
        "modules_run": list(modules),
        "errors": [{"module": k, "report": m.get("report")}
                   for k, m in modules.items() if m.get("traffic_light") == "fail"],
        "report_page": bool(html),
        "keys_removed": keys,      # keys found in the result and replaced, by type
        "paper_info": result.get("paper_info"),
        "modules": modules,
    }
    # anything else the server returned is kept as well
    paper.update({k: v for k, v in result.items() if k not in paper})
    save(os.path.join(papers_dir, osf_id + ".json"), paper)
    index[osf_id] = {"id": osf_id, "base_id": base, "version": version,
                     "title": preprint["title"], "authors": preprint["authors"],
                     "published": preprint["published"], "url": preprint["url"],
                     "checked": now, "report_page": bool(html),
                     "lights": {k: m.get("traffic_light") for k, m in modules.items()}}
    print(f"{osf_id}: saved", flush=True)
    return "done"


# ── The page of examples per check (modules/index.html) ──────────────────────
# The website does not have the full results (data/papers/, see pages.yml), so
# for each check a small file in data/modules/ holds its findings in every
# preprint. After a preprint is checked only its entry is renewed; the file is
# made again from all results when it is missing or MODULE_FORMAT changed.
MODULE_FORMAT = 2
MAX_SENTENCE = 400      # characters; a longer sentence is shortened around the test

# a sentence ends at . ! or ? followed by a capital, with or without a space
# (the converter sometimes joins two paragraphs: "participants.In Experiment"),
# but not after a single capital, as in "J. Smith"
SENTENCE_END = re.compile(r"(?<![A-Z])(?<=[.!?])\s*(?=[A-Z])")


def sentence_around(text, part):
    # the sentence of text that holds part (the reported test)
    text = re.sub(r"\s+", " ", text or "").strip()
    i = text.find(part)
    if i < 0:
        return text[:MAX_SENTENCE]
    start = 0
    for m in SENTENCE_END.finditer(text, 0, i):
        start = m.end()
    m = SENTENCE_END.search(text, i + len(part))
    s = text[start:m.start() if m else len(text)].strip()
    if len(s) > MAX_SENTENCE:
        j = s.find(part)
        a = max(0, j - (MAX_SENTENCE - len(part)) // 2)
        b = min(len(s), a + MAX_SENTENCE)
        s = ("…" if a else "") + s[a:b].strip() + ("…" if b < len(s) else "")
    return s


# Each check's function returns what the page shows of one preprint (at least
# "findings"), or None when there is nothing to show.

def stat_check_findings(result):
    # the p-values that differ from the p-value computed from the test
    # statistic and its degrees of freedom; decision_error: the difference
    # changes whether the result is significant
    out = []
    for r in (result.get("modules", {}).get("stat_check", {}).get("table") or []):
        if not r.get("error") or not r.get("raw"):
            continue
        out.append({"test": r["raw"],
                    "sentence": sentence_around(r.get("text"), r["raw"]),
                    "reported_p": r.get("reported_p"), "p_comp": r.get("p_comp"),
                    "computed_p": r.get("computed_p"),
                    "decision_error": bool(r.get("decision_error")),
                    "one_tailed_in_text": bool(r.get("one_tailed_in_txt")),
                    "section": r.get("header")})
    return {"findings": out} if out else None


# The reproducibility check: the outcomes of a script that ran through, or that
# another script ran (metacheck's .repro_error_message()); any other outcome is
# a script that did not run through.
RAN_THROUGH = {"ran_ok", "run_by_source", "run_by_import", "jags_model", "not_r_content",
               "defines_functions", "not_analysis"}
# the reason for an outcome, for results made before metacheck gave `reason`
# for every outcome (metacheck's .repro_failure_reason())
OUTCOME_REASON = {"timed_out": "time", "skipped_time_limit": "time", "needs_internet": "internet",
                  "dependency_unavailable": "package", "not_parsed": "syntax", "python2": "syntax",
                  "needs_a_person": "interactive", "out_of_memory": "environment",
                  "docker_failed": "environment", "download_too_large": "download",
                  "not_downloaded": "download", "skipped_missing_inputs": "file"}
MAX_MESSAGE = 300       # characters, as metacheck's error_message
OUTPUT_BLOCK = re.compile(r'::: \{\.callout-tip title="Output — (.*) \(([a-z_0-9]+)\)"')
STDERR = re.compile(r"\*\*Messages / errors \(stderr\):\*\*\s*````\n(.*?)\n````", re.S)


def shorten(s, n=MAX_MESSAGE):
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def error_line(stderr, python=False):
    # the error line of a script's output, as metacheck's .repro_error_line():
    # R: from the first line starting with "Error" to before "Calls:" and the
    # like; Python: the last line naming an Error or Exception
    lines = [l.strip() for l in (stderr or "").splitlines() if l.strip()]
    if python:
        hit = [l for l in lines if re.match(r"[A-Za-z_.]*(Error|Exception)\b", l)]
        return shorten(hit[-1]) if hit else ""
    start = next((i for i, l in enumerate(lines) if re.match(r"Error\b", l)), None)
    if start is None:
        return ""
    end = next((i for i in range(start + 1, len(lines)) if re.match(
        r"(Calls:|Backtrace:|In addition:|Execution halted|Run `rlang::last_trace|Warning message)",
        lines[i])), min(len(lines), start + 6))
    return shorten(" ".join(lines[start:end]))


def report_messages(report):
    # file name -> the error message of each script in the report text, for
    # results made before metacheck kept it in its table (version 0.4.3.19)
    out = {}
    for block in report or []:
        m = OUTPUT_BLOCK.search(block) if isinstance(block, str) else None
        if not m or m.group(1) in out:
            continue
        err = STDERR.search(block)
        err = err.group(1) if err else ""
        line = error_line(err) or error_line(err, python=True)
        if not line:
            rest = [l.strip() for l in err.splitlines() if l.strip()
                    and not re.match(r"(Execution halted|Calls:|Backtrace:)", l.strip())]
            line = shorten(rest[-1]) if rest else ""
        out[m.group(1)] = line or None
    return out


def reproducibility_findings(result):
    # the scripts that did not run through, each with why
    m = result.get("modules", {}).get("reproducibility_check", {})
    rows = [r for r in (m.get("table") or []) if r.get("outcome")]
    failed = [r for r in rows if r["outcome"] not in RAN_THROUGH]
    if not failed:
        return None
    old = None
    out = []
    for r in failed:
        reason = r.get("reason") or OUTCOME_REASON.get(r["outcome"], "other")
        if "error_message" in r:
            msg = r["error_message"]
        elif reason == "time":
            # metacheck gives the time limit here; the output of a script that
            # was stopped ends anywhere ("Start sampling"), so nothing
            msg = None
        else:
            if old is None:
                old = report_messages(m.get("report"))
            msg = old.get(r.get("file_name"))
        out.append({"file": r.get("file_name"), "outcome": r["outcome"], "reason": reason,
                    "message": msg or None,
                    "missing_files": r.get("unresolved_inputs") or None})
    return {"findings": out, "scripts": len(rows)}


# The other checks: every preprint where the check gave red, yellow or "info",
# with the check's own summary; for checks that flag sentences or cited
# references, also those (each check's function below gives them).
SHOWN_LIGHTS = ("red", "yellow", "info")
POWER_PARTS = {"statistical_test": "the statistical test", "sample_size": "the sample size",
               "alpha_level": "the alpha level", "power": "the power",
               "effect_size": "the effect size", "effect_size_metric": "the effect size metric",
               "software": "the software"}


def true(x):
    return x is True or str(x).lower() == "true"


def table_of(result, module):
    t = result.get("modules", {}).get(module, {}).get("table")
    return t if isinstance(t, list) else []


def p_exact_rows(result):
    # p-values reported imprecisely ("p < .05") or as zero ("p = .000")
    return [{"sentence": r.get("expanded") or r.get("text"), "mark": r.get("text"),
             "note": "reported as zero" if true(r.get("zero")) else "imprecise"}
            for r in table_of(result, "stat_p_exact") if true(r.get("imprecise")) or true(r.get("zero"))]


def marginal_rows(result):
    return [{"sentence": r.get("text")} for r in table_of(result, "marginal") if r.get("text")]


def power_rows(result):
    # power analyses that miss parts, with the parts missing
    out = []
    for r in table_of(result, "power"):
        if true(r.get("complete")):
            continue
        missing = [name for k, name in POWER_PARTS.items() if r.get(k) in (None, "", "NA")]
        out.append({"sentence": shorten(r.get("text") or "", 600) or None,
                    "note": "Not found: " + ", ".join(missing) + "." if missing else None})
    return out


def effect_size_rows(result):
    # tests without an effect size, or with one that does not fit the test
    out = []
    for r in table_of(result, "stat_effect_size"):
        if r.get("es") in (None, ""):
            note = "No effect size reported with this test."
        elif "no_match" in (r.get("d_coherence"), r.get("eta_coherence")):
            note = (f"The effect size {r['es']} does not fit the test. "
                    + (r.get("d_coherence_note") or r.get("eta_coherence_note") or ""))
        else:
            continue
        out.append({"sentence": r.get("text"), "mark": r.get("test_text"), "note": note.strip()})
    return out


def pubpeer_rows(result):
    out = []
    for r in table_of(result, "ref_pubpeer"):
        n = r.get("total_comments")
        out.append({"reference": r.get("text"), "link": r.get("url"),
                    "note": f"{n} comment{'' if str(n) == '1' else 's'} on PubPeer"
                            + (f" (by {r['users']})" if r.get("users") else "")})
    return out


def retraction_rows(result):
    return [{"reference": r.get("text"), "note": f"In the RetractionWatch database: {r.get('retractionwatch')}"}
            for r in table_of(result, "ref_retraction")]


def replication_rows(result):
    out = []
    for r in table_of(result, "ref_replication"):
        doi = r.get("replication_doi")
        out.append({"reference": r.get("text"),
                    "link": f"https://doi.org/{doi}" if doi else r.get("replication_url"),
                    "note": f"{(r.get('replication_type') or 'replication').capitalize()}, "
                            f"outcome: {r.get('replication_outcome') or 'not given'}. "
                            f"{r.get('replication_ref') or ''}".strip()})
    return out


# The data check's problems per file and column: from its `findings` (one row
# per problem; kept in the result since the SURF server's change of November
# 2026), else from the "Issues Identified" table in its report text, which
# holds the same as R code: structure(list(File = c(...), Column = c(...),
# Issues = c(...)), ...), each issue "<span title='detail'>icon label — detail</span>".
R_TOKEN = re.compile(r'\s*(?:"((?:[^"\\]|\\.)*)"|`([^`]*)`|([A-Za-z_.][A-Za-z0-9_.]*)|'
                     r'(-?[0-9.]+L?)|([(),=]))', re.S)
R_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "'": "'", "\\": "\\"}


def r_string(s):
    # an R string literal's content, as deparse() writes it
    return re.sub(r"\\(u\{?([0-9A-Fa-f]{1,8})\}?|.)",
                  lambda m: chr(int(m.group(2), 16)) if m.group(2) else R_ESCAPES.get(m.group(1), m.group(1)), s)


def r_table(code):
    # the columns of the data frame that deparse() wrote in code, as
    # {name: [values]}; None when there is none
    i = code.find("structure(list(")
    if i < 0:
        return None
    toks, pos = [], i + len("structure(list(")
    depth = 1
    while depth and pos < len(code):
        m = R_TOKEN.match(code, pos)
        if not m:
            return None
        pos = m.end()
        s, bq, name, num, p = m.groups()
        if p == "(":
            depth += 1
        elif p == ")":
            depth -= 1
        toks.append(("s", r_string(s)) if s is not None else ("n", bq or name) if (bq or name)
                    else ("v", num) if num else ("p", p))
    cols, k = {}, 0
    while k < len(toks) - 2:
        if toks[k][0] in ("n", "s") and toks[k + 1] == ("p", "="):
            name, k = toks[k][1], k + 2
            if toks[k] == ("n", "c") and toks[k + 1] == ("p", "("):
                vals, k = [], k + 2
                while toks[k] != ("p", ")"):
                    if toks[k][0] != "p":
                        vals.append(None if toks[k] == ("n", "NA") else toks[k][1])
                    k += 1
            else:
                vals = [None if toks[k] == ("n", "NA") else toks[k][1]]
            cols[name] = vals
        k += 1
    return cols


ISSUE_SPAN = re.compile(r"<span title='([^']*)'>(.*?)</span>", re.S)


def report_data_issues(report):
    out = []
    blocks = [b for b in (report or []) if isinstance(b, str)]
    for i, b in enumerate(blocks):
        if not b.strip().startswith("#### Issues Identified"):
            continue
        code = next((x for x in blocks[i + 1:i + 4] if "structure(list(" in x), None)
        cols = r_table(code) if code else None
        if not cols or "Issues" not in cols:
            continue
        n = len(cols["Issues"])
        files, columns = cols.get("File", [None] * n), cols.get("Column", [None] * n)
        for f, c, cell in zip(files, columns, cols["Issues"]):
            for detail, shown in ISSUE_SPAN.findall(cell or ""):
                shown = html_unescape(re.sub(r"<[^>]+>", "", shown)).strip()
                label = re.sub(r"^[^A-Za-z]+", "", shown.split(" — ")[0]).strip()
                out.append({"file": f, "column": c, "label": label,
                            "detail": html_unescape(detail).strip()})
        break
    return out


def data_rows(result):
    # each detail at most MAX_MESSAGE characters: some quote long text values
    # from the data (one preprint's took 1 KB per problem)
    m = result.get("modules", {}).get("data_check", {})
    rows = m.get("findings")
    if isinstance(rows, list):
        rows = [{"file": r.get("source_file"), "column": r.get("column"),
                 "label": r.get("label") or r.get("check"), "detail": r.get("detail") or ""} for r in rows]
    else:
        rows = report_data_issues(m.get("report"))
    for r in rows:
        r["detail"] = shorten(r["detail"])
    return rows


def summary_findings(module, rows=None):
    # the function for one check: its traffic light and summary, and the rows
    # rows() gives, for a preprint where the check gave red, yellow or "info"
    def findings(result):
        m = result.get("modules", {}).get(module, {})
        if m.get("traffic_light") not in SHOWN_LIGHTS:
            return None
        return {"light": m.get("traffic_light"), "summary": (m.get("summary_text") or "").strip(),
                "findings": rows(result) if rows else []}
    return findings


# every check, in the order of the report
MODULE_FINDINGS = {
    "ethics_check": summary_findings("ethics_check"),
    "power": summary_findings("power", power_rows),
    "prereg_check": summary_findings("prereg_check"),
    "marginal": summary_findings("marginal", marginal_rows),
    "stat_check": stat_check_findings,
    "stat_p_exact": summary_findings("stat_p_exact", p_exact_rows),
    "stat_p_nonsig": summary_findings("stat_p_nonsig"),
    "stat_effect_size": summary_findings("stat_effect_size", effect_size_rows),
    "codebook_check": summary_findings("codebook_check"),
    "repo_check": summary_findings("repo_check"),
    "code_check": summary_findings("code_check"),
    "data_check": summary_findings("data_check", data_rows),
    "reproducibility_check": reproducibility_findings,
    "ref_pubpeer": summary_findings("ref_pubpeer", pubpeer_rows),
    "ref_retraction": summary_findings("ref_retraction", retraction_rows),
    "ref_replication": summary_findings("ref_replication", replication_rows),
}


def update_module_lists(data_dir, index, osf_ids=()):
    # renews the entries of osf_ids in data/modules/<module>.json, and adds the
    # preprints of the index the file has not looked at yet (such as those an
    # older version of this script checked); makes the whole file again from
    # all results when it is missing or out of date. "looked_at": every
    # preprint looked at, also those without findings.
    os.makedirs(os.path.join(data_dir, "modules"), exist_ok=True)
    for module, findings in MODULE_FINDINGS.items():
        path = os.path.join(data_dir, "modules", module + ".json")
        old = load(path, None)
        if old is None or old.get("format") != MODULE_FORMAT:
            papers, todo = {}, list(index)
        else:
            seen = set(old.get("looked_at", []))
            papers = {p["id"]: p for p in old["papers"]}
            todo = list(dict.fromkeys(list(osf_ids) + [i for i in index if i not in seen]))
        for osf_id in todo:
            result = load(os.path.join(data_dir, "papers", osf_id + ".json"), None)
            found = findings(result) if result and osf_id in index else None
            if not found:
                papers.pop(osf_id, None)
                continue
            line = index[osf_id]
            papers[osf_id] = {"id": osf_id, "title": line["title"], "url": line["url"],
                              "published": line["published"], "report_page": line["report_page"],
                              **found}
        papers = [p for p in papers.values() if p["id"] in index]
        papers.sort(key=lambda p: p["published"] or "", reverse=True)
        looked_at = sorted(index)
        if (old is None or old.get("format") != MODULE_FORMAT or papers != old["papers"]
                or looked_at != old.get("looked_at")):
            save(path, {"format": MODULE_FORMAT, "module": module, "looked_at": looked_at,
                        "papers": papers})


def write_index_and_tally(data_dir, index, checked=()):
    papers = sorted(index.values(), key=lambda p: p["published"] or "", reverse=True)
    save(os.path.join(data_dir, "index.json"), {"papers": papers})
    update_module_lists(data_dir, index, checked)
    total = get(LIST.replace("page[size]=100", "page[size]=1"))["links"]["meta"]["total"]
    save(os.path.join(data_dir, "tally.json"), {
        "preprints": total,       # every version the OSF lists counts once
        "reports": len(index),    # every version checked counts once
        "updated": dt.date.today().isoformat(),
    })


# --push (the workflow): each preprint's files are committed and pushed to
# GitHub as soon as it is checked, so a preprint whose files GitHub refuses
# costs only itself, and the reports already made are kept when a run fails.
# Runs in the repository's top folder.
def git(*args, check=True):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and r.returncode:
        raise NotStored(f"git {args[0]}: {(r.stderr or r.stdout).strip()[-500:]}")
    return r


def stage():
    # True when there is something to commit
    git("add", "-A", "data")
    git("add", "-A", "--", "*_v*/index.html")
    return git("diff", "--cached", "--quiet", check=False).returncode != 0


def push():
    # None when the commit is on GitHub; GitHub's message when it refused the
    # files themselves: a key in them (push protection, GH009 or GH013) or a
    # file over 100 MB (GH001). Raises NotStored otherwise.
    msg = ""
    for attempt in range(3):
        r = git("pull", "--rebase", "--autostash", "origin", "main", check=False)
        if r.returncode:
            git("rebase", "--abort", check=False)
            msg = (r.stderr or r.stdout).strip()
        else:
            r = git("push", "origin", "HEAD:main", check=False)
            if r.returncode == 0:
                return None
            msg = r.stderr.strip()
            if "GH001" in msg or ("secret" in msg.lower() and ("GH009" in msg or "GH013" in msg)):
                return msg
        time.sleep(30)
    raise NotStored(msg[-500:])


def store(osf_id, state, index, state_path, index_path):
    # commits and pushes what the check of osf_id changed. When GitHub refuses
    # the files, that commit is dropped (the files go back to how they were
    # before this preprint, so state and index are read again) and the
    # preprint is listed as failed, so it is not sent again.
    if not stage():
        return
    git("commit", "-q", "-m", f"Add the report on {osf_id}")
    refused = push()
    if refused is None:
        return
    reason = ("a file over 100 MB" if "GH001" in refused
              else "a key GitHub recognises (its push protection)")
    print(f"{osf_id}: GitHub refused to store the result ({reason}); left out:\n{refused[-1500:]}", flush=True)
    git("reset", "-q", "--hard", "HEAD~1")
    state.clear()
    state.update(load(state_path, {}))
    index.clear()
    index.update({p["id"]: p for p in load(index_path, {"papers": []})["papers"]})
    state["queue"] = [q for q in state["queue"] if q["id"] != osf_id]
    state["tries"].pop(osf_id, None)
    state["failed"][osf_id] = f"GitHub refused to store the result: {reason}"
    save(state_path, state)
    if stage():
        git("commit", "-q", "-m", f"{osf_id}: GitHub refused to store its result")
        if push() is not None:
            raise NotStored("GitHub refused the commit that lists the refused preprint")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=50,
                        help="start no new preprint after this many minutes")
    parser.add_argument("--max", type=int, default=0, help="send at most this many (0: no limit)")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--site-dir", default=".", help="where the report pages go (with fonts/ and images/)")
    parser.add_argument("--redo", nargs="+", default=[], metavar="ID",
                        help="check these preprint versions again, first, overwriting their files")
    parser.add_argument("--push", action="store_true",
                        help="commit and push each preprint's files as soon as it is checked "
                             "(the workflow; run from the repository's top folder)")
    args = parser.parse_args()

    papers_dir = os.path.join(args.data_dir, "papers")
    os.makedirs(papers_dir, exist_ok=True)
    state_path = os.path.join(args.data_dir, "state.json")
    state = load(state_path, {"newest": None, "backfill_day": None, "backfill_sent": 0,
                              "queue": [], "tries": {}, "skipped": {}, "failed": {}})
    index = {p["id"]: p for p in load(os.path.join(args.data_dir, "index.json"), {"papers": []})["papers"]}

    stop_at = time.time() + args.minutes * 60
    n = refresh_pages(args.site_dir, args.data_dir)
    if n:
        print(f"Brought {n} report pages up to date with this script's changes.")
    global CURRENT_JOB
    CURRENT_JOB = os.path.join(args.data_dir, "current_job.json")
    sent = 0
    changed = False
    said = None          # the last waiting message printed, so it is printed once
    # --redo: these go first; their index lines are set aside so they count as
    # not yet checked, and come back if their new check does not succeed
    held = {}
    for osf_id in reversed(args.redo):
        if osf_id in index:
            held[osf_id] = index.pop(osf_id)
        state["skipped"].pop(osf_id, None)
        state["failed"].pop(osf_id, None)
        state["queue"] = [q for q in state["queue"] if q["id"] != osf_id]
        state["queue"].insert(0, {"id": osf_id, "published": None, "source": "redo"})
    try:
        while time.time() < stop_at and (args.max == 0 or sent < args.max):
            try:
                list_new(state, index)
                older = (not state["queue"] and state["backfill_sent"] < BACKFILL_LIMIT
                         and list_older_day(state, index))
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
                # the OSF did not answer as expected: try again in 5 minutes
                print("The OSF could not be read; trying again in 5 minutes:", e, flush=True)
                if not pause(stop_at, 300):
                    break
                continue
            if older:
                save(state_path, state)
                continue
            if not state["queue"]:
                # nothing waiting: look for new preprints again in 10 minutes
                # (a test run with --max stops here)
                if args.max:
                    print("Nothing waiting.")
                    break
                if said != "nothing":
                    print("Nothing waiting; looking for new preprints every 10 minutes.", flush=True)
                    said = "nothing"
                if not pause(stop_at, 600):
                    break
                continue
            # one preprint at a time, and only when the server is otherwise
            # idle: nothing running or waiting there, ours or anyone's
            if not server_idle():
                if said != "busy":
                    print("The server is busy or cannot be reached; waiting until it is idle.", flush=True)
                    said = "busy"
                if not pause(stop_at, 60):
                    break
                continue
            said = None
            item = state["queue"][0]
            try:
                outcome = check_one(item, state, index, papers_dir, args.site_dir)
            except ServerDown:
                raise
            except (urllib.error.URLError, TimeoutError, KeyError, TypeError, ValueError) as e:
                # an OSF answer that could not be read: tried again later
                outcome = fail(state, item["id"], f"{type(e).__name__}: {e}")
            state["queue"].pop(0)
            if outcome == "failed" and item["id"] in state["tries"]:
                state["queue"].append(item)        # try again after the others
            if outcome != "skipped":
                sent += 1
            if outcome == "done":
                changed = True
                # with the --redo lines not yet checked again, so none is lost
                write_index_and_tally(args.data_dir, {**held, **index}, [item["id"]])
            save(state_path, state)
            if args.push and outcome != "skipped":
                store(item["id"], state, index, state_path, os.path.join(args.data_dir, "index.json"))
    except ServerDown as e:
        print("The server could not be reached; stopping until the next run:", e)
    except NotStored as e:
        print("The results could not be stored on GitHub; stopping:", e)
    for osf_id, line in held.items():       # --redo checks that did not succeed
        index.setdefault(osf_id, line)
    if held:
        write_index_and_tally(args.data_dir, index)
    save(state_path, state)
    if not changed and not os.path.exists(os.path.join(args.data_dir, "tally.json")):
        write_index_and_tally(args.data_dir, index)
    print(f"Sent {sent}; {len(index)} reports; {len(state['queue'])} waiting.")


if __name__ == "__main__":
    sys.exit(main())
