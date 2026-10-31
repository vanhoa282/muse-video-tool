#!/usr/bin/env python3
"""Job server for muse-video-tool (stdlib only).

Operator-queue model (theo mo hinh dieu hanh cua Hoa):
  - Nguoi dung gui yeu cau tao video -> don hang vao trang dieu hanh,
    trang thai "cho_chay" (KHONG chay ngay).
  - Operator (nguoi dieu hanh) mo trang /admin, thay danh sach don,
    bam Chay tung don -> worker chay -> xong -> tai MP4.

  POST /jobs  {"scenes": [{"prompt": ..., "caption": ...}], "duration": 5,
               "mode": "gateway"|"test-clips"} -> {"id": ..., "status": "cho_chay"}
  GET  /jobs               -> danh sach don (moi nhat truoc)
  GET  /jobs/{id}          -> don hang (don + tien trinh chay)
  POST /jobs/{id}/run      -> operator bam chay don (chi chay tu cho_chay)
  GET  /jobs/{id}/download -> out.mp4 (404 until done)
  GET  /health             -> {"ok": true}
  GET  /                   -> web UI (web/index.html)
  GET  /admin              -> trang dieu hanh (web/admin.html)

Web UI + API are one unit: open the server URL in any browser and the
tool runs there. The UI sends X-Api-Key on every /jobs call.

Env: MUSE_GATEWAY_URL (default http://127.0.0.1:18610),
     MUSE_API_KEY (default testkey-local; key the worker uses on the
     gateway),
     MUSE_JOB_API_KEY (client token for the web UI; when set, /jobs
     routes require header X-Api-Key),
     MUSE_JOB_PORT (default 18700, or $PORT when set — Render injects
     $PORT, so the server listens on Render's port automatically).
A .env file next to this script (KEY=VALUE lines) is loaded first, so
tokens never need to travel on a command line.
"""

import datetime
import json
import os
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECTS = os.path.join(ROOT, "projects")
WEB = os.path.join(ROOT, "web")


