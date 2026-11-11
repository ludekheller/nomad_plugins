"""Your NOMAD projects in Jupyter, by name.

    from nomad_dept18_jupyter import nomad

    nomad.projects()                                   # table: name, id, folder, published, entries
    f = nomad.path('NAVRATY_ROUDNICKA_3Dtisk_NiTi/3dprinting_params_mapping_001/DSC/niti_slm_hex1121.json.gz')
    nomad.find('niti_slm_hex1121*')                    # files by name (wildcards), in all projects
    p = nomad.project('NAVRATY_ROUDNICKA_3Dtisk_NiTi')
    p.folder                                           # the project's files (a normal folder)
    p.files('**/*.json.gz')                            # files of the project (glob)
    p.entries()                                        # all NOMAD entries: name, type, file
    e = p.entry('niti_slm_hex11/121')                  # by entry name, file name or entry id
    e.data.transformation_results.Ms                   # what NOMAD stored (computed values too)
    p.table('DSC_SMA', ['specimen.material', 'transformation_results.Ms'])
    nomad.links()                                      # ~/work/projects/<project name> -> project folder

Files: NOMAD mounts your unpublished projects (own or as co-author) under ~/uploads/<project id>;
`path`, `find` and `Project.files` use these folders directly (no login needed once the project
names are known). Files of other projects (published, or only shared for viewing) are downloaded
through the API into ~/work/.nomad_cache.

Names: the folder names are project ids; the names come from the NOMAD API (login once per session,
`nomad.login()`, asked automatically) and are remembered in ~/work/.nomad_projects.json, so later
sessions find projects by name without login. Writing into ~/uploads changes the project itself.
"""

import fnmatch
import getpass
import json
import os
import re
from pathlib import Path

HOME = Path(os.path.expanduser('~'))
UPLOADS = HOME / 'uploads'
WORK = HOME / 'work'
NAMES_FILE = WORK / '.nomad_projects.json'
CACHE = WORK / '.nomad_cache'
LINKS = WORK / 'projects'
API_CANDIDATES = ['http://nomad.fzu.cz/api', 'http://nomad.fzu.cz/nomad-oasis/api']
ID_LEN = 22  # NOMAD upload ids

_session = {'api': None, 'token': None}


# ------------------------------------------------------------------ API and login
def _requests():
    import requests  # noqa: PLC0415

    return requests


def api():
    """'<...>/api/v1' of the NOMAD API (NOMAD_CLIENT_URL, else the known addresses)."""
    if _session['api']:
        return _session['api']
    env = os.environ.get('NOMAD_CLIENT_URL')
    for base in ([env] if env else []) + [os.environ.get('DSC_NOMAD_API', '')] + API_CANDIDATES:
        if not base:
            continue
        url = base.rstrip('/') + ('' if base.rstrip('/').endswith('/v1') else '/v1')
        try:
            r = _requests().get(f'{url}/info', timeout=5)
            if r.ok and 'version' in r.json():
                _session['api'] = url
                return url
        except Exception:  # noqa: S112 (try the next address)
            continue
    raise RuntimeError('NOMAD API not reachable; set nomad.API_CANDIDATES or DSC_NOMAD_API')


def token():
    return _session['token'] or os.environ.get('NOMAD_CLIENT_ACCESS_TOKEN')


def login(user=None, password=None):
    """Log in to NOMAD for this session (asks for user name and password if not given)."""
    if user is None:
        user = input('NOMAD user name: ')
    if password is None:
        password = getpass.getpass('NOMAD password: ')
    r = _requests().post(f'{api()}/auth/token', timeout=30,
                         data={'grant_type': 'password', 'username': user, 'password': password})
    r.raise_for_status()
    _session['token'] = r.json()['access_token']
    return True


def _headers(ask=True):
    if token() is None and ask:
        login()
    return {'Authorization': f'Bearer {token()}'} if token() else {}


def _get(path, **params):
    r = _requests().get(f'{api()}/{path}', params=params, headers=_headers(), timeout=120)
    r.raise_for_status()
    return r


def _post(path, body):
    r = _requests().post(f'{api()}/{path}', json=body, headers=_headers(), timeout=300)
    r.raise_for_status()
    return r.json()


# ------------------------------------------------------------------ projects
def _mounted():
    """{upload id: folder} of the projects mounted under ~/uploads."""
    out = {}
    if UPLOADS.is_dir():
        for d in UPLOADS.iterdir():
            if d.is_dir() and len(d.name) >= ID_LEN:
                out[d.name[-ID_LEN:]] = d
    return out


