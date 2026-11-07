# psyarxiv-reproducibility

A web page (GitHub Pages) that will show metacheck's reproducibility reports on PsyArXiv preprints. This repository holds the page, the scripts, and the notes for continuing the work.

## Status

Done:
- The landing page: `index.html`, with `site.css` copied from the SURF site (same colours, font and layout), `landing.css` and `landing.js`. It shows, in the top right corner, the number of preprints checked ("5 preprints checked", from `data/tally.json`), and a list of the reports (`data/index.json`): each title links to its report page, followed by the authors, the date, the id and a link to the OSF page. Above the list: a search field (title, authors, OSF id; every word typed must occur; capitals, accents and letters such as ł are ignored), and a line explaining green and grey links. A preprint none of the checks applied to (every module's traffic light "na") is greyed out, so it is clear there is little to read; its report page is still there. (The three boxes with the tally were removed on 7 November 2026, at Daniel's request.) The heading "Reports" and the link text "OSF" are placeholders for Daniel's wording.
- The report pages: `<id>/index.html` at the top of the repository, one per checked preprint version (for example `jc6rp_v1/`), so a report's address ends in the id as the OSF's does (`https://osf.io/preprints/psyarxiv/jc6rp_v1`). Each is the server's checklist report, as the metacheck site shows it, with two changes: the line at the top saying what converted the file (GROBID, "less complete than bibr's") is left out (the converter is kept in the result file), and the paper's full text, as metacheck read it, is added as the last folded block ("Full text") under "More detail": each section's heading, then its paragraphs (tables and figure captions not yet). The font and logo the server puts inside every page are linked to `fonts/Cabin.ttf` and `images/logo.png` instead (the script checks they are the same files, byte for byte), which makes a page about 58 KB instead of 355 KB.
- `scripts/test_surf_jobs.py`: sends three test jobs to the SURF server (a PDF preprint, a Word file, and a JSON check). It passed on the last run.
- On the SURF server (`surf-research-cloud`, branch `main`):
  - each module's section and detailed report text is kept in the JSON result (commit `607de75`);
  - a Word file uploaded directly is accepted and converted (commit `5c22474`);
  - the Word-file setting is `local` (LibreOffice, then GROBID);
  - the PsyArXiv report job is switched off (`metacheck_psyarxiv_reports: "0"`);
  - a check with `paper=true` returns the paper as converted, unchanged, as `paper` in its result (not yet committed or deployed);
  - the JSON result also keeps the authors and reference list GROBID read (`paper_info$authors`, `paper_info$references`), and each module's `checks`, `checklist_section`, `intro`, `naming_issues` and `useless_files` when it gives them: the fields metacheck's checklist report reads (commit `c7dbafa`, deployed 7 November 2026).
