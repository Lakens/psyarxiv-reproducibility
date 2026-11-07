# Checks that the SURF server converts PDF and Word files and makes reports.
# Sends three jobs to the public web interface: a PDF preprint (by its PsyArXiv
# id), a Word file uploaded directly, and a JSON check of the PDF preprint that
# must carry each module's section and report text. Uses only the Python
# standard library. Takes several minutes; each job runs the checks without
# the code of the paper's repository (run_code=false).
#
#   python scripts/test_surf_jobs.py [--pdf-id qgef5_v2] [--docx-id zak2b_v2]

import argparse
import json
import time
import urllib.error
import urllib.request
import uuid

SERVER = "https://metacheckserve.metacheck.src.surf-hosted.nl/api"
OSF = "https://api.osf.io/v2/preprints"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MODULES = "repo_check,code_check,data_check"


def post_job(fields, file=None):
    boundary = uuid.uuid4().hex
    body = b""
    for key, value in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
    if file is not None:
        name, data, ctype = file
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                 f"Content-Type: {ctype}\r\n\r\n").encode() + data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{SERVER}/jobs", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.load(urllib.request.urlopen(req, timeout=300))


def wait_for(job_id, minutes=6):
    end = time.time() + minutes * 60
    while time.time() < end:
        status = json.load(urllib.request.urlopen(f"{SERVER}/jobs/{job_id}", timeout=60))
        if status.get("status") in ("done", "failed"):
            return status
        time.sleep(10)
    return status


def word_file_of(osf_id):
    # the preprint's primary file on OSF, downloaded
    pre = json.load(urllib.request.urlopen(f"{OSF}/{osf_id}/", timeout=60))["data"]
    url = pre["relationships"]["primary_file"]["links"]["related"]["href"]
    info = json.load(urllib.request.urlopen(url, timeout=60))["data"]
    return info["attributes"]["name"], urllib.request.urlopen(info["links"]["download"], timeout=300).read()


def report_line(label, status):
    print(f"{label}: {status.get('status')} | converter: {status.get('converter')} | "
          f"error: {(status.get('error') or '-')[:200]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf-id", default="qgef5_v2")
    parser.add_argument("--docx-id", default="zak2b_v2")
    args = parser.parse_args()
    base = {"report_type": "checklist", "modules": MODULES, "run_code": "false"}

    # 1. PDF preprint by its id: a report
    job = post_job({"kind": "report", "psyarxiv": args.pdf_id, **base})
    report_line("PDF preprint (report)", wait_for(job["id"]))

    # 2. Word file uploaded directly: a report, converted by LibreOffice then GROBID
    name, data = word_file_of(args.docx_id)
    job = post_job({"kind": "report", **base}, file=(name, data, DOCX))
    status = wait_for(job["id"])
    report_line("Word file (report)", status)

    # 3. JSON check of the PDF preprint: every module keeps section and report text
    job = post_job({"kind": "check", "psyarxiv": args.pdf_id, **base})
    status = wait_for(job["id"])
    report_line("PDF preprint (JSON check)", status)
    if status.get("status") == "done":
        result = json.load(urllib.request.urlopen(f"{SERVER}/jobs/{job['id']}/result", timeout=120))
        modules = result.get("modules", {})
        ok = all("section" in m and "report" in m for m in modules.values())
        print(f"  modules: {', '.join(modules)}; section and report in each: {ok}")


if __name__ == "__main__":
    main()
