#!/usr/bin/env python3
"""Test the web build of muse-video-tool (stdlib only).

Loads the tool token from .env (never from argv), then checks:
  1. GET / serves the web UI
  2. POST /jobs without the token -> 401
  3. Two concurrent test-clips jobs (multitask) both reach done
  4. Both downloads are real MP4s
Usage: python3 test_web.py [server_url]
"""

import json
import sys
import time
import urllib.request
import urllib.error

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18700"
        ).rstrip("/")


def load_dotenv():
    env = {}
    try:
        with open(".env", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return env


def req(method, path, body=None, key=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        r.add_header("Content-Type", "application/json")
    if key:
        r.add_header("X-Api-Key", key)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read(), resp.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def main():
    token = load_dotenv().get("MUSE_JOB_API_KEY", "")
    assert token, "MUSE_JOB_API_KEY missing from .env"
    # 1. Web UI
    status, body, headers = req("GET", "/")
    assert status == 200 and b"MuseVideo" in body, f"GET / -> {status}"
    assert headers.get("Access-Control-Allow-Origin") == "*", "CORS missing"
    print("1. web UI OK (CORS OK)")
    # 2. No token -> 401
    scenes = [{"prompt": "test", "caption": "Test"}]
    status, body, _ = req("POST", "/jobs",
                          {"scenes": scenes, "duration": 5,
                           "mode": "test-clips"})
    assert status == 401, f"no-key POST -> {status} (expected 401)"
    print("2. no-key POST -> 401 OK")
    # 3. Two concurrent jobs
    ids = []
    for i in range(2):
        status, body, _ = req("POST", "/jobs",
                              {"scenes": [
                                  {"prompt": "A cute monkey walking",
                                   "caption": f"Job {i+1} canh 1"},
                                  {"prompt": "A cute frog jumping",
                                   "caption": f"Job {i+1} canh 2"}],
                               "duration": 5, "mode": "test-clips"},
                              key=token)
        assert status == 200, f"POST job {i+1} -> {status}: {body[:200]}"
        ids.append(json.loads(body)["id"])
    print(f"3. 2 jobs created (multitask): {ids}")
    deadline = time.time() + 240
    done = set()
    while len(done) < 2 and time.time() < deadline:
        for jid in ids:
            if jid in done:
                continue
            status, body, _ = req("GET", f"/jobs/{jid}", key=token)
            if json.loads(body).get("status") == "done":
                done.add(jid)
        time.sleep(5)
    assert len(done) == 2, f"only {len(done)}/2 jobs done"
    print("3. both jobs done OK")
    # 4. Downloads
    for jid in ids:
        status, data, _ = req("GET", f"/jobs/{jid}/download", key=token)
        assert status == 200 and len(data) > 100000, \
            f"download {jid} -> {status}, {len(data)} bytes"
        assert data[4:8] == b"ftyp", "not an MP4"
        print(f"4. download {jid}: {len(data)} bytes, MP4 OK")
    print("ALL WEB TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
