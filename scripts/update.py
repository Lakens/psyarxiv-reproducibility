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
#   state.json        where the run is: the newest preprint listed, the next
#                     older day to list, the preprints waiting, and those
#                     skipped or failed

import argparse
import base64
import datetime as dt
import glob
from html import escape as html_escape
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from test_surf_jobs import post_job, SERVER

OSF = "https://api.osf.io/v2"
LIST = OSF + "/preprints/?filter[provider]=psyarxiv&page[size]=100"
UA = "psyarxiv-reproducibility (github.com/Lakens/psyarxiv-reproducibility)"
# the checks the SURF server runs for its regular report; with run_code=true the
# server adds reproducibility_check, which runs the paper's code in the sandbox
MODULES = ("power,marginal,prereg_check,ethics_check,ref_pubpeer,ref_retraction,"
           "ref_replication,stat_check,stat_p_exact,stat_p_nonsig,stat_effect_size,"
           "repo_check,code_check,data_check,codebook_check")
FILE_TYPES = {"pdf": "application/pdf",
              "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
MAX_BYTES = 50 * 1024 ** 2      # the server refuses larger files (api.R MAX_UPLOAD_BYTES)
JOB_WAIT_MINUTES = 75           # the server stops a paper's code after 60 minutes
MAX_TRIES = 3                   # a preprint whose job fails is tried this often
BACKFILL_LIMIT = 1000           # older preprints sent to the server, at most
FIRST_DAY = dt.date(2016, 9, 1)  # PsyArXiv's first preprints
# files the report page carries inside it that the site has too
SHARED_FILES = {"font/ttf": "fonts/Cabin.ttf", "image/png": "images/logo.png"}


class ServerDown(Exception):
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


def decorate_page(html, paper):
    # this site's changes to the server's report page
    return add_way_back(add_full_text(drop_converter_note(html), paper))


def refresh_pages(site_dir, data_dir):
    # gives every report page this site's changes it does not have yet (such
    # as pages made before a change to this script); returns how many changed
    changed = 0
    for path in glob.glob(os.path.join(site_dir, "*_v*", "index.html")):
        with open(path, encoding="utf-8", newline="") as f:
            html = f.read()
        if 'id="back-to-main"' in html and 'class="logo-home"' in html and 'id="full-text"' in html:
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


def write_index_and_tally(data_dir, index):
    papers = sorted(index.values(), key=lambda p: p["published"] or "", reverse=True)
    save(os.path.join(data_dir, "index.json"), {"papers": papers})
    total = get(LIST.replace("page[size]=100", "page[size]=1"))["links"]["meta"]["total"]
    save(os.path.join(data_dir, "tally.json"), {
        "preprints": total,       # every version the OSF lists counts once
        "reports": len(index),    # every version checked counts once
        "updated": dt.date.today().isoformat(),
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=50,
                        help="start no new preprint after this many minutes")
    parser.add_argument("--max", type=int, default=0, help="send at most this many (0: no limit)")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--site-dir", default=".", help="where the report pages go (with fonts/ and images/)")
    parser.add_argument("--redo", nargs="+", default=[], metavar="ID",
                        help="check these preprint versions again, first, overwriting their files")
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
                write_index_and_tally(args.data_dir, {**held, **index})
            save(state_path, state)
    except ServerDown as e:
        print("The server could not be reached; stopping until the next run:", e)
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