- The scheduled run: `scripts/update.py`, run by `.github/workflows/update.yml`. For now the workflow starts only by hand (Actions tab, "Run workflow"); its hourly schedule is in the file, behind `#`. The first five reports were made on 7 November 2026 by running the script on Daniel's computer (`--max 5`).
  - It lists preprints on the OSF and downloads each one's file (PDF or Word) itself, then uploads it to the SURF server as one job that returns both the JSON result and the report page (`kind=check`, `report=true`). The server's own `psyarxiv` field cannot be used: it looks preprints up on `next.psyarxiv.org`, which does not have the newest ones yet, and it always takes the newest version.
  - Order: preprints published since the last run, newest first; when none is waiting, older ones, one day at a time going back, until 1000 older preprints have been sent.
  - A preprint is checked in the version that is its newest at that moment. When a newer version is checked later, the reports on older versions stay.
  - A run starts no new preprint after 50 minutes. A failed job is tried three times, then listed in `state.json` under `failed`.
  - One preprint at a time on the server, so one of its two places stays free for other people (Daniel's rule). The job the script has on the server is kept in `data/current_job.json`; no new job is sent while it is still queued or running, also not by the next run. Do not run the script on your own computer while the hourly run is on: the two would not see each other's jobs.
  - Started by hand (Actions tab, "Update the reports", "Run workflow"), it asks how many preprints to check at most (0: no limit).
- The `data/` folder:
  - `papers/<id>.json`: one per checked preprint version (for example `jc6rp_v1.json`). The OSF details (address, DOI, title, authors, date, version, file name), and everything the server returned except the report page, which is saved as `<id>/index.html`: metacheck's version and converter, the modules run, the modules that failed, `paper_info`, each module's full output, tables included, and `paper`: the paper as converted (bibr JSON: its full text in sections, references, tables, figure captions, links), which metacheck can read again to run checks without converting the file again. Sizes vary a lot: 18 KB to 3.4 MB for the first five without `paper` (most of it the `stat_p_exact` and `stat_p_nonsig` tables, which repeat the paragraph around each p-value); `paper` adds about 190 KB.
  - `index.json`: one line per checked preprint version (id, version, title, authors, date, OSF address, date checked, whether there is a report page, each module's traffic light).
  - `tally.json`: the numbers on the landing page.
  - `state.json`: the newest preprint listed, the next older day to list, the preprints waiting, and those skipped (withdrawn, older version, a file that is not PDF or Word, larger than 50 MB) or failed.

- Publishing: `.github/workflows/pages.yml` puts on GitHub Pages only the landing page and its files, the report pages, `data/index.json` and `data/tally.json`, after every push and after each run of `update.yml`. The full results in `data/papers/` stay in the repository only: GitHub Pages publishes at most 1 GB, counted at full size, while git stores the repository's files compressed (so compressing them ourselves would hardly make the repository smaller).
- `scripts/update.py --redo <id> ...` checks the given preprint versions again and overwrites their files.

Not done yet:
- GitHub Pages is not switched on for this repository yet (its source must be "GitHub Actions").
- The hourly schedule is switched off.

## Decisions so far

- Source: the old PsyArXiv site, through the OSF API: `https://api.osf.io/v2/preprints/?filter[provider]=psyarxiv`. Not `next.psyarxiv.org`.
- Scope: every new preprint, newest first. When no new preprint is waiting, older ones, one at a time.
- Checks: the checks the SURF server already runs for its regular report (the 15 modules listed below), with the paper's code run in the sandbox (`run_code=true`).
- Repository links: found by scanning each paper, not taken from OSF's data-link field.
- No reproducibility labels: the metacheck report is the output.
- Storage: keep everything the server returns (Daniel, 7 November 2026: the data is valuable; when the repository gets too large, that is solved then). That is the JSON result with every module's full output, tables included, and the checklist report page. Reports on older versions of a preprint stay.
  - Not stored, because the server does not return them: the uploaded file, the paper's full text, the downloaded repository files, and the progress and log files.
  - Open: the reproducibility check's full console output (every line each script printed). It may be large. Measure it on the first real runs, then decide.
- Report addresses: `<site>/<id>/`, ending in the id with its version as the OSF's address does.
- Landing page: a running tally of preprints listed on PsyArXiv, preprints checked, and the date of the last update. Still open: whether to count PDFs (this needs one more request per preprint to read its file type).
- The intro text and any other page wording are written by Daniel, or on his request. The title is his ("Metacheck reports for PsyArXiv preprints"). The intro (7 November 2026, on his request) starts with the sentences of the SURF site's landing page, adds the warning from the server's PsyArXiv reports page, and links to Metacheck's GitHub page and issues page, the manual, and the SURF server, and thanks SURF.

## The SURF server

- Public address: `https://metacheckserve.metacheck.src.surf-hosted.nl`. Health check: `/api/health`.
- Jobs: `POST /api/jobs` (form data) with `kind` (`report` or `check`), `psyarxiv` (a preprint id) or `file`, `report_type=checklist`, `modules`, `run_code` (`true` or `false`), `crossref`. Then `GET /api/jobs/<id>`, and `GET /api/jobs/<id>/result` when done. Results are deleted 60 minutes after they finish.
- The 15 modules the server runs for a report: `power`, `marginal`, `prereg_check`, `ethics_check`, `ref_pubpeer`, `ref_retraction`, `ref_replication`, `stat_check`, `stat_p_exact`, `stat_p_nonsig`, `stat_effect_size`, `repo_check`, `code_check`, `data_check`, `codebook_check`.
- `reproducibility_check` (the module that runs the code) is not on that list, but the server adds it itself when `run_code=true`, so each result has 16 modules.
- The server stops a paper's code after 60 minutes and refuses files larger than 50 MB.
- Access: SSH key `~/.ssh/id_ed25519_metacheckserve`, user `dlakens`, host `metacheckserve.metacheck.src.surf-hosted.nl`.
- On the server: the code clone is `~/surf-research-cloud` (branch `main`); the running copy is `/opt/metacheck-component`.
- Deploying a change:
  1. Push `main` in the `surf-research-cloud` repository.
  2. On the server: `cd ~/surf-research-cloud && git pull --ff-only origin main`.
  3. Check that no run is active: `ps -eo args | grep "[a]nsible-env/bin/python"` must print nothing.
  4. Start the playbook in the background, with a log file: `sudo ~/ansible-env/bin/ansible-playbook --connection=local -i localhost, -b metacheck.yml > ~/playbook-<date>.log 2>&1`. A run takes about two minutes. Check the end of the log for `failed=0`.
- Remembered settings: the server keeps values given in earlier runs in `/etc/metacheck-settings.json`. A changed default in `metacheck.yml` does not override a remembered value. To change one setting, pass it on the command line: `-e name=value`.

## The surf-research-cloud repository

- Work on `main` (this is Daniel's rule for this repository). The local folder `git_repos/surf-research-cloud` is on `main` (checked 7 November 2026).

## How to continue

1. Get the latest version of this repository (`git pull` in its folder).
2. See the page: from the project folder run `python -m http.server 8765`, then open `http://127.0.0.1:8765/`.
3. Check the server: `python scripts/test_surf_jobs.py`. It sends three jobs to the public server; it takes several minutes.
4. Try the scheduled run without touching the site: `python scripts/update.py --max 1 --data-dir <a test folder> --site-dir <a test folder>` (copy `fonts/` and `images/` into that test folder first).
5. Add reports: start the workflow by hand on GitHub, or switch on its hourly schedule.

## Open questions

- Measure the size of the reproducibility check's full output on the first runs, then decide whether to shorten it.
- The tally's number of preprints is the OSF's count, which counts every version of a preprint once (66,252 on 7 November 2026). The OSF cannot list only the newest versions, so counting preprints instead of versions would need about 660 more requests per run.
- Does the old PsyArXiv site give the Word file itself for Word preprints? (The new site gave a PDF version for one Word preprint, `zak2b_v2`. The old site's file is the Word file, `d-ELP Final Clean.docx`.)

## Keys

API keys are in `OneDrive\Documents\.Renviron`. Do not put keys in this repository.
