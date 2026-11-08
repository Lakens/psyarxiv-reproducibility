# Collects the rules that the secret scanner betterleaks uses to find keys
# (passwords for paid services, such as API keys) and writes them to
# scripts/key_patterns.json, which update.py reads to remove keys from what it
# saves. Run it by hand to take up newer rules; the run does not.
#
#   python scripts/make_key_patterns.py
#
# The rules are the work of betterleaks, https://github.com/betterleaks/betterleaks
# (MIT licence, (c) the betterleaks authors), made by the authors of gitleaks
# and its successor; its file config/betterleaks.toml. The commit that was read is
# written into key_patterns.json.
#
# Why betterleaks (8 November 2026): its rules each have a confidence level
# and filters against false finds, and they cover OpenRouter. Tried first were
# gitleaks (MIT; its rules are in betterleaks too) and TruffleHog (AGPL-3.0):
# TruffleHog's patterns are written to be followed by a test of the key with
# its provider, so without that test they find ordinary words and file names
# (on the 71 reports of 8 November 2026: 2,820 finds, in every report).
# Others looked at: Titus and Kingfisher (Apache-2.0; their rules are partly
# taken from betterleaks), detect-secrets (Apache-2.0; fewer providers),
# GitHub's own scanning (its patterns are not published).
#
# Taken: the rules with confidence "high" or "medium" that report a find on
# their own (not the parts of composite rules, skipReport). Left out: the three
# "low" rules (generic-api-key, generic-password, generic-username), which look
# for any value after a word such as "key" or "password".
#
# Of each rule's filter only its minimum entropy (how random the key must be)
# is kept; other conditions (such as tokenRatio, which needs betterleaks'
# word list) are left out, so a little more is removed than betterleaks
# would report. The general filter's placeholders (such as ${VAR} or true) are
# kept, as `ignore`.
#
# betterleaks is written in Go, whose regular expressions differ a little from
# Python's; a pattern is converted where that is simple (a flag such as (?i)
# in the middle, \z, [[:alnum:]]) and left out when Python cannot read it.

import json
import os
import re
import sys
import tomllib
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "key_patterns.json")
UA = "psyarxiv_metacheck (github.com/Lakens/psyarxiv_metacheck)"
REPO = "betterleaks/betterleaks"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


POSIX = {"alnum": "a-zA-Z0-9", "alpha": "a-zA-Z", "digit": "0-9", "xdigit": "0-9a-fA-F",
         "upper": "A-Z", "lower": "a-z", "space": r"\s", "word": r"\w",
         "punct": r"!-/:-@\[-`{-~"}


def to_python(rx):
    # a Go (RE2) pattern as a Python one; None when Python cannot read it
    if re.search(r"\\p[A-Z{]|\\Q", rx):
        return None
    rx = re.sub(r"\[:(\w+):\]", lambda m: POSIX.get(m.group(1), m.group(0)), rx)
    rx = rx.replace(r"\z", r"\Z")
    # flags for the whole pattern must stand at its start in Python
    flags = set()

    def take(m):
        flags.update(m.group(1))
        return ""
    rx = re.sub(r"\(\?([imsxU]+)\)", take, rx)
    flags.discard("U")
    if flags:
        rx = "(?" + "".join(sorted(flags)) + ")" + rx
    try:
        re.compile(rx)
    except re.error:
        return None
    return rx


def min_entropy(flt):
    # the entropy a key must reach by the rule's filter, which drops a find
    # with entropy(finding["secret"]) < N (or <= N); None when it has none
    m = re.search(r'entropy\(finding\["secret"\]\)\s*(<=?)\s*([\d.]+)', flt or "")
    if not m:
        return None
    return {"min": float(m.group(2)), "strict": m.group(1) == "<="}


def placeholders(flt):
    # the general filter: patterns and texts that a find must not be
    pats = re.search(r'matchesAny\(finding\["secret"\],\s*\[(.*?)\]\)', flt, re.S)
    texts = re.search(r'containsAny\(finding\["secret"\],\s*\[(.*?)\]\)', flt, re.S)
    out = {"patterns": [], "texts": []}
    for rx in re.findall(r"`([^`]*)`", pats.group(1)) if pats else []:
        rx = to_python(rx)
        if rx:
            out["patterns"].append(rx)
    out["texts"] = re.findall(r'"([^"]*)"', texts.group(1)) if texts else []
    return out


def main():
    sha = json.loads(get(f"https://api.github.com/repos/{REPO}/commits/HEAD"))["sha"]
    conf = tomllib.loads(get(f"https://raw.githubusercontent.com/{REPO}/{sha}/config/betterleaks.toml").decode())
    out, dropped, left_out = [], [], []
    for rule in conf["rules"]:
        if not rule.get("regex") or rule.get("skipReport") or rule.get("confidence") not in ("high", "medium"):
            left_out.append(rule["id"])
            continue
        rx = to_python(rule["regex"])
        if rx is None:
            dropped.append(rule["id"])
            continue
        out.append({"name": rule["id"], "description": rule.get("description"),
                    "confidence": rule["confidence"], "regex": rx,
                    "keywords": [k.lower() for k in rule.get("keywords", [])],
                    "entropy": min_entropy(rule.get("filter")),
                    "group": rule.get("valueGroup") or rule.get("secretGroup")})
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump({
            "about": "Rules for finding keys, from betterleaks (MIT licence, (c) the betterleaks authors), "
                     "collected by scripts/make_key_patterns.py.",
            "source": {"url": f"https://github.com/{REPO}", "licence": "MIT", "commit": sha,
                       "file": "config/betterleaks.toml"},
            "ignore": placeholders(conf.get("filter", "")),
            "patterns": out,
        }, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"betterleaks {sha[:7]}: {len(out)} rules taken; {len(left_out)} left out "
          f"(low confidence, or part of another rule); {len(dropped)} Python cannot read: {dropped}")
    print(f"Written to {OUT}")


if __name__ == "__main__":
    sys.exit(main())
