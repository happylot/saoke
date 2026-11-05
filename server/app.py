"""SaoKe WSGI API with SQLite persistence and cookie authentication."""
import hashlib
from contextlib import contextmanager
import hmac
from http.cookies import SimpleCookie
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
EMPTY = {'meta': {}, 'balance': '0.00', 'cashback': '0', 'statement': {}, 'cards': [], 'txns': []}
MAX_BODY = 2 * 1024 * 1024
SESSION_AGE = 12 * 60 * 60
ID = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'


def password_matches(password, encoded):
    try:
        algorithm, iterations, salt, expected = encoded.split('$')
        if algorithm != 'pbkdf2_sha256':
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), int(iterations)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def validate_state(data):
    if not isinstance(data, dict):
        raise APIError(400, 'Dữ liệu không hợp lệ.')

    def text(value, limit=4000):
        if not isinstance(value, str) or len(value) > limit:
            raise APIError(400, 'Nội dung quá dài hoặc không hợp lệ.')
        return value

    def identifier(value):
        if not isinstance(value, str) or not ID.fullmatch(value):
            raise APIError(400, 'Mã thẻ hoặc giao dịch không hợp lệ.')
        return value

    def mapping(value):
        if not isinstance(value, dict) or len(value) > 30:
            raise APIError(400, 'Thông tin sao kê không hợp lệ.')
        return {text(k, 64): text(v) for k, v in value.items()}

    def money(value):
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise APIError(400, 'Số tiền không hợp lệ.')
        try:
            number = float(value)
        except (ValueError, OverflowError):
            raise APIError(400, 'Số tiền không hợp lệ.') from None
        if not math.isfinite(number) or abs(number) > 1e15:
            raise APIError(400, 'Số tiền không hợp lệ.')
        return text(str(value), 64)

    cards, txns = data.get('cards', []), data.get('txns', [])
    if not isinstance(cards, list) or not isinstance(txns, list) or len(cards) > 1000 or len(txns) > 10000:
        raise APIError(400, 'Số lượng thẻ hoặc giao dịch vượt giới hạn.')
    result = {'balance': money(data.get('balance', '0.00')), 'cashback': money(data.get('cashback', '0')),
              'meta': mapping(data.get('meta', {})), 'statement': mapping(data.get('statement', {})),
              'cards': [], 'txns': []}
    seen = set()
    for card in cards:
        if not isinstance(card, dict):
            raise APIError(400, 'Thẻ không hợp lệ.')
        card_id = identifier(card.get('id'))
        last4 = text(card.get('last4', ''), 4)
        if last4 and not re.fullmatch(r'\d{4}', last4):
            raise APIError(400, 'Nhập đúng 4 số cuối thẻ.')
        if card_id in seen:
            raise APIError(400, 'Mã thẻ bị trùng.')
        seen.add(card_id)
        result['cards'].append({'id': card_id, 'last4': last4, 'name': text(card.get('name', ''))})
    seen.clear()
    for txn in txns:
        if not isinstance(txn, dict):
            raise APIError(400, 'Giao dịch không hợp lệ.')
        item = {'id': identifier(txn.get('id')), 'amount': money(txn.get('amount', 0))}
        if item['id'] in seen:
            raise APIError(400, 'Mã giao dịch bị trùng.')
        seen.add(item['id'])
        for field in ['card', 'name', 'desc', 'merchant', 'date', 'time', 'source']:
            item[field] = text(txn.get(field, ''))
        item['status'] = text(txn.get('status', 'success'), 20)
        if item['status'] not in {'success', 'pending', 'failed', 'refunded'}:
            raise APIError(400, 'Trạng thái giao dịch không hợp lệ.')
        result['txns'].append(item)
    return result


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL DEFAULT 0,
                    balance TEXT NOT NULL, cashback TEXT NOT NULL, meta TEXT NOT NULL, statement TEXT NOT NULL);
                INSERT OR IGNORE INTO settings VALUES(1,0,'0.00','0','{}','{}');
                CREATE TABLE IF NOT EXISTS cards (
                    id TEXT PRIMARY KEY, position INTEGER NOT NULL, last4 TEXT NOT NULL, name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS transactions (
                    id TEXT PRIMARY KEY, position INTEGER NOT NULL, card TEXT NOT NULL,
                    name TEXT NOT NULL, description TEXT NOT NULL, merchant TEXT NOT NULL,
                    date TEXT NOT NULL, time TEXT NOT NULL, amount TEXT NOT NULL,
                    status TEXT NOT NULL, source TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, expires INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS login_attempts (
                    address TEXT PRIMARY KEY, count INTEGER NOT NULL, started INTEGER NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def read(self):
        with self.connect() as db:
            db.execute('BEGIN')
            row = db.execute('SELECT * FROM settings WHERE id=1').fetchone()
            cards = [{k: c[k] for k in ['id', 'last4', 'name']}
                     for c in db.execute('SELECT * FROM cards ORDER BY position')]
            txns = []
            for t in db.execute('SELECT * FROM transactions ORDER BY position'):
                txn = {k: t[k] for k in ['id', 'card', 'name', 'merchant', 'date', 'time', 'status', 'source']}
                txn.update(desc=t['description'], amount=float(t['amount']))
                txns.append(txn)
            return {'revision': row['revision'], 'data': {
                'balance': row['balance'], 'cashback': row['cashback'], 'meta': json.loads(row['meta']),
                'statement': json.loads(row['statement']), 'cards': cards, 'txns': txns}}

    def write(self, data, expected_revision):
        data = validate_state(data)
        if type(expected_revision) is not int or expected_revision < 0:
            raise APIError(400, 'Phiên bản dữ liệu không hợp lệ.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            revision = db.execute('SELECT revision FROM settings WHERE id=1').fetchone()[0]
            if revision != expected_revision:
                raise APIError(409, 'Dữ liệu đã đổi ở cửa sổ khác. Tải lại trước khi chỉnh sửa tiếp.')
            data['meta']['updated'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            db.execute('UPDATE settings SET revision=?,balance=?,cashback=?,meta=?,statement=? WHERE id=1',
                       (revision + 1, data['balance'], data['cashback'], json.dumps(data['meta']), json.dumps(data['statement'])))
            db.execute('DELETE FROM cards')
            db.executemany('INSERT INTO cards VALUES(?,?,?,?)',
                           [(c['id'], i, c['last4'], c['name']) for i, c in enumerate(data['cards'])])
            db.execute('DELETE FROM transactions')
            db.executemany('INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?,?)', [
                (t['id'], i, t['card'], t['name'], t['desc'], t['merchant'], t['date'], t['time'],
                 t['amount'], t['status'], t['source']) for i, t in enumerate(data['txns'])])
            return revision + 1


class Application:
    def __init__(self, db_path=None, username=None, encoded_password=None, origin=None):
        self.store = Store(db_path or os.environ.get('SAOKE_DB', str(ROOT / '.local/saoke.sqlite3')))
        self.username = username or os.environ.get('SAOKE_USER', 'admin')
        self.password = encoded_password or os.environ.get('SAOKE_PASSWORD_HASH', '')
        self.origin = origin or os.environ.get('SAOKE_ORIGIN', 'http://localhost:8765')
        self.secure = self.origin.startswith('https://')
        version = ROOT / 'version.txt'
        self.revision = version.read_text().strip() if version.exists() else 'development'

    def body(self, env):
        if env.get('CONTENT_TYPE', '').split(';')[0] != 'application/json':
            raise APIError(415, 'Yêu cầu không hợp lệ.')
        try:
            length = int(env.get('CONTENT_LENGTH', '0'))
            if length < 1 or length > MAX_BODY:
                raise APIError(413, 'Dữ liệu quá lớn.')
            return json.loads(env['wsgi.input'].read(length))
        except (ValueError, UnicodeDecodeError):
            raise APIError(400, 'Dữ liệu không hợp lệ.') from None

    def token(self, env):
        cookie = SimpleCookie()
        try:
            cookie.load(env.get('HTTP_COOKIE', ''))
            token = cookie['sk_session'].value if 'sk_session' in cookie else ''
        except Exception:
            token = ''
        return hashlib.sha256(token.encode()).hexdigest()

    def require_session(self, env):
        with self.store.connect() as db:
            session = db.execute('SELECT expires FROM sessions WHERE token=?', (self.token(env),)).fetchone()
        if not session or session['expires'] <= time.time():
            raise APIError(401, 'Vui lòng đăng nhập.')

    def cookie(self, value, age=SESSION_AGE):
        return ('Set-Cookie', f'sk_session={value}; HttpOnly; SameSite=Strict; Path=/; Max-Age={age}'
                + ('; Secure' if self.secure else ''))

    def route(self, env):
        method, path = env['REQUEST_METHOD'], env['PATH_INFO']
        if method == 'GET' and path == '/api/health':
            with self.store.connect() as db:
                db.execute('SELECT revision FROM settings WHERE id=1').fetchone()
            return 200, {'status': 'ok', 'version': self.revision}, []
        if method in {'POST', 'PUT', 'DELETE'} and env.get('HTTP_ORIGIN') != self.origin:
            raise APIError(403, 'Nguồn yêu cầu không hợp lệ.')
        if method == 'POST' and path == '/api/login':
            data = self.body(env)
            if not isinstance(data, dict) or not isinstance(data.get('password'), str) or len(data['password']) > 1024:
                raise APIError(400, 'Thông tin đăng nhập không hợp lệ.')
            address = env.get('HTTP_X_REAL_IP', env.get('REMOTE_ADDR', 'unknown'))[:64]
            now = int(time.time())
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                attempt = db.execute('SELECT * FROM login_attempts WHERE address=?', (address,)).fetchone()
                if attempt and now - attempt['started'] < 900 and attempt['count'] >= 10:
                    raise APIError(429, 'Đăng nhập sai nhiều lần. Vui lòng thử lại sau 15 phút.')
                count = attempt['count'] + 1 if attempt and now - attempt['started'] < 900 else 1
                started = attempt['started'] if count > 1 else now
                db.execute('INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)', (address, count, started))
            valid = password_matches(data['password'], self.password)
            if not valid or data.get('username') != self.username:
                raise APIError(401, 'Tên đăng nhập hoặc mật khẩu không đúng.')
            token = secrets.token_urlsafe(32)
            with self.store.connect() as db:
                db.execute('DELETE FROM login_attempts WHERE address=?', (address,))
                db.execute('DELETE FROM sessions WHERE expires<=?', (now,))
                db.execute('INSERT INTO sessions VALUES(?,?)', (hashlib.sha256(token.encode()).hexdigest(), now + SESSION_AGE))
            return 200, {'username': self.username}, [self.cookie(token)]
        self.require_session(env)
        if method == 'POST' and path == '/api/logout':
            with self.store.connect() as db:
                db.execute('DELETE FROM sessions WHERE token=?', (self.token(env),))
            return 200, {'ok': True}, [self.cookie('', 0)]
        if method == 'GET' and path == '/api/state':
            return 200, self.store.read(), []
        if method == 'PUT' and path == '/api/state':
            data = self.body(env)
            if not isinstance(data, dict):
                raise APIError(400, 'Dữ liệu không hợp lệ.')
            revision = self.store.write(data.get('data'), data.get('revision'))
            return 200, {'revision': revision}, []
        raise APIError(404, 'Không tìm thấy yêu cầu.')

    def __call__(self, env, start_response):
        if env['REQUEST_METHOD'] == 'GET' and env['PATH_INFO'] in {'/', '/index.html'}:
            body = (ROOT / 'index.html').read_bytes()
            start_response('200 OK', [('Content-Type', 'text/html; charset=utf-8'), ('Cache-Control', 'no-store')])
            return [body]
        try:
            status, result, extra = self.route(env)
        except APIError as error:
            status, result, extra = error.status, {'error': error.message}, []
        except Exception:
            import traceback
            traceback.print_exc(file=sys.stderr)
            status, result, extra = 500, {'error': 'Máy chủ chưa lưu được dữ liệu. Vui lòng thử lại.'}, []
        body = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
        reasons = {200: 'OK', 400: 'Bad Request', 401: 'Unauthorized', 403: 'Forbidden',
                   404: 'Not Found', 409: 'Conflict', 413: 'Payload Too Large',
                   415: 'Unsupported Media Type', 429: 'Too Many Requests', 500: 'Internal Server Error'}
        start_response(f'{status} {reasons[status]}', [('Content-Type', 'application/json; charset=utf-8'),
                       ('Content-Length', str(len(body))), ('Cache-Control', 'no-store'),
                       ('X-Content-Type-Options', 'nosniff')] + extra)
        return [body]


_application = None


def application(environ, start_response):
    global _application
    if _application is None:
        _application = Application()
    return _application(environ, start_response)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'import':
        app = Application()
        state = app.store.read()
        if state['revision'] != 0:
            raise SystemExit('Database already initialized; refusing to overwrite it.')
        imported = json.loads(Path(sys.argv[2]).read_text())
        app.store.write(imported, 0)
        print(f"Imported {len(imported.get('cards', []))} cards and {len(imported.get('txns', []))} transactions.")
    else:
        if not os.environ.get('SAOKE_PASSWORD_HASH'):
            import getpass
            os.environ['SAOKE_PASSWORD_HASH'] = password_hash(getpass.getpass('Set local admin password: '))
        from wsgiref.simple_server import make_server
        parsed = urlsplit(os.environ.get('SAOKE_ORIGIN', 'http://localhost:8765'))
        with make_server('127.0.0.1', parsed.port or 8765, application) as httpd:
            print(f'SaoKe: {parsed.geturl()} (user: {os.environ.get("SAOKE_USER", "admin")})')
            httpd.serve_forever()
