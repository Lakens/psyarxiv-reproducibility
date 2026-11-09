# Counts everything in the checked preprints, for the page of totals
# (totals/index.html): writes data/totals.json. The full results in
# data/papers/ are not on the website, so this file carries what the page
# shows: one line per preprint with its counts and traffic lights, the lists of
# p values, StatCheck tests and power analyses, and the most frequent
# references, journals, packages, error messages, words and countries.
# GitHub runs it once a day (.github/workflows/totals.yml). Uses only the
# Python standard library.
#
#   python scripts/totals.py [--data-dir data]

import argparse
import collections
import datetime as dt
import json
import math
import os
import re
import urllib.parse
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update import (RAN_THROUGH, OUTCOME_REASON, data_rows, load, reproducibility_findings,  # noqa: E402
                    true)

TOP = 30                # entries in each list of the most frequent
LIGHT_CODE = {"red": "r", "yellow": "y", "green": "g", "info": "i", "na": "n", "fail": "f"}
SECTION_CODE = {"abstract": "a", "intro": "i", "method": "m", "results": "r", "discussion": "d",
                "annex": "x", "figure": "f", "table": "t"}
STOP = set("""a an the of in on for and or to with by from at as is are be its their this that
these those into about over under between among after before during via vs versus do does
can could how why what when who whom which than not no new using use based study studies
evidence effects effect role across toward towards through within we our it it's more less
two one three among them they i you your his her he she s""".split())
COUNTRIES = ["United States", "USA", "U.S.A", "United Kingdom", "UK", "Germany", "Netherlands",
             "The Netherlands", "Canada", "Australia", "France", "Italy", "Spain", "Switzerland",
             "Belgium", "Austria", "Sweden", "Norway", "Denmark", "Finland", "Ireland", "Poland",
             "Czech Republic", "Czechia", "Hungary", "Portugal", "Greece", "Israel", "Turkey",
             "Türkiye", "China", "Japan", "Korea", "Singapore", "India", "Brazil", "Chile",
             "Argentina", "Mexico", "Colombia", "South Africa", "Nigeria", "Kenya", "New Zealand",
             "Iran", "Pakistan", "Indonesia", "Malaysia", "Thailand", "Vietnam", "Taiwan",
             "Hong Kong", "Russia", "Ukraine", "Romania", "Croatia", "Serbia", "Slovenia",
             "Slovakia", "Estonia", "Lithuania", "Latvia", "Iceland", "Luxembourg", "Peru",
             "Ghana", "Ethiopia", "Egypt", "Saudi Arabia", "Qatar", "United Arab Emirates",
             "Lebanon", "Philippines", "Bangladesh", "Uruguay", "Ecuador", "Cyprus", "Malta"]
COUNTRY_NAME = {"USA": "United States", "U.S.A": "United States", "UK": "United Kingdom",
                "The Netherlands": "Netherlands", "Czechia": "Czech Republic",
                "Türkiye": "Turkey"}
COUNTRY_RE = re.compile(r"\b(" + "|".join(re.escape(c) for c in
                                          sorted(COUNTRIES, key=len, reverse=True)) + r")\b")
# the roles of authors (CRediT), which Grobid sometimes takes for keywords
CREDIT = {"conceptualization", "data curation", "formal analysis", "funding acquisition",
          "investigation", "methodology", "project administration", "resources", "software",
          "supervision", "validation", "visualization", "writing - original draft",
          "writing -original draft", "writing - review & editing", "writing -review & editing",
          "writing – original draft", "writing – review & editing"}
