import copy
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from server.app import Application, EMPTY, password_hash

PASSWORD = 'test-only-strong-password'
HASH = password_hash(PASSWORD)
ORIGIN = 'https://test.example'


class APITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'app.sqlite3'
        self.app = Application(self.path, 'admin', HASH, ORIGIN)
        self.cookie = ''

    def request(self, path, method='GET', data=None, origin=ORIGIN):
        body = json.dumps(data).encode() if data is not None else b''
        env = {'REQUEST_METHOD': method, 'PATH_INFO': path, 'CONTENT_TYPE': 'application/json',
               'CONTENT_LENGTH': str(len(body)), 'wsgi.input': io.BytesIO(body),
               'HTTP_ORIGIN': origin, 'HTTP_COOKIE': self.cookie, 'REMOTE_ADDR': '127.0.0.1'}
        response = {}
        def start(status, headers):
            response.update(status=int(status.split()[0]), headers=dict(headers))
        result = json.loads(b''.join(self.app(env, start)))
        if 'Set-Cookie' in response['headers']:
            self.cookie = response['headers']['Set-Cookie'].split(';')[0]
        return response['status'], result, response['headers']

    def login(self):
        status, _, headers = self.request('/api/login', 'POST', {'username':'admin','password':PASSWORD})
        self.assertEqual(status, 200)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('Secure', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])

    def test_authentication_and_csrf(self):
        self.assertEqual(self.request('/api/state')[0], 401)
        self.assertEqual(self.request('/api/state','PUT',{'revision':0,'data':EMPTY})[0], 401)
        self.assertEqual(self.request('/api/login','POST',{'username':'admin','password':'wrong'})[0],401)
        self.login()
        self.assertEqual(self.request('/api/state','PUT',{'revision':0,'data':EMPTY},origin='https://evil.test')[0],403)
        self.assertEqual(self.request('/api/state')[0],200)

    def test_data_survives_new_backend_instance(self):
        self.login()
        data = copy.deepcopy(EMPTY)
        data.update(balance='123.45', cashback='2.00', statement={'holder':'Test User','opening':'100.00'})
        data['cards']=[{'id':'c1','last4':'1234','name':'Test Card'}]
        data['txns']=[{'id':'t1','card':'c1','name':'Test User','desc':'Test purchase','merchant':'Test Store',
                       'date':'05/11/2026','time':'12:30','amount':-12.34,'status':'success','source':'imported'}]
        self.assertEqual(self.request('/api/state','PUT',{'revision':0,'data':data})[:2],(200,{'revision':1}))
        self.app = Application(self.path,'admin',HASH,ORIGIN)
        status, result, _ = self.request('/api/state')
        self.assertEqual(status,200)
        self.assertEqual(result['data']['cards'],data['cards'])
        self.assertEqual(result['data']['txns'],data['txns'])
        self.assertEqual(result['data']['statement'],data['statement'])
        self.assertEqual(result['data']['balance'],'123.45')

    def test_conflict_does_not_overwrite_changes(self):
        self.login()
        data = {**EMPTY,'balance':'99.00'}
        self.assertEqual(self.request('/api/state','PUT',{'revision':0,'data':data})[0],200)
        self.assertEqual(self.request('/api/state','PUT',{'revision':0,'data':EMPTY})[0],409)
        self.assertEqual(self.request('/api/state')[1]['data']['balance'],'99.00')

    def test_validation_preserves_database(self):
        self.login()
        for invalid in [None, {**EMPTY,'balance':'NaN'}, {**EMPTY,'cards':[{'id':'../bad','last4':'1234'}]},
                        {**EMPTY,'txns':[{'id':'t1','amount':2,'status':'bad'}]}]:
            self.assertEqual(self.request('/api/state','PUT',{'revision':0,'data':invalid})[0],400)
            self.assertEqual(self.request('/api/state')[1]['revision'],0)

    def test_order_edit_and_delete_are_saved(self):
        self.login()
        data = copy.deepcopy(EMPTY)
        data['cards']=[{'id':'c1','last4':'1234','name':'One'}]
        data['txns']=[{'id':key,'amount':index,'card':'c1'} for index,key in enumerate(['t2','t1'])]
        self.assertEqual(self.request('/api/state','PUT',{'revision':0,'data':data})[0],200)
        state=self.request('/api/state')[1]
        self.assertEqual([t['id'] for t in state['data']['txns']],['t2','t1'])
        state['data']['txns'].pop(0)
        state['data']['txns'][0]['amount']=-42.50
        state['data']['cards']=[]
        self.assertEqual(self.request('/api/state','PUT',state)[0],200)
        saved=self.request('/api/state')[1]['data']
        self.assertEqual(saved['cards'],[])
        self.assertEqual(saved['txns'][0]['amount'],-42.5)
        self.assertEqual(len(saved['txns']),1)

    def test_logout_and_expired_session(self):
        self.login()
        token=self.cookie
        self.assertEqual(self.request('/api/logout','POST',{})[0],200)
        self.cookie=token
        self.assertEqual(self.request('/api/state')[0],401)
        self.login()
        with self.app.store.connect() as db:
            db.execute('UPDATE sessions SET expires=?',(int(time.time())-1,))
        self.assertEqual(self.request('/api/state')[0],401)

    def test_login_rate_limit(self):
        for _ in range(10):
            self.assertEqual(self.request('/api/login','POST',{'username':'admin','password':'wrong'})[0],401)
        self.assertEqual(self.request('/api/login','POST',{'username':'admin','password':PASSWORD})[0],429)


if __name__ == '__main__':
    unittest.main()
