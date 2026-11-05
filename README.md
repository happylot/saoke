# saoke

Giao diện xem, chỉnh sửa và xuất lịch sử giao dịch, chạy bằng HTML/CSS/JavaScript.

Website: https://sk.zenify.cx

## Chạy trên máy cá nhân

Yêu cầu Node.js để kiểm tra mã nguồn, Python 3 để chạy HTTP server.

```sh
# Chỉ sao chép khi chưa có data.json để tránh ghi đè dữ liệu cá nhân.
test -f data.json || cp data.example.json data.json
python3 -m http.server 8765 --bind 127.0.0.1
```

Mở http://localhost:8765. Dùng **Mở JSON** để chọn dữ liệu cục bộ; trình duyệt
hỗ trợ File System Access API có thể lưu thay đổi vào file đã chọn. Website
không có backend lưu dữ liệu: **Lưu JSON** lưu file trên thiết bị của người dùng.

## CI/CD

- Push hoặc pull request vào `main`: kiểm tra cú pháp JavaScript và dữ liệu mẫu.
- Push vào `main` hoặc chạy workflow thủ công trên `main`: deploy production.
- Workflow: [CI / Deploy](https://github.com/happylot/saoke/actions/workflows/deploy.yml).
- Máy chủ: `14.225.7.175`, SSH cổng `1786`, tài khoản `saoke-deploy`.
- Nginx phục vụ `/var/www/saoke/current`; mỗi bản deploy có thư mục riêng trong
  `/var/www/saoke/releases`. Symlink được chuyển nguyên tử sau khi upload hoàn tất.
- Kiểm tra HTTPS sau deploy; tự quay về bản trước nếu kiểm tra trên máy chủ thất bại.
- Giữ năm bản gần nhất và bản liền trước để rollback.

Secrets của GitHub Actions (environment `production` chỉ deploy từ nhánh `main`):

| Secret | Nội dung |
| --- | --- |
| `SAOKE_SSH_KEY` | Khóa Ed25519 riêng cho tài khoản deploy |
| `SAOKE_KNOWN_HOSTS` | Host key đã xác minh của `[14.225.7.175]:1786` |

Khóa deploy chỉ gọi được `/usr/local/lib/saoke/receive.py`, không được mở shell,
forward port hoặc chạy lệnh tùy ý. Tài khoản deploy không có quyền sudo.
Cấu hình Nginx và script nhận bản deploy nằm trong `deploy/`; thay đổi các tệp
này cần quản trị viên cài lại trên máy chủ, workflow chỉ cập nhật website.

Kiểm tra và đóng gói thủ công:

```sh
bash scripts/package.sh
```

Gói deploy chỉ chứa `index.html`, `data.json` trống lấy từ `data.example.json` và
`version.txt` chứa commit SHA. `data.json` cá nhân, `Giaodich/`, chứng từ và bản
`mb-saoke.html` có thông tin ngân hàng nhúng được giữ cục bộ, không commit/deploy.
Trên website, dùng **Mở JSON** để làm việc với dữ liệu trên thiết bị của bạn.

## Quản trị máy chủ

Nginx vhost: `/etc/nginx/sites-available/sk.zenify.cx`.
Chứng chỉ: `/etc/letsencrypt/live/sk.zenify.cx/`, tự gia hạn bằng Certbot.
Deploy hook của Certbot kiểm tra rồi reload Nginx khi gia hạn.

Rollback (root, thay `<release>` bằng tên thư mục đã có):

```sh
ls -1t /var/www/saoke/releases
ln -s /var/www/saoke/releases/<release> /var/www/saoke/.rollback-next
mv -Tf /var/www/saoke/.rollback-next /var/www/saoke/current
curl -fsS https://sk.zenify.cx/version.txt
```
