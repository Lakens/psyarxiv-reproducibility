# Checks a few preprint versions again, next to the hourly run: each one is
# sent as soon as the server has a free place (it has two), instead of waiting
# until the server is idle as update.py does, so the hourly run keeps the
# other place. For example after one of the server's keys was refused: the
# new key can be sent with these jobs only, before the server itself has it.
#
#   python scripts/redo.py 5snc8_v4 7eaw6_v1
#   python scripts/redo.py 5snc8_v4 --key researchbox=RESEARCHBOX_API_KEY \
#       --renviron "C:/Users/.../Documents/.Renviron"
#           (sends that key with each job; the server uses it for that job only)
#   python scripts/redo.py 5snc8_v4 7eaw6_v1 --no-check
#           (only writes index.json, tally.json and modules/ again from the
#           saved results, for example after a git conflict in those files)
#
# A preprint whose new check fails keeps its old files. Nothing is committed:
# commit the changed files in data/ and the report pages afterwards (pull
# first; the hourly run pushes often).

import argparse
import os
import sys
import tempfile
import time
import urllib.error

import update
from update import SERVER, get, load


def read_renviron(path):
    # NAME=value lines; quotes around a value are removed
    values = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def free_place():
    # True when the server answers, does not hold new jobs back (an update
    # drains it), and has a place without a job running or waiting
    try:
        h = get(f"{SERVER}/health", tries=1)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False
    busy = (h.get("jobs_running") or 0) + (h.get("jobs_waiting") or 0)
    return h.get("status") == "ok" and not h.get("draining") and busy < (h.get("workers") or 1)


def index_line(paper):
    # the line of index.json for a saved result (as update.check_one makes it)
    p = paper["preprint"]
    return {"id": p["osf_id"], "base_id": p["id"], "version": p["version"],
            "title": p["title"], "authors": p["authors"], "published": p["published"],
            "url": p["url"], "checked": paper["checked"], "report_page": paper["report_page"],
            "lights": {k: m.get("traffic_light") for k, m in paper["modules"].items()}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="+", metavar="ID", help="preprint versions, such as 5snc8_v4")
    parser.add_argument("--key", action="append", default=[], metavar="SERVICE=VARIABLE",
                        help="send this key with each job (github, osf, dryad, researchbox, "
                             "gitlab, openalex), read from the environment or --renviron")
    parser.add_argument("--renviron", help="an .Renviron file to read the keys from")
    parser.add_argument("--no-check", action="store_true",
                        help="only write index.json, tally.json and modules/ again")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--site-dir", default=".")
    args = parser.parse_args()
    papers_dir = os.path.join(args.data_dir, "papers")

    keys = {}
    file_values = read_renviron(args.renviron) if args.renviron else {}
    for k in args.key:
        service, _, variable = k.partition("=")
        value = os.environ.get(variable) or file_values.get(variable)
        if not value:
            sys.exit(f"{variable} is not set (nor in --renviron)")
        keys[f"key_{service}"] = value

    done = []
    if args.no_check:
        done = list(args.ids)
    else:
        # the job this script has on the server is kept apart from the hourly
        # run's (data/current_job.json), which would otherwise wait for it
        update.CURRENT_JOB = os.path.join(tempfile.gettempdir(), "psyarxiv_redo_job.json")
        send = update.post_job
        update.post_job = lambda fields, file=None: send({**fields, **keys}, file=file)
        index = {p["id"]: p for p in load(os.path.join(args.data_dir, "index.json"), {"papers": []})["papers"]}
        state = {"skipped": {}, "tries": {}, "failed": {}, "backfill_sent": 0}
        for osf_id in args.ids:
            said = False
            while not free_place():
                if not said:
                    print("Waiting for a free place on the server ...", flush=True)
                    said = True
                time.sleep(30)
            try:
                outcome = update.check_one({"id": osf_id, "source": "redo"}, state, index,
                                           papers_dir, args.site_dir)
            except update.ServerDown as e:
                print(f"{osf_id}: the server could not be reached; stopping: {e}")
                break
            except (urllib.error.URLError, TimeoutError, KeyError, TypeError, ValueError) as e:
                outcome = "failed"
                print(f"{osf_id}: failed: {type(e).__name__}: {e}")
            if outcome == "skipped":
                print(f"{osf_id}: not checked: {state['skipped'].get(osf_id)}")
            if outcome == "done":
                done.append(osf_id)

    if done:
        # index.json as it is now (it may have been pulled since this started),
        # with the lines of the preprints checked again
        index = {p["id"]: p for p in load(os.path.join(args.data_dir, "index.json"), {"papers": []})["papers"]}
        for osf_id in done:
            index[osf_id] = index_line(load(os.path.join(papers_dir, osf_id + ".json"), None))
        update.write_index_and_tally(args.data_dir, index, done)
    print(f"Checked again: {', '.join(done) or 'none'}")


if __name__ == "__main__":
    sys.exit(main())