# what went wrong in a script, from its error message: the first that matches
MESSAGE_KINDS = [
    ("a file it reads is missing", r"No such file|cannot open|does not exist|FileNotFound|not found in|no lines available"),
    ("a package or module is missing", r"no package called|No module named|ModuleNotFound|there is no package"),
    ("a function is not defined", r"could not find function"),
    ("an object or variable is not defined", r"object '.*' not found|not found$|NameError|undefined"),
    ("it needs arguments on the command line", r"arguments are required|is required \(or"),
    ("a column or index does not exist", r"Column `|columns that don't exist|IndexError|KeyError|subscript"),
    ("it ran out of time", r"timed out"),
    ("the data have another shape than expected", r"ValueError|must specify|no rows|invalid"),
]
PACKAGE_MISSING = [re.compile(r"there is no package called ['‘’\"]?([A-Za-z0-9._]+)"),
                   re.compile(r"No module named ['\"]([A-Za-z0-9_.]+)")]


# Repository websites by their address; a DOI by its prefix
SITES = {"osf.io": "OSF", "github.com": "GitHub", "researchbox.org": "ResearchBox",
         "zenodo.org": "Zenodo", "figshare.com": "Figshare", "gitlab.com": "GitLab",
         "datadryad.org": "Dryad", "psycharchives.org": "PsychArchives",
         "reshare.ukdataservice.ac.uk": "UK Data Service ReShare", "data.4tu.nl": "4TU.ResearchData",
         "data.mendeley.com": "Mendeley Data", "ldbase.org": "LDbase"}
DOI_SITES = {"10.5281": "Zenodo", "10.17605": "OSF", "10.6084": "Figshare", "10.5061": "Dryad",
             "10.7910": "Dataverse", "10.34894": "Dataverse", "10.23668": "PsychArchives",
             "10.4121": "4TU.ResearchData", "10.17632": "Mendeley Data", "10.5255": "UK Data Service ReShare"}


def repo_site(url):
    # the website a repository link goes to, such as "OSF"; None when unknown
    url = urllib.parse.unquote(str(url or "").strip())
    m = re.search(r"safelinks\.protection\.outlook\.com/\?url=([^&]+)", url)
    if m:                                   # a link pasted from an Outlook email
        url = m.group(1)
    m = re.search(r"(?:^|doi\.org/)(10\.\d{4,9})/", url, re.I)
    if m:
        return DOI_SITES.get(m.group(1), "other (DOI " + m.group(1) + ")")
    host = re.sub(r"^www\.", "", re.sub(r"^[a-z]+://", "", url, flags=re.I).split("/")[0].lower())
    if not host:
        return None
    for h, name in SITES.items():
        if host == h or host.endswith("." + h):
            return name
    if "dataverse" in host:
        return "Dataverse"
    return host


def num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def table(result, module):
    t = result.get("modules", {}).get(module, {}).get("table")
    return [r for r in t if isinstance(r, dict)] if isinstance(t, list) else []


def first_info(paper):
    i = (paper or {}).get("info")
    if isinstance(i, list):
        return i[0] if i and isinstance(i[0], dict) else {}
    return i if isinstance(i, dict) else {}


def year_of(s):
    m = re.match(r"(\d{4})", str(s or ""))
    return int(m.group(1)) if m else None


def top(counter, n=TOP):
    return [[k, v] for k, v in counter.most_common(n)]


def r3(x):
    return None if x is None else round(x, 4)


