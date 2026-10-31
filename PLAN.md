# muse-video-tool — bản rút gọn chỉ xài Muse (qua muse2api)

## Mục tiêu
Tool làm video kể chuyện dọc cho Hoà, chạy trên điện thoại Android (app Expo),
chỉ dùng Muse AI qua gateway muse2api — KHÔNG dùng Google Flow.

## Kiến trúc
```
App Expo (điện thoại)
  │ tạo project, nhập kịch bản, xem tiến trình, tải MP4 về máy
  ▼
Worker (chạy cùng máy với gateway, sau này là VPS)
  │ 1. Kịch bản → từng cảnh (prompt + caption)
  │ 2. muse-image: ảnh cảnh (cảnh sau dùng ảnh cảnh đầu làm tham chiếu giữ nhân vật)
  │ 3. muse-video: video từ ảnh đầu (image = first frame), clip ~5-8s
  │ 4. Tải clip về, ráp bằng FFmpeg → MP4 dọc phone-safe
  ▼
Gateway muse2api (FastAPI, OpenAI-compatible)
  │ /v1/chat/completions, /v1/images/generations, /v1/videos (+poll)
  ▼
Tài khoản Muse (browser driver, Chromium + CDP)
```

## Quyết định đã chốt
- Chỉ xài Muse, không Flow (Hoà chốt 2026-10-31).
- Gateway = muse2api repo `www222fff/muse2api` (Hoà chốt 2026-10-31 ~18:52).
- Đăng nhập bằng phiên Muse của Hoà — Hoà đã duyệt ("Api đăng nhập t duyệt").
- Phải là APP, không phải web (web không can thiệp được hệ thống thiết bị).
- Xuất dọc 1080x1920, 30fps, H.264 + AAC, faststart (đúng chuẩn phone-safe cũ).

## Trạng thái (2026-10-31)
- ✅ Gateway mock chạy tốt trên VM: health/models/chat/images/videos đều OK.
- ✅ Worker v0.1 (`worker.py`, chỉ dùng stdlib Python): gọi đủ endpoint, poll
  task, tải clip, ghi `job.json` theo từng bước.
- ⚠️ Mock media là dữ liệu giả (ảnh PNG 64x64, video MP4 16 byte không play
  được) → ráp FFmpeg KHÔNG test được bằng mock. Ráp được kiểm chứng bằng
  `--test-clips` (clip giả sinh bằng ffmpeg testsrc).
- ⏳ Chưa có: test live với tài khoản Muse thật (cần VPS + trình duyệt),
  app Expo, lời dẫn (Muse không có TTS — để giai đoạn sau), phụ đề cháy hình.

## Chạy thử (mock)
```
# Gateway mock (terminal 1)
cd ~/workspace/muse2api
MUSE2API_DRIVER=mock MUSE2API_API_KEY=testkey-local \
  MUSE2API_ADMIN_KEY=testkey-local .venv/bin/python -m muse2api

# Worker: chỉ test gọi API + tải file (không ráp)
python3 worker.py --scenes scenes-demo.json --out projects/demo/out.mp4 \
  --skip-assemble

# Worker: test ráp FFmpeg bằng clip giả (không cần gateway)
python3 worker.py --scenes scenes-demo.json --out projects/demo/out.mp4 \
  --test-clips
```

## Việc tiếp theo
1. Sếp duyệt thuê VPS (gói 4-4-40, 150k/tháng) → triển khai gateway live
   bằng Docker (Dockerfile đã có sẵn Chromium) + test live lần đầu.
2. Đưa phiên Muse vào gateway (cần trình duyệt desktop hoặc extension;
   điện thoại chưa có đường chắc chắn — tìm khi tới bước này).
3. Dựng app Expo: tạo project, nhập kịch bản, xem tiến trình, tải MP4.
4. Lời dẫn + phụ đề cháy hình (giai đoạn sau).
