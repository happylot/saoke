# saoke

Ứng dụng quản lý, chỉnh sửa và xuất lịch sử giao dịch tại [sk.zenify.cx](https://sk.zenify.cx).
Dữ liệu tự lưu vào SQLite trên máy chủ; giao diện yêu cầu đăng nhập.
Không cần mở hoặc lưu file JSON. Xuất CSV và PDF vẫn được hỗ trợ.

## Chạy cục bộ

Yêu cầu Python 3.9+; Node.js dùng để kiểm tra JavaScript.

```sh
python3 server/app.py
```

Đặt mật khẩu khi được hỏi, mở http://localhost:8765 và đăng nhập bằng `admin`.
Database cục bộ nằm ở `.local/saoke.sqlite3`, được loại khỏi Git.

## Lưu dữ liệu

- API `GET /api/state`, `PUT /api/state` đọc và ghi thẻ, giao dịch, số dư và thông tin sao kê.
- Tự lưu sau khi chỉnh sửa, có trạng thái đã lưu/chưa lưu và nút **Lưu ngay** để thử lại.
- Phiên bản dữ liệu ngăn các cửa sổ ghi đè thay đổi của nhau. Khi có xung đột,
  giao diện giữ thay đổi chưa lưu và yêu cầu tải lại.
- SQLite lưu thẻ và giao dịch trong các bảng riêng, giữ thứ tự hiển thị; cập nhật
  trong một transaction và dùng WAL. Database production: `/var/lib/saoke/saoke.sqlite3`.
- Database nằm ngoài thư mục release và được giữ lại khi deploy hoặc rollback.
- Cookie đăng nhập HttpOnly, Secure, SameSite=Strict; phiên đăng nhập có hạn 12 giờ.
  API kiểm tra Origin với yêu cầu ghi và giới hạn số lần đăng nhập sai.
- Mật khẩu được băm PBKDF2; cấu hình tài khoản nằm trong `/etc/saoke/saoke.env`.
  Thông tin đăng nhập ban đầu nằm trong `/etc/saoke/initial-login.txt` (chỉ root đọc được).

## CI/CD

[GitHub Actions](https://github.com/happylot/saoke/actions/workflows/deploy.yml)
kiểm tra backend, tự lưu trên giao diện và gói deploy với mỗi push/PR vào `main`.
Push `main` sẽ deploy; cũng có thể chạy workflow thủ công trên nhánh này.

Máy chủ `14.225.7.175`, SSH cổng `1786`. Khóa deploy riêng được mã hóa trong
`SAOKE_SSH_KEY`; `SAOKE_KNOWN_HOSTS` chứa host key đã xác minh. Environment
`production` chỉ nhận nhánh `main`.

Gói deploy chỉ có `index.html`, `server/app.py`, `version.txt`; không có dữ liệu,
chứng từ hay thông tin đăng nhập. Tài khoản `saoke-deploy` chỉ nhận gói qua forced
SSH command và restart/stop đúng service `saoke.service`. Backend chạy bằng
`saoke-app` với Gunicorn, chỉ lắng nghe `127.0.0.1:8175`, qua Nginx và HTTPS.
Mỗi release nằm trong `/var/www/saoke/releases`; symlink `current` được chuyển
nguyên tử. Deploy kiểm tra cả phiên bản giao diện và backend, tự rollback code
nếu kiểm tra thất bại, giữ năm release gần nhất cùng bản liền trước.

Kiểm tra cục bộ:

```sh
python3 -m unittest discover -s tests -v
node scripts/test-autosave.mjs
bash scripts/package.sh
```

## Quản trị

- Nginx: `/etc/nginx/sites-available/sk.zenify.cx`.
- Backend: `systemctl status saoke.service`, log: `journalctl -u saoke.service`.
- HTTPS dùng Certbot, có lịch tự gia hạn và hook reload Nginx.
- Database được sao lưu mỗi ngày lúc 02:15 theo giờ máy chủ, giữ bảy bản trong
  `/var/lib/saoke/backups`. Chạy thủ công: `systemctl start saoke-backup.service`.
  Các bản sao nằm trên cùng máy chủ; cần sao chép ra ngoài nếu cần phục hồi khi
  toàn bộ máy chủ bị mất.
- `deploy/setup-backend.sh` cài runtime, service và script deploy từ toàn bộ source
  bằng root; cấu hình hạ tầng cần quản trị viên cài lại khi thay đổi.

Rollback code (root, thay `<release>` bằng thư mục đã có):

```sh
ls -1t /var/www/saoke/releases
ln -s /var/www/saoke/releases/<release> /var/www/saoke/.rollback-next
mv -Tf /var/www/saoke/.rollback-next /var/www/saoke/current
systemctl restart saoke.service
curl -fsS https://sk.zenify.cx/api/health
```

Dữ liệu ban đầu từ file cục bộ đã được chuyển một lần qua SSH vào database.
File cục bộ, `Giaodich/`, `mb-saoke.html`, `.secrets/` và database không được commit.
Lệnh import chỉ chạy khi database chưa có dữ liệu và từ chối ghi đè database
đã được khởi tạo.
