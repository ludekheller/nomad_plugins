"""nomad_dept18_jupyter.nomad against a small fake NOMAD API and fake mounted projects."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from nomad_dept18_jupyter import nomad

PID, OID = 'TG_S6zI2RMCID31b_3DG5g', 'Pub0000000000000000001'
UPLOADS = [{'upload_id': PID, 'upload_name': 'NAVRATY_ROUDNICKA_3Dtisk_NiTi', 'published': False, 'entries': 2},
           {'upload_id': OID, 'upload_name': 'Published DSC', 'published': True, 'entries': 1}]
ENTRIES = {PID: [{'entry_id': 'e1', 'entry_name': 'niti_slm_hex11/121', 'entry_type': 'DSC_SMA',
                  'mainfile': 'series/DSC/niti_slm_hex11121.archive.json'},
                 {'entry_id': 'e2', 'entry_name': 'dsc_evaluation.archive.json', 'entry_type': 'DSC_EvaluationSettings',
                  'mainfile': 'series/DSC/dsc_evaluation.archive.json'}]}
ARCHIVE = {'e1': {'metadata': {'entry_name': 'niti_slm_hex11/121', 'entry_type': 'DSC_SMA',
                               'mainfile': 'series/DSC/niti_slm_hex11121.archive.json'},
                  'data': {'specimen': {'material': 'NiTi'}, 'transformation_results': {'Ms': 7.18, 'Af': 52.2}}}}
RAW = {OID: {'data/run.csv': b'T,q\n1,2\n'}}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, ctype='application/json', code=200):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth(self):
        return self.headers.get('Authorization') == 'Bearer tok'

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        p = u.path.removeprefix('/api/v1/')
        if p == 'info':
            return self._send({'version': '2.0.0'})
        if not self._auth():
            return self._send({'detail': 'no'}, code=401)
        if p == 'uploads':
            return self._send({'data': UPLOADS, 'pagination': {'total': len(UPLOADS)}})
        if p.startswith('entries/') and p.endswith('/archive'):
            return self._send({'data': {'archive': ARCHIVE[p.split('/')[1]]}})
        if p.startswith(f'uploads/{OID}/raw/'):
            return self._send(RAW[OID][p.split('/raw/', 1)[1]], 'application/octet-stream')
        if p.startswith(f'uploads/{OID}/rawdir'):
            d = p.split('/rawdir', 1)[1].strip('/')
            content = [{'name': 'data', 'is_file': False}] if d == '' else [{'name': 'run.csv', 'is_file': True}]
            return self._send({'directory_metadata': {'content': content}})
        return self._send({'detail': p}, code=404)

    def do_POST(self):  # noqa: N802
        p = urlparse(self.path).path.removeprefix('/api/v1/')
        n = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(n).decode()
        if p == 'auth/token':
            form = parse_qs(raw)
            ok = form.get('username') == ['lheller'] and form.get('password') == ['pw']
            return self._send({'access_token': 'tok'} if ok else {'detail': 'bad'}, code=200 if ok else 401)
        if not self._auth():
            return self._send({'detail': 'no'}, code=401)
        body = json.loads(raw)
        if p == 'entries/query':
            return self._send({'data': ENTRIES.get(body['query']['upload_id'], []), 'pagination': {}})
        if p == 'entries/archive/query':
            q = body['query']
            data = [{'archive': ARCHIVE[e['entry_id']]} for e in ENTRIES.get(q['upload_id'], [])
                    if e['entry_type'] == q['entry_type'] and e['entry_id'] in ARCHIVE]
            return self._send({'data': data, 'pagination': {}})
        return self._send({'detail': p}, code=404)


@pytest.fixture
def env(tmp_path, monkeypatch):
    srv = HTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for k, v in {'UPLOADS': tmp_path / 'uploads', 'WORK': tmp_path / 'work',
                 'NAMES_FILE': tmp_path / 'work' / '.nomad_projects.json', 'CACHE': tmp_path / 'work' / '.cache',
                 'LINKS': tmp_path / 'work' / 'projects'}.items():
        monkeypatch.setattr(nomad, k, v)
    monkeypatch.setattr(nomad, 'API_CANDIDATES', [f'http://127.0.0.1:{srv.server_port}/api'])
    monkeypatch.setattr(nomad, '_session', {'api': None, 'token': None})
    monkeypatch.delenv('NOMAD_CLIENT_ACCESS_TOKEN', raising=False)
    monkeypatch.delenv('NOMAD_CLIENT_URL', raising=False)
    d = tmp_path / 'uploads' / PID / 'series' / 'DSC'
    d.mkdir(parents=True)
    (d / 'niti_slm_hex11121.json.gz').write_bytes(b'x')
    (d / 'niti_slm_hex11121.archive.json').write_text('{}')
    (tmp_path / 'work').mkdir()
    yield tmp_path
    srv.shutdown()


def test_names_paths_and_find(env, monkeypatch):
    nomad.login('lheller', 'pw')
    df = nomad.projects()
    assert list(df.name) == ['NAVRATY_ROUDNICKA_3Dtisk_NiTi', 'Published DSC']
    assert df.folder[0] == env / 'uploads' / PID and df.folder[1] is None
    f = nomad.path('NAVRATY_ROUDNICKA_3Dtisk_NiTi/series/DSC/niti_slm_hex11121.json.gz')
    assert f == env / 'uploads' / PID / 'series' / 'DSC' / 'niti_slm_hex11121.json.gz'
    assert nomad.find('niti_slm_hex11121*') == sorted((env / 'uploads' / PID / 'series' / 'DSC').glob('*'))
    assert nomad.project('roudnicka').id == PID  # unique part of the name, any case
    # names remembered: a new session finds the project by name without login
    monkeypatch.setattr(nomad, '_session', {'api': None, 'token': None})
    assert nomad.project('NAVRATY_ROUDNICKA_3Dtisk_NiTi').folder == env / 'uploads' / PID


def test_links(env):
    nomad.login('lheller', 'pw')
    (link,) = nomad.links()
    assert link.name == 'NAVRATY_ROUDNICKA_3Dtisk_NiTi' and link.resolve() == env / 'uploads' / PID
    assert (link / 'series' / 'DSC' / 'niti_slm_hex11121.json.gz').exists()
    assert nomad.links() == []  # already there


def test_unmounted_project_downloads(env):
    nomad.login('lheller', 'pw')
    p = nomad.project('Published DSC')
    assert p.files('**/*.csv') == ['data/run.csv']
    f = nomad.path('Published DSC/data/run.csv')
    assert f.read_bytes() == b'T,q\n1,2\n' and str(f).startswith(str(env / 'work'))


def test_entries_data_and_table(env):
    nomad.login('lheller', 'pw')
    p = nomad.project('NAVRATY_ROUDNICKA_3Dtisk_NiTi')
    assert list(p.entries().entry_type) == ['DSC_SMA', 'DSC_EvaluationSettings']
    e = p.entry('niti_slm_hex11121.archive.json')
    assert e.data.transformation_results.Ms == 7.18 and e.data.specimen.material == 'NiTi'
    assert e.file('niti_slm_hex11121.json.gz').name == 'niti_slm_hex11121.json.gz'
    t = p.table('DSC_SMA', ['specimen.material', 'transformation_results.Ms'])
    assert t.to_dict('records') == [{'entry_name': 'niti_slm_hex11/121',
                                     'mainfile': 'series/DSC/niti_slm_hex11121.archive.json',
                                     'specimen.material': 'NiTi', 'transformation_results.Ms': 7.18}]


def test_wrong_password(env):
    with pytest.raises(Exception):  # noqa: B017
        nomad.login('lheller', 'nope')
