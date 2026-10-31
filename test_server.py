#!/usr/bin/env python3
"""End-to-end test for the job server (stdlib only).

Creates a test-clips job, polls until done/failed, downloads the MP4 and
prints its size. Usage:
  python3 test_server.py [server_url]
"""

import json
import sys
import time
import urllib.request
import urllib.error

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18700"
        ).rstrip("/")


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main():
    scenes = [
        {"prompt": "A cute monkey and a turtle walking together in a sunny "
                   "garden, 2D animation style, vertical video",
         "caption": "Khỉ và Rùa đi dạo"},
        {"prompt": "A cute frog jumping happily on a lotus leaf in a pond, "
                   "2D animation style, vertical video",
         "caption": "Ếch nhảy trên lá sen"},
    ]
    status, body = req("POST", "/jobs",
                       {"scenes": scenes, "duration": 5, "mode": "test-clips"})
    assert status == 200, f"POST /jobs -> {status}: {body[:300]}"
    job_id = json.loads(body)["id"]
    print(f"job: {job_id}", flush=True)
    deadline = time.time() + 240
    while True:
        status, body = req("GET", f"/jobs/{job_id}")
        job = json.loads(body)
        print(f"poll: {job.get('status')}", flush=True)
        if job.get("status") in ("done", "failed"):
            break
        if time.time() > deadline:
            print("TIMEOUT")
            return 1
        time.sleep(5)
    if job.get("status") != "done":
        print(f"FAILED: {job.get('error', '')[:500]}")
        return 1
    status, data = req("GET", f"/jobs/{job_id}/download")
    assert status == 200, f"download -> {status}"
    out = f"/tmp/job-{job_id}.mp4"
    with open(out, "wb") as f:
        f.write(data)
    print(f"downloaded: {out} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