def paper_row(i, item, result, acc):
    # one preprint: its counts and lights; adds its lists to acc
    pre = result.get("preprint") or {}
    paper = result.get("paper") or {}
    mods = result.get("modules") or {}
    published = item.get("published") or pre.get("published")
    pub_year = year_of(published)
    row = {"id": item["id"], "t": item.get("title") or pre.get("title"),
           "pub": published, "chk": item.get("checked") or result.get("checked"),
           "v": item.get("version") or pre.get("version"), "mc": result.get("metacheck_version"),
           "conv": result.get("converter"),
           "L": "".join(LIGHT_CODE.get((mods.get(m) or {}).get("traffic_light"), "n")
                        for m in acc["modules"])}

    # the text Metacheck read
    texts = [t for t in paper.get("text") or [] if isinstance(t, dict)]
    row["words"] = sum(len(str(t.get("text") or "").split()) for t in texts)
    row["paras"] = len({t.get("paragraph_id") for t in texts})
    secs = [s for s in paper.get("section") or [] if isinstance(s, dict)]
    row["secs"] = len(secs)
    for s in secs:
        acc["section_types"][s.get("section_type") or "unknown"] += 1
    row["figs"] = len(paper.get("figure") or [])
    row["tabs"] = len(paper.get("table") or [])
    row["eqs"] = len(paper.get("eq") or [])
    row["urls"] = len(paper.get("url") or [])
    for u in paper.get("url") or []:
        m = re.match(r"https?://(?:www\.)?([^/]+)", str((u or {}).get("href") or ""))
        if m:
            acc["domains"][m.group(1).lower()] += 1

    # title, keywords, authors
    title = row["t"] or ""
    row["tw"] = len(title.split())
    row["tq"] = "?" in title
    row["tc"] = ":" in title
    for w in set(re.findall(r"[a-zà-ÿ][a-zà-ÿ'-]+", title.lower())):
        if w not in STOP and len(w) > 2:
            acc["title_words"][w] += 1
    for k in first_info(paper).get("keywords") or []:
        # Grobid sometimes takes authors' initials for keywords
        k = k.strip().lower() if isinstance(k, str) else ""
        if 3 < len(k) < 60 and not re.search(r"\b[a-z]\.", k) and k not in CREDIT and not k.startswith("writing"):
            acc["keywords"][k] += 1
    names = item.get("authors") or pre.get("authors") or []
    row["auth"] = len(names)
    base = item.get("base_id") or item["id"].split("_v")[0]
    for a in names:
        acc["authors"][a].add(base)
    people = [a for a in paper.get("author") or [] if isinstance(a, dict)]
    row["orcid"] = sum(1 for a in people if a.get("orcid"))
    row["email"] = sum(1 for a in people if a.get("email"))
    countries = set()
    for a in people:
        for c in COUNTRY_RE.findall(str(a.get("affiliation") or "")):
            countries.add(COUNTRY_NAME.get(c, c))
    for c in countries:
        acc["countries"][c] += 1
    row["ctry"] = len(countries)

    # references
    bib = [b for b in paper.get("bib") or [] if isinstance(b, dict)]
    row["refs"] = len(bib)
    row["refdoi"] = sum(1 for b in bib if b.get("doi"))
    ages = []
    for b in bib:
        acc["bib_types"][b.get("bib_type") or "unknown"] += 1
        y = year_of(b.get("year"))
        if y and 1800 <= y <= (pub_year or 2100) + 1:
            acc["ref_years"][y] += 1
            if pub_year:
                ages.append(pub_year - y)
                acc["ref_ages"][max(0, min(pub_year - y, 60))] += 1
        c = (b.get("container") or "").strip()
        if c:
            acc["journals"][c] += 1
        # one work, by its title (one preprint gives the DOI, another does not)
        key = re.sub(r"\W+", " ", (b.get("title") or "").lower()).strip()
        if len(key) < 12:
            key = (b.get("doi") or "").lower().strip()
        if key and len(key) > 12:
            acc["cited"][key].add(base)
            known = acc["cited_info"].get(key)
            if not known or (b.get("doi") and not known["doi"]):
                acc["cited_info"][key] = {"title": b.get("title"), "year": y, "journal": c or None,
                                          "doi": b.get("doi") or None}
    ages.sort()
    row["refage"] = ages[len(ages) // 2] if ages else None
    row["refold"] = ages[-1] if ages else None
    row["refnew"] = sum(1 for a in ages if a <= 2)

    # p values
    pex = table(result, "stat_p_exact")
    row["p"] = len(pex)
    row["pimp"] = sum(1 for r in pex if true(r.get("imprecise")))
    row["plt"] = sum(1 for r in pex if r.get("p_comp") in ("<", "≤"))
    row["peq"] = sum(1 for r in pex if r.get("p_comp") == "=")
    row["pzero"] = sum(1 for r in pex if true(r.get("zero")))
    for r in pex:
        p = num(r.get("p_value"))
        if p is None or p < 0 or p > 1:
            continue
        # the p value as the paper wrote it, for its number of decimals
        # (a number loses its trailing zeros: .050 becomes 0.05)
        m = re.search(r"[<>=≤≥]\s*0?\.(\d+)", str(r.get("text") or ""))
        acc["p"].append([r3(p), r.get("p_comp") or "=", SECTION_CODE.get(r.get("section_type"), "o"),
                         1 if true(r.get("imprecise")) else 0, i, m.group(1) if m else None])
    row["nonsig"] = len(table(result, "stat_p_nonsig"))
    row["marg"] = len(table(result, "marginal"))

    # StatCheck
    sc = table(result, "stat_check")
    row["sc"] = len(sc)
    row["scerr"] = sum(1 for r in sc if true(r.get("error")))
    row["scdec"] = sum(1 for r in sc if true(r.get("decision_error")))
    for r in sc:
        rp, cp = num(r.get("reported_p")), num(r.get("computed_p"))
        if rp is None or cp is None:
            continue
        acc["sc"].append([r3(rp), float("%.3g" % cp), r.get("p_comp") or "=", r.get("test_type"),
                          1 if true(r.get("error")) else 0, 1 if true(r.get("decision_error")) else 0,
                          num(r.get("df1")), num(r.get("df2")), i])

    # effect sizes
    es = table(result, "stat_effect_size")
    row["es_t"] = sum(1 for r in es if r.get("test") == "t-test")
    row["es_f"] = sum(1 for r in es if r.get("test") == "F-test")
    row["es_no"] = sum(1 for r in es if not r.get("es"))
    for r in es:
        for sym in re.findall(r"(?<![A-Za-z])(ηp²|η²p|η²|ω²|dz|d|r|b|β|f|g|OR|R²)\s*=", str(r.get("es") or "")):
            acc["es_symbols"][sym.replace("η²p", "ηp²")] += 1
        d = num(r.get("d_reported"))
        di = num(r.get("d_implied_indep_equal_n"))
        if d is not None and di is not None and abs(d) < 10 and abs(di) < 10:
            # the design under which metacheck finds the reported d fits the
            # test: e equal groups, p paired (d_z), u unequal groups, x none
            fit = {"independent_equal_n": "e", "paired_dz": "p", "paired_drm_r05": "p",
                   "independent_unequal_n_range": "u"}.get(r.get("d_coherence_assumption"), "x")
            acc["d_pairs"].append([round(d, 3), round(di, 3), i, fit])

    # power
    pw = table(result, "power")
    row["pow"] = len(pw)
    for r in pw:
        acc["power"].append([num(r.get("power")), num(r.get("alpha_level")),
                             r.get("effect_size_metric") or None, r.get("software") or None,
                             r.get("power_type") or None, r.get("statistical_test") or None,
                             num(r.get("sample_size")), num(r.get("effect_size")),
                             1 if true(r.get("complete")) else 0, i])

    # preregistration, ethics
    pr = table(result, "prereg_check")
    row["prereg"] = len(pr)
    for r in pr:
        acc["prereg_templates"][r.get("template_name") or "unknown"] += 1
    eth = table(result, "ethics_check")
    row["live"] = sum(1 for r in eth if true(r.get("live_data")))
    row["ethics"] = sum(1 for r in eth if true(r.get("ethics")))

    # the repository
    repo = table(result, "repo_check")
    row["files"] = len(repo)
    row["bytes"] = sum(num(r.get("file_size")) or 0 for r in repo)
    row["repos"] = len({r.get("repo_url") for r in repo if r.get("repo_url")})
    # each repository website once per preprint; also the repositories that
    # could not be read, which only the summary names
    m = mods.get("repo_check") or {}
    urls = {r.get("repo_url") for r in repo if r.get("repo_url")}
    urls |= set(re.findall(r"https?://[^\s;),]+", str(m.get("summary_text") or "")))
    for site in {repo_site(u) for u in urls} - {None}:
        acc["repo_sites"][site].add(base)
    kinds = collections.Counter(r.get("data_type") or "unknown" for r in repo)
    for k in ("data", "code", "materials", "documentation"):
        row["f_" + k] = kinds.get(k, 0)
    row["readme"] = sum(1 for r in repo if r.get("file_type") == "readme")
    for r in repo:
        ext = os.path.splitext(str(r.get("file_name") or ""))[1].lower().lstrip(".")
        if ext and len(ext) <= 6:
            acc["extensions"][ext].add(base)
    names = m.get("naming_issues") if isinstance(m.get("naming_issues"), list) else []
    row["naming"] = len(names)
    for r in names:
        if isinstance(r, dict):
            acc["naming_rules"][r.get("rule") or "other"].add(base)
    useless = m.get("useless_files")
    row["useless"] = len(useless) if isinstance(useless, list) else 0

    # the code
    code = table(result, "code_check")
    langs = collections.Counter(r.get("language") or "other" for r in code)
    row["code"] = len(code)
    row["c_R"], row["c_Py"] = langs.get("R", 0), langs.get("Python", 0)
    row["c_other"] = len(code) - row["c_R"] - row["c_Py"]
    row["loc"] = int(sum(num(r.get("code_lines")) or 0 for r in code))
    row["comments"] = int(sum(num(r.get("comment_lines")) or 0 for r in code))
    row["setwd"] = int(sum(num(r.get("code_setwd")) or 0 for r in code))
    row["abspath"] = sum(1 for r in code if r.get("absolute_paths"))
    row["install"] = int(sum(num(r.get("code_install_packages")) or 0 for r in code))
    # the number of files a code file reads that are not in the repository
    row["missing_in"] = sum(1 for r in code if (num(r.get("loaded_files_missing")) or 0) > 0)
    for lang in langs:
        acc["languages"][lang].add(base)
    used = collections.defaultdict(set)
    for r in code:
        for p in str(r.get("packages") or "").split(","):
            p = p.strip()
            if p and len(p) < 40:
                used[r.get("language") or "other"].add(p)
    for lang, ps in used.items():
        for p in ps:
            acc["packages"][lang][p] += 1

    # the reproducibility check
    rep = [r for r in table(result, "reproducibility_check") if r.get("outcome")]
    row["scr"] = len(rep)
    row["ran"] = sum(1 for r in rep if r["outcome"] in RAN_THROUGH)
    row["broke"] = row["scr"] - row["ran"]
    for r in rep:
        acc["outcomes"][r["outcome"]] += 1
        ext = os.path.splitext(str(r.get("file_name") or ""))[1].lower()
        lang = {".r": "R", ".rmd": "R", ".qmd": "R", ".py": "Python", ".ipynb": "Python"}.get(ext, "other")
        acc["outcome_lang"][lang][r["outcome"] in RAN_THROUGH] += 1
    found = reproducibility_findings(result)
    for f in (found or {}).get("findings", []):
        acc["reasons"][f["reason"]] += 1
        msg = f.get("message") or ""
        kind = next((k for k, pat in MESSAGE_KINDS if re.search(pat, msg)), None)
        if not msg:
            kind = {"time": "it ran out of time", "interactive": "it waits for a person",
                    "internet": "it needs the internet", "package": "a package or module is missing",
                    "syntax": "it could not be read as code", "download": "its files could not be downloaded"
                    }.get(f["reason"], "no message")
        acc["message_kinds"][kind or "something else"] += 1
        for pat in PACKAGE_MISSING:
            for p in pat.findall(msg):
                acc["missing_packages"][p.split(".")[0]] += 1
        if msg:
            acc["messages"][re.sub(r"'[^']*'|\"[^\"]*\"|‘[^’]*’", "'…'", msg)[:120]] += 1

    # the data
    dat = table(result, "data_check")
    row["cols"] = len(dat)
    row["dfiles"] = len({r.get("source_file") for r in dat if r.get("source_file")})
    for r in dat:
        acc["levels"][r.get("measurement_level") or "unknown"] += 1
        acc["quality"][r.get("quality") or "unknown"] += 1
        acc["roles"][r.get("role") or "unknown"] += 1
        if true(r.get("is_qualtrics")):
            acc["qualtrics"].add(base)
    # n counts the values present, n_missing those missing
    shares = [(num(r.get("n_missing")) or 0) / ((num(r.get("n")) or 0) + (num(r.get("n_missing")) or 0))
              for r in dat if (num(r.get("n")) or 0) + (num(r.get("n_missing")) or 0) > 0]
    row["cmiss"] = round(sum(shares) / len(shares), 4) if shares else None
    issues = data_rows(result) if dat or (mods.get("data_check") or {}).get("report") else []
    row["dissues"] = len(issues)
    # by kind: "check" in metacheck's findings ("label" there names the sheet
    # of a problem with a whole sheet); results from before the findings list
    # only have the label, which then is the kind
    found = (mods.get("data_check") or {}).get("findings")
    kinds = ([r.get("check") or r.get("label") or "other" for r in found] if isinstance(found, list)
             else [r.get("label") or "other" for r in issues])
    for k in kinds:
        acc["data_issues"][k] += 1
    careless = (mods.get("data_check") or {}).get("careless")
    if isinstance(careless, list):
        row["careless"] = len(careless)
        for c in careless:
            for why in str((c or {}).get("reasons") or "").split(","):
                if why.strip():
                    acc["careless_reasons"][why.strip()] += 1
    cb = table(result, "codebook_check")
    row["cb_lab"] = sum(1 for r in cb if r.get("label_status") == "labelled")
    row["cb_unlab"] = sum(1 for r in cb if r.get("label_status") == "unlabelled")

    # the cited literature
    pp = table(result, "ref_pubpeer")
    row["pubpeer"] = len(pp)
    row["ppcom"] = int(sum(num(r.get("total_comments")) or 0 for r in pp))
    rw = table(result, "ref_retraction")
    row["retract"] = len(rw)
    for r in rw:
        acc["retraction_kinds"][r.get("retractionwatch") or "unknown"] += 1
    rr = table(result, "ref_replication")
    row["repl"] = len(rr)
    for r in rr:
        acc["replication_outcomes"][r.get("replication_outcome") or "unknown"] += 1
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()
    data_dir = args.data_dir

    index = load(os.path.join(data_dir, "index.json"), {"papers": []}).get("papers", [])
    tally = load(os.path.join(data_dir, "tally.json"), {})
    state = load(os.path.join(data_dir, "state.json"), {})
    C, S = collections.Counter, lambda: collections.defaultdict(set)
    acc = {"modules": [], "titles": {}, "p": [], "sc": [], "power": [], "d_pairs": [],
           "section_types": C(), "domains": C(), "title_words": C(), "keywords": C(),
           "authors": S(), "countries": C(), "bib_types": C(), "ref_years": C(), "ref_ages": C(),
           "journals": C(), "cited": S(), "cited_info": {}, "es_symbols": C(),
           "prereg_templates": C(), "extensions": S(), "naming_rules": S(), "languages": S(), "repo_sites": S(),
           "packages": collections.defaultdict(C), "outcomes": C(),
           "outcome_lang": collections.defaultdict(C), "reasons": C(), "message_kinds": C(),
           "missing_packages": C(), "messages": C(), "levels": C(), "quality": C(), "roles": C(),
           "qualtrics": set(), "data_issues": C(), "careless_reasons": C(),
           "retraction_kinds": C(), "replication_outcomes": C()}

    results = []
    for item in index:
        path = os.path.join(data_dir, "papers", item["id"] + ".json")
        if os.path.exists(path):
            results.append((item, load(path, {})))
    # the checks, in the order of the report (the order the server gives)
    for _, result in results:
        for m, v in (result.get("modules") or {}).items():
            if m not in acc["titles"]:
                acc["modules"].append(m)
                acc["titles"][m] = (v or {}).get("title") or m

    rows = [paper_row(i, item, result, acc) for i, (item, result) in enumerate(results)]

    def cited_list():
        out = []
        for key, bases in sorted(acc["cited"].items(), key=lambda kv: -len(kv[1])):
            if len(bases) < 2 or len(out) >= TOP:
                break
            out.append(dict(acc["cited_info"][key], n=len(bases)))
        return out

    totals = {
        "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "preprints_on_psyarxiv": tally.get("preprints"),
        "waiting": len(state.get("queue") or []),
        "failed": len(state.get("failed") or {}),
        "modules": [{"id": m, "title": acc["titles"][m]} for m in acc["modules"]],
        "light_codes": {v: k for k, v in LIGHT_CODE.items()},
        "section_codes": {v: k for k, v in SECTION_CODE.items()},
        "papers": rows,
        "p": acc["p"],
        "statcheck": acc["sc"],
        "power": acc["power"],
        "d_pairs": acc["d_pairs"],
        "counts": {
            "section_types": top(acc["section_types"], 20),
            "domains": top(acc["domains"]),
            "title_words": top(acc["title_words"], 60),
            "keywords": top(acc["keywords"]),
            # how many people wrote 1, 2, 3, ... of the preprints (no names)
            "authors_per_count": sorted([k, n] for k, n in
                                        collections.Counter(len(b) for b in acc["authors"].values()).items()),
            "countries": top(acc["countries"], 40),
            "bib_types": top(acc["bib_types"]),
            "ref_years": sorted([y, n] for y, n in acc["ref_years"].items()),
            "ref_ages": sorted([a, n] for a, n in acc["ref_ages"].items()),
            "journals": top(acc["journals"]),
            "cited": cited_list(),
            "es_symbols": top(acc["es_symbols"], 15),
            "prereg_templates": top(acc["prereg_templates"], 15),
            "extensions": [[e, len(b)] for e, b in sorted(acc["extensions"].items(), key=lambda kv: -len(kv[1]))][:TOP],
            "naming_rules": [[r, len(b)] for r, b in sorted(acc["naming_rules"].items(), key=lambda kv: -len(kv[1]))],
            "repo_sites": [[r, len(b)] for r, b in sorted(acc["repo_sites"].items(), key=lambda kv: -len(kv[1]))],
            "languages": [[l, len(b)] for l, b in sorted(acc["languages"].items(), key=lambda kv: -len(kv[1]))],
            "packages": {lang: top(c, 25) for lang, c in acc["packages"].items() if lang in ("R", "Python")},
            "outcomes": top(acc["outcomes"]),
            "outcome_lang": {l: {"ran": c[True], "broke": c[False]} for l, c in acc["outcome_lang"].items()},
            "reasons": top(acc["reasons"]),
            "message_kinds": top(acc["message_kinds"]),
            "missing_packages": top(acc["missing_packages"], 20),
            "messages": top(acc["messages"], 20),
            "levels": top(acc["levels"]),
            "quality": top(acc["quality"]),
            "roles": top(acc["roles"]),
            "qualtrics": len(acc["qualtrics"]),
            "data_issues": top(acc["data_issues"]),
            "careless_reasons": top(acc["careless_reasons"]),
            "retraction_kinds": top(acc["retraction_kinds"]),
            "replication_outcomes": top(acc["replication_outcomes"]),
        },
    }
    path = os.path.join(data_dir, "totals.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(totals, f, ensure_ascii=False, separators=(",", ":"))
    print("%s: %d preprints, %d KB" % (path, len(rows), os.path.getsize(path) // 1024))


if __name__ == "__main__":
    main()
