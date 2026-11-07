# psyarxiv-reproducibility

A web page (GitHub Pages) that will show metacheck's reproducibility reports on PsyArXiv preprints. This repository holds the page, the scripts, and the notes for continuing the work.

## Status

Done:
- The landing page layout: `index.html`, with `site.css` copied from the SURF site (same colours, font and layout), and `landing.css`. The page shows a tally read from `data/tally.json`. That file does not exist yet, so the page shows "not yet".
- `scripts/test_surf_jobs.py`: sends three test jobs to the SURF server (a PDF preprint, a Word file, and a JSON check). It passed on the last run.
- On the SURF server (`surf-research-cloud`, branch `main`):
  - each module's section and detailed report text is kept in the JSON result (commit `607de75`);
  - a Word file uploaded directly is accepted and converted (commit `5c22474`);
  - the Word-file setting is `local` (LibreOffice, then GROBID);
  - the PsyArXiv report job is switched off (`metacheck_psyarxiv_reports: "0"`).

Not built yet:
- The scheduled run: list new preprints, send them one at a time to the SURF server, save each paper's JSON, and update `data/tally.json`.
- The paper pages (one per preprint, showing its report).
- The `data/` folder layout.

## Decisions so far

- Source: the old PsyArXiv site, through the OSF API: `https://api.osf.io/v2/preprints/?filter[provider]=psyarxiv`. Not `next.psyarxiv.org`.
- Scope: every new preprint, newest first. When no new preprint is waiting, older ones, one at a time.
- Checks: the checks the SURF server already runs for its regular report (the 15 modules listed below), with the paper's code run in the sandbox (`run_code=true`).
- Repository links: found by scanning each paper, not taken from OSF's data-link field.
- No reproducibility labels: the metacheck report is the output.
- Storage: JSON only, no full HTML reports.
  - Keep: the preprint's address, ID, title, authors, date, version and DOI; the paper details the report reads (title, DOI, authors, reference list); for each module, all of its output (traffic light, summary text, summary table, table, section, report text); metacheck version, converter, modules run, and errors.
  - Drop: the uploaded file, the paper's full text, the HTML report, the downloaded repository files, and the progress and log files.
  - Open: the reproducibility check's full console output (every line each script printed). It may be large. Measure it on the first real runs, then decide.
- Landing page: a running tally of preprints listed on PsyArXiv, preprints checked, and the date of the last update. Still open: whether to count PDFs (this needs one more request per preprint to read its file type).
- The intro text and any other page wording are written by Daniel. Nothing is written for them.

## The SURF server

- Public address: `https://metacheckserve.metacheck.src.surf-hosted.nl`. Health check: `/api/health`.
- Jobs: `POST /api/jobs` (form data) with `kind` (`report` or `check`), `psyarxiv` (a preprint id) or `file`, `report_type=checklist`, `modules`, `run_code` (`true` or `false`), `crossref`. Then `GET /api/jobs/<id>`, and `GET /api/jobs/<id>/result` when done. Results are deleted 60 minutes after they finish.
- The 15 modules the server runs for a report: `power`, `marginal`, `prereg_check`, `ethics_check`, `ref_pubpeer`, `ref_retraction`, `ref_replication`, `stat_check`, `stat_p_exact`, `stat_p_nonsig`, `stat_effect_size`, `repo_check`, `code_check`, `data_check`, `codebook_check`.
- `reproducibility_check` (the module that runs the code) is not on that list. Open question: add it to the server's list, or not.
- Access: SSH key `~/.ssh/id_ed25519_metacheckserve`, user `dlakens`, host `metacheckserve.metacheck.src.surf-hosted.nl`.
- On the server: the code clone is `~/surf-research-cloud` (branch `main`); the running copy is `/opt/metacheck-component`.
- Deploying a change:
  1. Push `main` in the `surf-research-cloud` repository.
  2. On the server: `cd ~/surf-research-cloud && git pull --ff-only origin main`.
  3. Check that no run is active: `ps -eo args | grep "[a]nsible-env/bin/python"` must print nothing.
  4. Start the playbook in the background, with a log file: `sudo ~/ansible-env/bin/ansible-playbook --connection=local -i localhost, -b metacheck.yml > ~/playbook-<date>.log 2>&1`. A run takes about two minutes. Check the end of the log for `failed=0`.
- Remembered settings: the server keeps values given in earlier runs in `/etc/metacheck-settings.json`. A changed default in `metacheck.yml` does not override a remembered value. To change one setting, pass it on the command line: `-e name=value`.

## The surf-research-cloud repository

- Work on `main` (this is Daniel's rule for this repository).
- The local folder `git_repos/surf-research-cloud` is on another branch, `python2-sandbox`, with uncommitted edits that are not ours. Switch to `main` before editing, and do not commit that branch's edits.

## How to continue

1. Get the latest version of this repository (`git pull` in its folder).
2. See the page: from the project folder run `python -m http.server 8765`, then open `http://127.0.0.1:8765/`. The tally shows "not yet" until `data/tally.json` exists.
3. Check the server: `python scripts/test_surf_jobs.py`. It sends three jobs to the public server; it takes several minutes.
4. Build the next parts, in this order: the scheduled run; the `data/` folder and the tally file; the paper pages.

## Open questions

- Add `reproducibility_check` to the server's module list?
- Measure the size of the reproducibility check's full output on the first runs, then decide whether to shorten it.
- Page title and intro text (written by Daniel).
- Does the old PsyArXiv site give the Word file itself for Word preprints? (The new site gave a PDF version for one Word preprint, `zak2b_v2`. The old site's file is the Word file, `d-ELP Final Clean.docx`.)

## Keys

API keys are in `OneDrive\Documents\.Renviron`. Do not put keys in this repository.
