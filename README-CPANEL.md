# MuseVideo — cach dua len host

## 1. Phan giao dien web (len cPanel duoc ngay)
- Upload toan bo thu muc `web/` (file index.html) len public_html.
- Mo bang trinh duyet la thay giao dien tao video.

## 2. Phan chay video (KHONG chay tren host share thuong)
- Server can: Python 3.12 + FFmpeg + chay tien trinh lau (server.py).
- Host share (cPanel) thuong khong co FFmpeg, khong chay daemon lau,
  khong chay duoc Chromium cua gateway sinh AI.
- Cach lam thuc te: giao dien o tren cPanel, o "Dia chi server" trong
  giao dien nhap dia chi cua may dang chay server.py (VPS, hoac
  Termux tren dien thoai). Server da bat CORS nen giao dien tu
  domain khac goi qua duoc.

## 3. Token rieng
- Copy `.env.example` thanh `.env`, dien token rieng vao.
- Giao dien nhap token do o o "Token rieng cua bo tool".
- Khong co token thi server tra 401.

## 4. Chay local de test
- `python3 server.py` (tu doc .env), mo http://127.0.0.1:18700/
- Test: `python3 test_web.py`

## 5. Docker (len VPS)
- `docker compose up -d --build` (gateway muse2api + tool).
