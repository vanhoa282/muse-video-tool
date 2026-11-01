#!/usr/bin/env python3
"""Test the operator-queue build of muse-video-tool (stdlib only).

Loads the tool token from .env (never from argv), then checks:
  1. GET / and GET /admin serve HTML pages
  2. POST /jobs without the token -> 401
  3. POST /jobs creates an order in status cho_chay (NOT auto-run)
  4. GET /jobs lists it; POST /jobs/{id}/run starts it
  5. Poll -> done; download is a real MP4; second run returns done
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


def req_raw(method, path, blob, key=None, ctype="video/mp4"):
    r = urllib.request.Request(BASE + path, data=blob, method=method)
    r.add_header("Content-Type", ctype)
    if key:
        r.add_header("X-Api-Key", key)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, resp.read(), resp.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def main():
    token = load_dotenv().get("MUSE_JOB_API_KEY", "")
    assert token, "MUSE_JOB_API_KEY missing from .env"
    # 1. Pages
    status, body, _ = req("GET", "/")
    assert status == 200 and b"MuseVideo" in body, f"GET / -> {status}"
    status, body, _ = req("GET", "/admin")
    assert status == 200 and "Trang".encode() in body, \
        f"GET /admin -> {status}"
    print("1. web UI + admin page OK")
    # 2. No token -> 401
    scenes = [{"prompt": "test", "caption": "Test"}]
    status, _, _ = req("POST", "/jobs",
                       {"scenes": scenes, "duration": 5,
                        "mode": "test-clips"})
    assert status == 401, f"no-key POST -> {status} (expected 401)"
    status, _, _ = req("GET", "/jobs")
    assert status == 401, f"no-key list -> {status} (expected 401)"
    print("2. no-key POST/list -> 401 OK")
    # 3. Create order (queued, not auto-run)
    status, body, _ = req("POST", "/jobs",
                          {"scenes": [
                              {"prompt": "A cute monkey walking",
                               "caption": "Canh 1"},
                              {"prompt": "A cute frog jumping",
                               "caption": "Canh 2"}],
                           "duration": 5, "mode": "test-clips"},
                          key=token)
    assert status == 200, f"POST -> {status}: {body[:200]}"
    job = json.loads(body)
    assert job["status"] == "cho_chay", f"new order: {job}"
    jid = job["id"]
    print(f"3. order created, queued: {jid}")
    time.sleep(3)
    status, body, _ = req("GET", f"/jobs/{jid}", key=token)
    assert json.loads(body)["status"] == "cho_chay", \
        "order auto-ran (should wait for operator)"
    status, body, _ = req("GET", "/jobs", key=token)
    ids = [o["id"] for o in json.loads(body)["orders"]]
    assert jid in ids, "order missing from list"
    print("3. order stays queued, listed OK")
    # 4. Operator runs it
    status, body, _ = req("POST", f"/jobs/{jid}/run", key=token)
    assert status == 200, f"run -> {status}: {body[:200]}"
    assert json.loads(body)["status"] == "dang_chay", body[:200]
    deadline = time.time() + 240
    while True:
        status, body, _ = req("GET", f"/jobs/{jid}", key=token)
        st = json.loads(body)["status"]
        print(f"poll: {st}")
        if st in ("done", "failed"):
            break
        assert time.time() < deadline, "run timeout"
        time.sleep(5)
    assert st == "done", f"final status: {st}"
    print("4. operator run -> done OK")
    # 5. Download + idempotent re-run
    status, data, _ = req("GET", f"/jobs/{jid}/download", key=token)
    assert status == 200 and len(data) > 100000, \
        f"download -> {status}, {len(data)} bytes"
    assert data[4:8] == b"ftyp", "not an MP4"
    print(f"5. download: {len(data)} bytes, MP4 OK")
    mp4data = data
    status, body, _ = req("POST", f"/jobs/{jid}/run", key=token)
    assert json.loads(body)["status"] == "done", "re-run not idempotent"
    print("5. re-run on done order -> done OK")
    # 6. Client page + operator orders (FrameWeaver-style client)
    status, body, _ = req("GET", "/client")
    assert status == 200 and b"MuseVideo" in body, f"GET /client -> {status}"
    status, body, _ = req("POST", "/jobs",
                          {"title": "Test truyen",
                           "characters": [{"name": "Khi", "desc": "khi con"}],
                           "scenes": [{"prompt": "test", "caption": "Canh 1",
                                       "duration": 7}],
                           "duration": 7, "mode": "operator"},
                          key=token)
    assert status == 200, f"operator POST -> {status}: {body[:200]}"
    op = json.loads(body)
    assert op["status"] == "cho_chay", op
    status, body, _ = req("POST", f"/jobs/{op['id']}/run", key=token)
    assert status == 400, f"operator run -> {status} (expected 400)"
    status, body, _ = req("GET", f"/jobs/{op['id']}", key=token)
    v = json.loads(body)
    assert v["mode"] == "operator" and v.get("title") == "Test truyen", \
        body[:200]
    assert v["characters"][0]["name"] == "Khi", body[:200]
    assert v["scenes"][0].get("duration") == 7, body[:200]
    print("6. client page + operator order OK")
    # 7. Operator completes an order by uploading the finished MP4
    status, body, _ = req_raw("POST", f"/jobs/{op['id']}/complete",
                              b"not a video", key=token)
    assert status == 400, f"complete garbage -> {status} (expected 400)"
    status, body, _ = req("POST", f"/jobs/{op['id']}/complete")
    assert status == 401, f"complete no-key -> {status} (expected 401)"
    status, body, _ = req_raw("POST", f"/jobs/{op['id']}/complete",
                              mp4data, key=token)
    assert status == 200, f"complete -> {status}: {body[:200]}"
    assert json.loads(body)["status"] == "done", body[:200]
    status, body, _ = req("GET", f"/jobs/{op['id']}", key=token)
    assert json.loads(body)["status"] == "done", body[:200]
    status, data, _ = req("GET", f"/jobs/{op['id']}/download", key=token)
    assert status == 200 and len(data) == len(mp4data), \
        f"completed download -> {status}, {len(data)} bytes"
    print("7. operator complete + download OK")
    print("ALL QUEUE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
