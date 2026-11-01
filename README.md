# MuseVideo — tạo video dọc từ kịch bản

Ảnh + video do Muse AI sinh, ráp sẵn phụ đề, xuất MP4 dọc 1080x1920.

## Mô hình điều hành (hàng đợi đơn)
- Người dùng gửi yêu cầu ở trang chính (`/`) hoặc giao diện client kiểu
  FrameWeaver (`/client`: dự án, nhân vật, nhiều cảnh có thời lượng riêng)
  -> đơn vào trang điều hành ở trạng thái "Chờ chạy" (KHÔNG chạy ngay).
- Điều hành mở trang `/admin`, thấy danh sách đơn, bấm **Chạy** từng đơn.
  Đơn xong thì tải MP4 về giao.
- Đơn chế độ `operator` (từ trang client) KHÔNG tự chạy bằng worker — điều
  hành xử lý thủ công rồi đánh dấu xong, trang admin chỉ hiện "Chờ điều hành
  xử lý thủ công" thay cho nút Chạy.
- Token điều hành: cùng 1 token cho cả 2 trang (điền ở ô token).

## Chạy web UI (không cần cài app)
- Mở `web/index.html` bằng trình duyệt, hoặc chạy server rồi mở địa chỉ server.
- Nhập kịch bản từng dòng dạng: `lời thoại | prompt tiếng Anh`, bấm Tạo video,
  đơn sẽ vào trang điều hành chờ chạy.

## Chạy server (cần máy chạy Python + FFmpeg)
- Copy `.env.example` thành `.env`, điền token riêng vào.
- `python3 server.py` rồi mở http://127.0.0.1:18700/
- Test: `python3 test_web.py`

## Docker (lên VPS)
- `docker compose up -d --build` (gateway muse2api + tool).

## Lưu ý
- GitHub Pages chỉ chạy được phần giao diện tĩnh (`web/`).
  Phần chạy video (server.py + FFmpeg + sinh AI) cần một máy chạy
  tiến trình dài (VPS, hoặc Termux trên điện thoại).
- Không bao giờ commit file `.env` thật lên git.