def _load_names():
    try:
        return json.loads(NAMES_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save_names(names):
    try:
        WORK.mkdir(exist_ok=True)
        NAMES_FILE.write_text(json.dumps(names, indent=1, sort_keys=True))
    except OSError:
        pass


def _project_records(refresh=False):
    """[{'name', 'id', 'folder', 'published', 'entries'}] from the API (or the remembered names)."""
    names = _load_names()
    mounted = _mounted()
    recs = {}
    if refresh or token() or any(i not in names for i in mounted):
        page = 1
        while True:
            js = _get('uploads', page_size=200, page=page, include_all=False).json()
            for u in js.get('data', []):
                recs[u['upload_id']] = {'name': u.get('upload_name') or u['upload_id'], 'id': u['upload_id'],
                                        'published': bool(u.get('published')), 'entries': u.get('entries')}
            if page * 200 >= (js.get('pagination') or {}).get('total', 0):
                break
            page += 1
        names.update({i: r['name'] for i, r in recs.items()})
        _save_names(names)
    for i in mounted:
        recs.setdefault(i, {'name': names.get(i, i), 'id': i, 'published': False, 'entries': None})
    for r in recs.values():
        r['folder'] = mounted.get(r['id'])
    return sorted(recs.values(), key=lambda r: r['name'].lower())


def projects(refresh=False):
    """Table of your projects: name, id, folder (None if not mounted), published, entries."""
    import pandas as pd  # noqa: PLC0415

    return pd.DataFrame(_project_records(refresh), columns=['name', 'id', 'folder', 'published', 'entries'])


def project(name_or_id):
    """A project by its name (exact, else unique case-insensitive part) or id."""
    recs = _project_records()
    for key in ('id', 'name'):
        hit = [r for r in recs if r[key] == name_or_id]
        if hit:
            return Project(**hit[0])
    hit = [r for r in recs if name_or_id.lower() in r['name'].lower()]
    if len(hit) == 1:
        return Project(**hit[0])
    if not hit:
        hit = [r for r in _project_records(refresh=True) if r['name'] == name_or_id or r['id'] == name_or_id]
        if hit:
            return Project(**hit[0])
        raise KeyError(f'no project {name_or_id!r}; see nomad.projects()')
    raise KeyError(f"{name_or_id!r} matches several projects: {', '.join(r['name'] for r in hit)}")


def _split(spec):
    """'Project name/sub/file' -> (Project, 'sub/file'); the project name may contain '/'."""
    spec = str(spec).strip('/')
    parts = spec.split('/')
    names = {r['name']: r for r in _project_records()} | {r['id']: r for r in _project_records()}
    for i in range(len(parts), 0, -1):
        head = '/'.join(parts[:i])
        if head in names:
            return Project(**names[head]), '/'.join(parts[i:])
    return project(parts[0]), '/'.join(parts[1:])


def path(spec):
    """Local path of 'Project name/sub folder/file name' (downloaded if the project is not mounted)."""
    p, rel = _split(spec)
    return p.file(rel)


def find(pattern, project_name=None):
    """Files whose name matches `pattern` (wildcards * ?), in one project or in all mounted ones."""
    recs = [vars(project(project_name))] if project_name else _project_records()
    hits = []
    for r in recs:
        if r.get('folder'):
            hits += [f for f in Path(r['folder']).rglob('*') if f.is_file() and fnmatch.fnmatch(f.name, pattern)]
    return sorted(hits)


def links():
    """~/work/projects/<project name> -> mounted project folder (shows names in the file browser)."""
    LINKS.mkdir(parents=True, exist_ok=True)
    made = []
    for r in _project_records():
        if not r['folder']:
            continue
        link = LINKS / re.sub(r'[\\/:*?"<>|]', '_', r['name'])
        if link.is_symlink() or link.exists():
            if link.is_symlink() and os.readlink(link) == str(r['folder']):
                continue
            link = link.with_name(f"{link.name}_{r['id']}")
            if link.is_symlink():
                continue
        link.symlink_to(r['folder'], target_is_directory=True)
        made.append(link)
    return made


# ------------------------------------------------------------------ project, entries
class Project:
    def __init__(self, name, id, folder=None, published=False, entries=None):  # noqa: A002
        self.name, self.id, self.published, self.n_entries = name, id, published, entries
        self.folder = Path(folder) if folder else None

    def __repr__(self):
        where = self.folder or 'not mounted (files are downloaded on use)'
        return f'Project({self.name!r}, id={self.id}, folder={where})'

    def file(self, rel):
        """Local path of a file of the project (relative path inside the project)."""
        rel = str(rel).strip('/')
        if self.folder:
            f = self.folder / rel
            if not f.exists():
                raise FileNotFoundError(f'{rel} not in project {self.name}')
            return f
        f = CACHE / self.id / rel
        if not f.exists():
            r = _get(f'uploads/{self.id}/raw/{rel}')
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(r.content)
        return f

    def files(self, pattern='**/*'):
        """Files of the project matching a glob pattern (relative paths for unmounted projects)."""
        if self.folder:
            return sorted(f for f in self.folder.glob(pattern) if f.is_file())
        rels = []

        def walk(d):
            page = 1
            while True:
                js = _get(f'uploads/{self.id}/rawdir/{d}', page_size=1000, page=page).json()
                content = (js.get('directory_metadata') or {}).get('content', [])
                for c in content:
                    p = f"{d}/{c['name']}".strip('/')
                    if c.get('is_file'):
                        rels.append(p)
                    else:
                        walk(p)
                if len(content) < 1000:
                    return
                page += 1
        walk('')
        return sorted(r for r in rels if fnmatch.fnmatch(r, pattern) or fnmatch.fnmatch(r, pattern.replace('**/', '')))

    def entries(self, entry_type=None):
        """Table of the project's entries: entry_name, entry_type, mainfile, entry_id."""
        import pandas as pd  # noqa: PLC0415

        query = {'upload_id': self.id}
        if entry_type:
            query['entry_type'] = entry_type
        body = {'owner': 'visible', 'query': query,
                'required': {'include': ['entry_id', 'entry_name', 'entry_type', 'mainfile']},
                'pagination': {'page_size': 1000, 'order_by': 'mainfile'}}
        rows = []
        while True:
            js = _post('entries/query', body)
            rows += js.get('data', [])
            nxt = (js.get('pagination') or {}).get('next_page_after_value')
            if not nxt:
                break
            body['pagination']['page_after_value'] = nxt
        return pd.DataFrame(rows, columns=['entry_name', 'entry_type', 'mainfile', 'entry_id'])

    def entry(self, key):
        """Entry by entry name, main file (path or file name) or entry id."""
        df = self.entries()
        for col in ('entry_id', 'entry_name', 'mainfile'):
            hit = df[df[col] == key]
            if len(hit) == 1:
                return Entry(hit.iloc[0].entry_id, self)
        hit = df[df['mainfile'].str.endswith('/' + key) | (df['mainfile'] == key)]
        if len(hit) == 1:
            return Entry(hit.iloc[0].entry_id, self)
        if len(hit) > 1:
            raise KeyError(f'{key!r} matches several entries: {list(hit.mainfile)}')
        raise KeyError(f'no entry {key!r} in {self.name}')

    def table(self, entry_type, fields, extra=('entry_name', 'mainfile')):
        """DataFrame with the given archive fields ('data.' optional, dots for sub-sections)."""
        import pandas as pd  # noqa: PLC0415

        fields = [f if f.startswith(('data.', 'metadata.', 'results.')) else f'data.{f}' for f in fields]
        required = {'metadata': {'entry_name': '*', 'mainfile': '*'}}
        for f in fields:
            node = required
            parts = f.split('.')
            for p in parts[:-1]:
                node = node.setdefault(p, {}) if isinstance(node.get(p, {}), dict) else node
            node[parts[-1]] = '*'
        body = {'owner': 'visible', 'query': {'upload_id': self.id, 'entry_type': entry_type},
                'required': required, 'pagination': {'page_size': 100, 'order_by': 'mainfile'}}
        rows = []
        while True:
            js = _post('entries/archive/query', body)
            for e in js.get('data', []):
                a = e.get('archive') or {}
                row = {k: (a.get('metadata') or {}).get(k) for k in extra}
                for f in fields:
                    row[f.removeprefix('data.')] = _dig(a, f.split('.'))
                rows.append(row)
            nxt = (js.get('pagination') or {}).get('next_page_after_value')
            if not nxt:
                break
            body['pagination']['page_after_value'] = nxt
        return pd.DataFrame(rows)


def _dig(d, keys):
    for k in keys:
        if isinstance(d, list):
            d = [x.get(k) if isinstance(x, dict) else None for x in d]
        elif isinstance(d, dict):
            d = d.get(k)
        else:
            return None
    return d


class AttrDict(dict):
    """dict with attribute access (e.data.transformation_results.Ms); values in the units of the schema."""

    def __getattr__(self, k):
        try:
            v = self[k]
        except KeyError as e:
            raise AttributeError(k) from e
        return wrap(v)

    def __dir__(self):
        return list(self.keys())


def wrap(v):
    if isinstance(v, dict):
        return AttrDict(v)
    if isinstance(v, list):
        return [wrap(x) for x in v]
    return v


class Entry:
    def __init__(self, entry_id, project=None):
        self.id, self.project = entry_id, project
        self._archive = None

    @property
    def archive(self):
        """The whole archive as NOMAD stores it (metadata, data, results ...), as nested dicts."""
        if self._archive is None:
            self._archive = _get(f'entries/{self.id}/archive').json()['data']['archive']
        return self._archive

    @property
    def data(self):
        return wrap(self.archive.get('data', {}))

    @property
    def mainfile(self):
        return self.archive.get('metadata', {}).get('mainfile')

    def file(self, rel=None):
        """Local path of the entry's main file, or of a file next to it."""
        main = self.mainfile
        rel = main if rel is None else f'{os.path.dirname(main)}/{rel}'.strip('/')
        return self.project.file(rel)

    def section(self):
        """The archive as NOMAD sections (with units), if nomad-lab and the plugins are installed."""
        from nomad.datamodel import EntryArchive  # noqa: PLC0415

        return EntryArchive.m_from_dict(self.archive)

    def __repr__(self):
        md = self.archive.get('metadata', {})
        return f"Entry({md.get('entry_name')!r}, type={md.get('entry_type')}, file={md.get('mainfile')})"