def _load_dotenv():
    try:
        with open(os.path.join(ROOT, ".env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except FileNotFoundError:
        pass


_load_dotenv()
GATEWAY = os.environ.get("MUSE_GATEWAY_URL", "http://127.0.0.1:18610")
API_KEY = os.environ.get("MUSE_API_KEY", "testkey-local")
JOB_TOKEN = os.environ.get("MUSE_JOB_API_KEY", "")


def _order_view(job_dir):
    """Merged view of an order: request (order.json) + run progress
    (job.json, written by the worker). Old job dirs without order.json
    (created before the queue model) still display from job.json."""
    view = {"status": "cho_chay", "scenes": []}
    op = os.path.join(job_dir, "order.json")
    if os.path.exists(op):
        try:
            with open(op, encoding="utf-8") as f:
                view.update(json.load(f))
        except Exception:
            pass
    sp = os.path.join(job_dir, "job.json")
    if os.path.exists(sp):
        try:
            with open(sp, encoding="utf-8") as f:
                prog = json.load(f)
        except Exception:
            prog = {}
        st = prog.get("status")
        if st == "started":
            view["status"] = "dang_chay"
        elif st in ("done", "failed"):
            view["status"] = st
        if prog.get("scenes"):
            view["scenes"] = prog["scenes"]
        if prog.get("error"):
            view["error"] = prog["error"]
        if prog.get("output"):
            view["output"] = prog["output"]
    return view


def _list_orders():
    orders = []
    if not os.path.isdir(PROJECTS):
        return orders
    for job_id in sorted(os.listdir(PROJECTS)):
        job_dir = os.path.join(PROJECTS, job_id)
        if not os.path.isdir(job_dir):
            continue
        v = _order_view(job_dir)
        v["id"] = job_id
        orders.append(v)
    orders.sort(key=lambda o: (o.get("created", ""), o["id"]),
                reverse=True)
    return orders


def run_job(job_id, scenes, duration, mode):
    job_dir = os.path.join(PROJECTS, job_id)
    scenes_path = os.path.join(job_dir, "scenes.json")
    out_path = os.path.join(job_dir, "out.mp4")
    with open(scenes_path, "w", encoding="utf-8") as f:
        json.dump(scenes, f, ensure_ascii=False, indent=2)
    cmd = [sys.executable, os.path.join(ROOT, "worker.py"),
           "--scenes", scenes_path, "--out", out_path,
           "--gateway", GATEWAY, "--key", API_KEY,
           "--duration", str(duration)]
    if mode == "test-clips":
        cmd.append("--test-clips")
    r = subprocess.run(cmd, capture_output=True, text=True)
    state_path = os.path.join(job_dir, "job.json")
    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {"status": "started", "scenes": []}
    if r.returncode != 0 and state.get("status") != "done":
        state["status"] = "failed"
        state["error"] = (r.stderr or r.stdout or "")[-1000:]
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(
            obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, X-Api-Key")
        self.send_header("Access-Control-Allow-Methods",
                         "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _auth_ok(self):
        if not JOB_TOKEN:
            return True
        return self.headers.get("X-Api-Key") == JOB_TOKEN

    def do_OPTIONS(self):
        self._send(204, b"")

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/health":
            return self._send(200, {"ok": True})
        if p == "/":
            fp = os.path.join(WEB, "index.html")
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    return self._send(200, f.read(), "text/html")
            return self._send(404, {"error": "web UI not built"})
        if p == "/admin":
            fp = os.path.join(WEB, "admin.html")
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    return self._send(200, f.read(), "text/html")
            return self._send(404, {"error": "admin page not built"})
        parts = [unquote(x) for x in p.strip("/").split("/") if x]
        if parts == ["jobs"]:
            if not self._auth_ok():
                return self._send(401, {"error": "bad api key"})
            return self._send(200, {"orders": _list_orders()})
        if len(parts) == 2 and parts[0] == "jobs":
            if not self._auth_ok():
                return self._send(401, {"error": "bad api key"})
            job_dir = os.path.join(PROJECTS, parts[1])
            if os.path.isdir(job_dir):
                v = _order_view(job_dir)
                v["id"] = parts[1]
                return self._send(200, v)
            return self._send(404, {"error": "job not found"})
        if len(parts) == 3 and parts[0] == "jobs" \
                and parts[2] == "download":
            if not self._auth_ok():
                return self._send(401, {"error": "bad api key"})
            fp = os.path.join(PROJECTS, parts[1], "out.mp4")
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    return self._send(200, f.read(), "video/mp4")
            return self._send(404, {"error": "not ready"})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        p = urlparse(self.path).path
        parts = [unquote(x) for x in p.strip("/").split("/") if x]
        if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "run":
            if not self._auth_ok():
                return self._send(401, {"error": "bad api key"})
            job_dir = os.path.join(PROJECTS, parts[1])
            if not os.path.isdir(job_dir):
                return self._send(404, {"error": "job not found"})
            view = _order_view(job_dir)
            if view["status"] == "done":
                return self._send(200, {"id": parts[1], "status": "done"})
            if view["status"] == "dang_chay":
                return self._send(200, {"id": parts[1],
                                        "status": "dang_chay"})
            op = os.path.join(job_dir, "order.json")
            if not os.path.exists(op):
                return self._send(400, {"error": "order has no request"})
            with open(op, encoding="utf-8") as f:
                order = json.load(f)
            threading.Thread(
                target=run_job,
                args=(parts[1], order["scenes"], order["duration"],
                      order["mode"]),
                daemon=True).start()
            return self._send(200, {"id": parts[1],
                                    "status": "dang_chay"})
        if p != "/jobs":
            return self._send(404, {"error": "not found"})
        if not self._auth_ok():
            return self._send(401, {"error": "bad api key"})
        ln = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(ln).decode() or "{}")
        except Exception:
            return self._send(400, {"error": "bad json"})
        scenes = body.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            return self._send(400, {"error": "scenes must be a non-empty list"})
        try:
            duration = int(body.get("duration", 5))
        except Exception:
            return self._send(400, {"error": "bad duration"})
        mode = body.get("mode", "gateway")
        if mode not in ("gateway", "test-clips"):
            return self._send(400, {"error": "bad mode"})
        job_id = uuid.uuid4().hex[:12]
        job_dir = os.path.join(PROJECTS, job_id)
        os.makedirs(job_dir, exist_ok=True)
        with open(os.path.join(job_dir, "order.json"), "w",
                  encoding="utf-8") as f:
            json.dump({
                "status": "cho_chay",
                "scenes": scenes,
                "duration": duration,
                "mode": mode,
                "created": datetime.datetime.now().isoformat(
                    timespec="seconds"),
            }, f, ensure_ascii=False, indent=2)
        return self._send(200, {"id": job_id, "status": "cho_chay"})


if __name__ == "__main__":
    port = int(os.environ.get("MUSE_JOB_PORT")
               or os.environ.get("PORT", "18700"))
    print(f"muse-video job server on 0.0.0.0:{port} "
          f"(gateway {GATEWAY})", flush=True)
    print(f"Mo trinh duyet tren cung may nay: http://127.0.0.1:{port}/",
          flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
