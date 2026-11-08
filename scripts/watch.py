# Watches the runs that make the reports, and keeps one GitHub issue in this
# repository, "Problems with the runs", up to date: it lists what is wrong
# now, adds a comment for each new problem (GitHub emails the repository's
# owner about it), and closes the issue when nothing is wrong. Run every six
# hours by .github/workflows/watch.yml; uses the gh program for GitHub.
#
#   python scripts/watch.py [--dry-run]   (--dry-run: print, change nothing)
#
# Problems:
#   - stopped: the workflow "Update the reports" is switched off, its last run
#     failed, no run has ended for STOPPED_HOURS, or a run has gone on
#     for longer than its 180 minutes allow
#   - no new report for QUIET_HOURS
#   - a module that failed (traffic light "fail") in a stored report; grouped
#     by module and error message, so one bug is listed once with its papers
#   - a preprint listed as failed in data/state.json (its job failed twice,
#     or GitHub refused its result)
#   - keys removed from a result (the authors may want to know)
# Which problems were already announced is kept in the issue itself, in a
# line the issue page does not show.

import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request

REPO = os.environ.get("GITHUB_REPOSITORY", "Lakens/psyarxiv_metacheck")
SERVER = "https://metacheckserve.metacheck.src.surf-hosted.nl/api"
SITE = "https://lakens.github.io/psyarxiv_metacheck/"
TITLE = "Problems with the runs"
LABEL = "watch"
STOPPED_HOURS = 3
QUIET_HOURS = 24
LONG_RUN_HOURS = 4          # update.yml stops a run after 180 minutes
MARK = re.compile(r"<!-- watch-state (.*?) -->", re.S)


def gh(*args, data=None):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, input=data)
    if r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {r.stderr.strip()}")
    return r.stdout


def api(path):
    return json.loads(gh("api", f"repos/{REPO}/{path}"))


