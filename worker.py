#!/usr/bin/env python3
"""muse-video-tool worker v0.1 — Muse-only video pipeline via muse2api.

Flow: scenes JSON -> scene image (muse-image; later scenes reuse the first
scene image as a reference to keep the character) -> image-to-video
(muse-video, image = first frame) -> download clips -> ffmpeg assemble to a
vertical phone-safe MP4.

Stdlib only. Against the mock driver this validates orchestration (API calls,
polling, downloads, job state); mock media itself is placeholder bytes, so
assembly is validated separately with --test-clips (ffmpeg testsrc clips).

Scenes file format (JSON list):
  [{"prompt": "A turtle walks in a garden", "caption": "Rùa đi dạo"}]
Caption defaults to prompt when omitted.

Usage:
  python3 worker.py --scenes scenes.json --out out.mp4
  python3 worker.py --scenes scenes.json --out out.mp4 --skip-assemble
  python3 worker.py --scenes scenes.json --out out.mp4 --test-clips
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error


class Gateway:
    def __init__(self, base, key):
        self.base = base.rstrip("/")
        self.key = key

    def req(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, data=data, method=method)
        r.add_header("Authorization", "Bearer " + self.key)
        if data:
            r.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(r, timeout=120) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path} -> HTTP {e.code}: "
                               f"{e.read().decode()[:300]}")

    def chat(self, messages, model="muse-chat"):
        return self.req("POST", "/v1/chat/completions",
                        {"model": model, "messages": messages, "stream": False})

    def image(self, prompt, size="9:16", reference_url=None):
        body = {"prompt": prompt, "size": size}
        if reference_url:
            body["image"] = reference_url
        return self.req("POST", "/v1/images/generations", body)

    def video_create(self, prompt, duration=5, size="9:16", image_url=None):
        body = {"prompt": prompt, "duration": duration, "size": size}
        if image_url:
            body["image"] = image_url
        return self.req("POST", "/v1/videos", body)

    def video_poll(self, task_id, interval=10, timeout=1800):
        deadline = time.time() + timeout
        while True:
            task = self.req("GET", f"/v1/videos/{task_id}")
            status = task.get("status")
            if status == "succeeded":
                return task["result"]["url"]
            if status in ("failed", "error", "cancelled"):
                raise RuntimeError(f"video task {task_id} -> {status}: "
                                   f"{task.get('error')}")
            if time.time() > deadline:
                raise RuntimeError(f"video task {task_id} timed out")
            print(f"  poll {task_id}: {status} "
                  f"({task.get('progress', 0)}%)", flush=True)
            time.sleep(interval)

    def download(self, url, dest):
        req = urllib.request.Request(url)
        req.add_header("Authorization", "Bearer " + self.key)
        with urllib.request.urlopen(req, timeout=300) as resp, \
                open(dest, "wb") as f:
            f.write(resp.read())
        return dest


def data_url(path):
    """File -> data URL. The gateway SSRF guard rejects loopback URLs, so
    images are passed as data URLs instead of gateway media URLs."""
    import base64
    import mimetypes
    mime, _ = mimetypes.guess_type(path)
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime or 'image/png'};base64,{b64}"


def save_state(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def build_srt(captions, durations):
    """captions: list of text; durations: seconds per scene."""
    lines, t = [], 0.0
    for i, (cap, dur) in enumerate(zip(captions, durations), 1):
        def ts(sec):
            h, m = divmod(int(sec), 3600)
            m, s = divmod(m, 60)
            ms = int((sec - int(sec)) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
        lines.append(f"{i}\n{ts(t)} --> {ts(t + dur)}\n{cap}\n")
        t += dur
    return "\n".join(lines)


def assemble(clips, captions, durations, out_path):
    """Concat clips -> 1080x1920 30fps, silent AAC, mov_text subtitles."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    srt_path = out_path + ".srt"
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(build_srt(captions, durations))
    total = sum(durations)
    n = len(clips)
    cmd = ["ffmpeg", "-y"]
    for c in clips:
        cmd += ["-i", c]
    cmd += ["-f", "lavfi", "-t", str(total), "-i",
            "anullsrc=r=48000:cl=stereo"]
    cmd += ["-i", srt_path]
    filt = []
    for i in range(n):
        filt.append(f"[{i}:v]scale=1080:1920:force_original_aspect_ratio="
                    f"increase,crop=1080:1920,fps=30,format=yuv420p[v{i}]")
    filt.append("".join(f"[v{i}]" for i in range(n)) +
                f"concat=n={n}:v=1:a=0[vout]")
    cmd += ["-filter_complex", ";".join(filt),
            "-map", "[vout]", "-map", f"{n}:a", "-map", f"{n+1}:s",
            "-c:v", "libx264", "-profile:v", "high",
            "-level", "4.0", "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-c:s", "mov_text", "-movflags", "+faststart",
            "-video_track_timescale", "15360", out_path]
    print("  ffmpeg:", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("  ffmpeg with subtitles failed, retrying without them:",
              flush=True)
        print("  " + "\n  ".join(r.stderr.strip().splitlines()[-5:]),
              flush=True)
        cmd2 = [c for c in cmd]
        # Drop the srt input (last -i before filter) and subtitle map/codec.
        srt_idx = cmd2.index(srt_path)
        del cmd2[srt_idx - 1:srt_idx + 1]
        cmd2.remove(f"{n+1}:s")
        cmd2.remove("-c:s")
        cmd2.remove("mov_text")
        subprocess.run(cmd2, check=True, capture_output=True, text=True)
    return out_path


def make_test_clip(path, duration, text):
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i",
           f"testsrc=size=1080x1920:rate=30:duration={duration}",
           "-vf", f"drawtext=text='{text}':fontsize=64:fontcolor=white:"
                  "x=(w-text_w)/2:y=(h-text_h)/2",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        # drawtext needs libfreetype; fall back to plain testsrc.
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i",
               f"testsrc=size=1080x1920:rate=30:duration={duration}",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", path]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", required=True, help="JSON list of scenes")
    ap.add_argument("--out", required=True, help="output MP4 path")
    ap.add_argument("--gateway", default="http://127.0.0.1:18610")
    ap.add_argument("--key", default="testkey-local")
    ap.add_argument("--duration", type=int, default=5,
                    help="seconds per scene video")
    ap.add_argument("--size", default="9:16")
    ap.add_argument("--skip-assemble", action="store_true",
                    help="stop after downloading clips")
    ap.add_argument("--test-clips", action="store_true",
                    help="assemble from ffmpeg testsrc clips, no gateway")
    args = ap.parse_args()

    with open(args.scenes, encoding="utf-8") as f:
        scenes = json.load(f)
    assert isinstance(scenes, list) and scenes, "scenes must be a non-empty list"
    for s in scenes:
        assert "prompt" in s, "each scene needs a 'prompt'"

    proj_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(proj_dir, exist_ok=True)
    state_path = os.path.join(proj_dir, "job.json")
    state = {"status": "started", "scenes": []}
    save_state(state_path, state)

    gw = Gateway(args.gateway, args.key)
    clips, captions, durations = [], [], []
    ref_image = None
    for i, scene in enumerate(scenes):
        print(f"[{i+1}/{len(scenes)}] {scene['prompt']}", flush=True)
        entry = {"prompt": scene["prompt"]}
        if args.test_clips:
            clip = os.path.join(proj_dir, f"clip{i}.mp4")
            make_test_clip(clip, args.duration, f"Scene {i+1}")
            entry["clip"] = clip
        else:
            img = gw.image(scene["prompt"], size=args.size,
                           reference_url=ref_image)
            img_url = img["data"][0]["url"]
            entry["image_url"] = img_url
            ext = os.path.splitext(img_url.split("?")[0])[1] or ".png"
            img_file = os.path.join(proj_dir, f"scene{i}{ext}")
            gw.download(img_url, img_file)
            entry["image_file"] = img_file
            img_data = data_url(img_file)
            if ref_image is None:
                ref_image = img_data
            print(f"  image: {img_url} -> {img_file}", flush=True)
            task = gw.video_create(scene["prompt"], duration=args.duration,
                                   size=args.size, image_url=img_data)
            print(f"  video task: {task['id']} ({task.get('status')})",
                  flush=True)
            video_url = gw.video_poll(task["id"])
            print(f"  video: {video_url}", flush=True)
            clip = os.path.join(proj_dir, f"clip{i}.mp4")
            gw.download(video_url, clip)
            entry["video_url"] = video_url
            entry["clip"] = clip
        clips.append(entry["clip"])
        captions.append(scene.get("caption") or scene["prompt"])
        durations.append(args.duration)
        state["scenes"].append(entry)
        save_state(state_path, state)

    if args.skip_assemble:
        state["status"] = "downloaded"
        save_state(state_path, state)
        print(f"OK: clips downloaded, state at {state_path}")
        return 0

    print("Assembling...", flush=True)
    assemble(clips, captions, durations, args.out)
    state["status"] = "done"
    state["output"] = os.path.abspath(args.out)
    save_state(state_path, state)
    print(f"OK: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
