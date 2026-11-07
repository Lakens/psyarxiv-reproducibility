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
    end = time.time() + JOB_WAIT_MINUTES * 60
    while time.time() < end:
        time.sleep(15)
        try:
            status = get(f"{SERVER}/jobs/{job['id']}")
        except (urllib.error.URLError, TimeoutError) as e:
            raise ServerDown(str(e))
        if status.get("status") == "done":
            return get(f"{SERVER}/jobs/{job['id']}/result"), None
        if status.get("status") == "failed":
            return None, status.get("error") or "the job failed"
    return None, f"no result after {JOB_WAIT_MINUTES} minutes"


def save_page(html, site_dir, osf_id):
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
        save_page(html, site_dir, osf_id)
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

    try:
        health = get(f"{SERVER}/health")
    except (urllib.error.URLError, TimeoutError) as e:
        health = {"error": str(e)}
    if health.get("status") != "ok":
        print("The server is not ready; stopping until the next run:", health)
        return
    stop_at = time.time() + args.minutes * 60
    sent = 0
    changed = False
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
            list_new(state, index)
            if not state["queue"]:
                if state["backfill_sent"] >= BACKFILL_LIMIT or not list_older_day(state, index):
                    print("Nothing waiting.")
                    break
                save(state_path, state)
                continue
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