def when(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def ago(t, now):
    h = (now - t).total_seconds() / 3600
    return f"{h:.0f} hours ago" if h >= 2 else f"{h * 60:.0f} minutes ago"


def short(t):
    return t.strftime("%Y-%m-%d %H:%M UTC")


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def server():
    try:
        req = urllib.request.Request(f"{SERVER}/health", headers={"User-Agent": "psyarxiv_metacheck watch"})
        with urllib.request.urlopen(req, timeout=30) as r:
            h = json.load(r)
        return (f"the server answers (Metacheck {h.get('metacheck_version')}; "
                f"{h.get('jobs_running')} running, {h.get('jobs_waiting')} waiting)")
    except Exception as e:
        return f"**the server does not answer** ({type(e).__name__})"


def run_problems(now):
    # [(id, text)] about the update runs, and a line on how they stand
    out = []
    wf = api("actions/workflows/update.yml")
    if wf["state"] != "active":
        out.append(("switched-off", f'The workflow "Update the reports" is switched off ({wf["state"]}), '
                    f'so no run starts. Switch it on in the Actions tab ("..." menu, "Enable workflow").'))
    runs = api("actions/workflows/update.yml/runs?per_page=10")["workflow_runs"]
    going = [r for r in runs if r["status"] in ("in_progress", "queued", "waiting")]
    done = [r for r in runs if r["status"] == "completed"]
    for r in going:
        if now - when(r["run_started_at"]) > dt.timedelta(hours=LONG_RUN_HOURS):
            out.append((f"long-run:{r['id']}", f"[A run]({r['html_url']}) has been going since "
                        f"{short(when(r['run_started_at']))}, longer than its 180 minutes allow."))
    last = done[0] if done else None
    if last and last["conclusion"] not in ("success", "cancelled", "skipped"):
        out.append((f"run-failed:{last['id']}", f"[The last run]({last['html_url']}), which ended "
                    f"{short(when(last['updated_at']))}, ended with \"{last['conclusion']}\". "
                    "A failed run does not start the next one; GitHub's hourly timetable may restart them."))
    if not going and last and now - when(last["updated_at"]) > dt.timedelta(hours=STOPPED_HOURS):
        out.append((f"no-run:{last['id']}", f"No run is going, and the last one ended "
                    f"{ago(when(last['updated_at']), now)} ({short(when(last['updated_at']))})."))
    if going:
        status = f"a run is going (since {short(when(going[0]['run_started_at']))})"
    elif last:
        status = f"no run is going; the last ended {ago(when(last['updated_at']), now)}, with \"{last['conclusion']}\""
    else:
        status = "no run has been made yet"
    return out, status


def error_kind(msg):
    # the error message without what differs from paper to paper (quoted
    # text, numbers, file names), so one bug gives one group
    msg = re.sub(r"\s+", " ", msg or "the module failed").strip()
    msg = re.sub(r"(['\"`]).*?\1", "'…'", msg)
    msg = re.sub(r"\d+(?:\.\d+)?", "N", msg)
    return msg[:300]


def code(text):
    # text shown as code in the issue, on one line
    text = re.sub(r"\s+", " ", text).replace("`", "'")
    return f"`{text}`"


def module_failures(data_dir):
    # {(module, kind): {"papers": [...], "versions": set, "example": message}}
    index = load(os.path.join(data_dir, "index.json"), {"papers": []})["papers"]
    groups = {}
    for p in index:
        failed = [k for k, light in (p.get("lights") or {}).items() if light == "fail"]
        if not failed:
            continue
        rec = load(os.path.join(data_dir, "papers", p["id"] + ".json"), {})
        reports = {e.get("module"): e.get("report") for e in rec.get("errors") or []}
        for mod in failed:
            msg = reports.get(mod) or (rec.get("modules", {}).get(mod) or {}).get("report") or ""
            g = groups.setdefault((mod, error_kind(msg)), {"papers": [], "versions": set(), "example": msg})
            g["papers"].append(p["id"])
            g["versions"].add(rec.get("metacheck_version") or "?")
    return groups


def keys_removed(data_dir):
    out = {}
    for path in glob.glob(os.path.join(data_dir, "papers", "*.json")):
        with open(path, encoding="utf-8") as f:
            head = f.read(200000)         # keys_removed stands near the top
        m = re.search(r'"keys_removed": (\{[^}]*\})', head)
        if m and m.group(1) != "{}":
            out[os.path.basename(path)[:-5]] = json.loads(m.group(1))
    return out


def report(data_dir, now):
    # (problems [(id, text)], the issue's text)
    problems, status = run_problems(now)
    index = load(os.path.join(data_dir, "index.json"), {"papers": []})["papers"]
    state = load(os.path.join(data_dir, "state.json"), {})
    last = max((when(p["checked"]) for p in index if p.get("checked")), default=None)
    srv = server()
    waiting = len(state.get("queue", []))
    if last and now - last > dt.timedelta(hours=QUIET_HOURS):
        problems.append((f"quiet:{last.isoformat()}", f"No new report for {ago(last, now)} (the last was made "
                         f"{short(last)}). {waiting} preprints are waiting; {srv}."))
    groups = module_failures(data_dir)
    for (mod, kind), g in sorted(groups.items()):
        papers = ", ".join(f"[{x}]({SITE}{x}/)" for x in g["papers"][:10]) + (" …" if len(g["papers"]) > 10 else "")
        problems.append((f"module:{mod}:{kind}", f"Module `{mod}` failed in {len(g['papers'])} report(s) "
                         f"(Metacheck {', '.join(sorted(g['versions']))}): {papers}. "
                         f"Error: {code(g['example'][:500])}"))
    for osf_id, why in sorted((state.get("failed") or {}).items()):
        problems.append((f"failed:{osf_id}", f"Preprint [{osf_id}](https://osf.io/preprints/psyarxiv/{osf_id}) "
                         f"failed and is not tried again: {why}"))
    for osf_id, keys in sorted(keys_removed(data_dir).items()):
        problems.append((f"keys:{osf_id}", f"Keys were removed from the result of [{osf_id}]({SITE}{osf_id}/): "
                         f"{keys}. The authors may want to know."))
    tries = state.get("tries") or {}
    lines = [f"Checked {short(now)}. Runs: {status}. {waiting} preprints waiting; {srv}. "
             f"{len(index)} reports; the newest made {short(last) if last else 'never'}.", ""]
    if problems:
        lines += ["**Problems now**", ""] + [f"- {t}" for _, t in problems]
    else:
        lines += ["No problems."]
    if tries:
        lines += ["", "Failed once, to be tried again: " + ", ".join(sorted(tries)) + "."]
    lines += ["", "_Kept up to date by `scripts/watch.py` (workflow \"Watch the runs\"), every six hours._"]
    return problems, "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--dry-run", action="store_true", help="print what would be done; change nothing")
    args = parser.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    problems, text = report(args.data_dir, now)

    found = json.loads(gh("issue", "list", "-R", REPO, "--label", LABEL, "--state", "all",
                          "--limit", "1", "--json", "number,state,body"))
    issue = found[0] if found else None
    m = MARK.search(issue["body"]) if issue else None
    announced = set(json.loads(m.group(1))) if m else set()
    # each problem is remembered by a short fingerprint of its id, which can
    # stand in the hidden line whatever the id contains
    problems = [(hashlib.sha1(i.encode()).hexdigest()[:12], t) for i, t in problems]
    new = [(i, t) for i, t in problems if i not in announced]
    # only the problems of now: one that went away and comes back is new again
    ids = sorted(i for i, _ in problems)
    if len(text) > 60000:                           # GitHub allows 65,536 characters
        text = text[:60000] + "\n\n… (cut short; see scripts/watch.py --dry-run)"
    body = text + f"\n\n<!-- watch-state {json.dumps(ids)} -->\n"

    if args.dry_run:
        print(body)
        print("\nNew problems, each would be a comment:" if new else "\nNo new problems.")
        for _, t in new:
            print("-", t)
        return
    if not problems:
        if issue and issue["state"] == "OPEN":
            gh("issue", "edit", str(issue["number"]), "-R", REPO, "--body-file", "-", data=body)
            gh("issue", "close", str(issue["number"]), "-R", REPO, "--comment", "No problems any more.")
        print("No problems.")
        return
    if not issue:
        try:
            gh("label", "create", LABEL, "-R", REPO, "--description", "Kept by scripts/watch.py", "--color", "B60205")
        except RuntimeError:
            pass                                    # it exists already
        gh("issue", "create", "-R", REPO, "--title", TITLE, "--label", LABEL, "--body-file", "-", data=body)
        print(f"Opened the issue with {len(problems)} problem(s).")
        return
    num = str(issue["number"])
    gh("issue", "edit", num, "-R", REPO, "--body-file", "-", data=body)
    if issue["state"] != "OPEN":
        gh("issue", "reopen", num, "-R", REPO)
    if new:
        gh("issue", "comment", num, "-R", REPO, "--body-file", "-",
           data="New:\n\n" + "\n".join(f"- {t}" for _, t in new))
    print(f"{len(problems)} problem(s), {len(new)} new.")


if __name__ == "__main__":
    sys.exit(main())
