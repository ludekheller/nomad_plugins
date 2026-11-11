"""Table (CSV) of the DSC results of a NOMAD project: one row per DSC entry.

Command line (scripts/dsc_results_csv.py):
    python dsc_results_csv.py PROJECT_ID [--folder FOLDER] [-o results.csv] [--url ...]

--folder limits the table to the DSC entries in that folder of the project and its sub-folders,
e.g. --folder 3dprinting_params_mapping_001/DSC

PROJECT_ID is the upload id shown on the project page (or by `nomad admin uploads ls`). You are asked
for your NOMAD user name and password (or set NOMAD_TOKEN to an access token). Only `requests` is
needed. Temperatures in °C, enthalpies in J/g.
"""

import argparse
import csv
import getpass
import os

DSC = 'nomad_dsc_trios.schema_packages.dsc.DSC_SMA'
TEMPS = ['Ms', 'Mf', 'As', 'Af', 'Rs', 'Rf', 'peak_temperature_cooling', 'peak_temperature_heating']
NUMBERED = [f'{a}{i}' for i in (1, 2, 3) for a in ('Ms', 'Mf', 'As', 'Af')]
COLUMNS = (['project', 'mainfile', 'entry_name', 'specimen_id', 'material', 'mode', 'cycle']
           + TEMPS + NUMBERED + ['enthalpy_cooling', 'enthalpy_heating', 'n_peaks_cooling', 'n_peaks_heating',
                                 'evaluation_method', 'flags', 'messages', 'entry_id'])


def row(entry):
    """One CSV row from an /entries/archive/query result."""
    arch = entry.get('archive') or {}
    meta, data = arch.get('metadata') or {}, arch.get('data') or {}
    res, ev = data.get('transformation_results') or {}, data.get('evaluation') or {}
    spec = data.get('specimen') or {}
    peaks = ev.get('peaks') or []
    r = {'project': meta.get('upload_name'), 'mainfile': meta.get('mainfile'), 'entry_name': meta.get('entry_name'),
         'entry_id': entry.get('entry_id'), 'specimen_id': spec.get('specimen_id'), 'material': spec.get('material'),
         'mode': ev.get('mode') or 'off', 'cycle': ev.get('cycle'),
         'evaluation_method': res.get('evaluation_method'),
         'n_peaks_cooling': sum(p.get('ramp') == 'cooling' for p in peaks) if ev else None,
         'n_peaks_heating': sum(p.get('ramp') == 'heating' for p in peaks) if ev else None,
         'flags': '; '.join(f"{p.get('label')}: {p['flags']}" for p in peaks if p.get('flags')) or None,
         'messages': (ev.get('messages') or '').replace('\n', '; ') or None}
    for k in TEMPS + NUMBERED + ['enthalpy_cooling', 'enthalpy_heating']:
        v = res.get(k)
        r[k] = round(v, 3) if isinstance(v, (int, float)) else None
    return r


def fetch(url, upload_id, headers, folder=''):
    import requests  # noqa: PLC0415

    body = {'owner': 'visible', 'query': {'upload_id': upload_id, 'section_defs.definition_qualified_name': DSC},
            'required': {'metadata': {'entry_name': '*', 'mainfile': '*', 'upload_name': '*'},
                         'data': {'specimen': '*', 'transformation_results': '*',
                                  'evaluation': {'mode': '*', 'cycle': '*', 'messages': '*', 'peaks': '*'}}},
            'pagination': {'page_size': 50, 'order_by': 'mainfile'}}
    rows = []
    while True:
        resp = requests.post(f'{url}/entries/archive/query', json=body, headers=headers, timeout=120)
        resp.raise_for_status()
        js = resp.json()
        rows += [row(e) for e in js.get('data', [])]
        nxt = (js.get('pagination') or {}).get('next_page_after_value')
        if not nxt:
            folder = folder.strip('/')
            return [r for r in rows if not folder or (r['mainfile'] or '').startswith(folder + '/')]
        body['pagination']['page_after_value'] = nxt


def token(url):
    import requests  # noqa: PLC0415

    if os.environ.get('NOMAD_TOKEN'):
        return os.environ['NOMAD_TOKEN']
    user = input('NOMAD user name: ')
    pw = getpass.getpass('Password: ')
    resp = requests.post(f'{url}/auth/token', data={'username': user, 'password': pw}, timeout=60)
    resp.raise_for_status()
    return resp.json()['access_token']


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('project_id')
    ap.add_argument('--folder', default='', help='only entries in this folder (and its sub-folders)')
    ap.add_argument('-o', '--output', default=None, help='CSV file (default: dsc_results_<project id>.csv)')
    ap.add_argument('--url', default='http://nomad.fzu.cz/nomad-oasis/api/v1', help='NOMAD API base URL')
    a = ap.parse_args(argv)
    headers = {'Authorization': f'Bearer {token(a.url)}'}
    folder = a.folder.strip('/')
    rows = fetch(a.url.rstrip('/'), a.project_id, headers, folder)
    tag = f"{a.project_id}_{folder.replace('/', '_')}" if folder else a.project_id
    out = a.output or f'dsc_results_{tag}.csv'
    write_csv(rows, out)
    print(f'{len(rows)} DSC entries -> {out}')


def write_csv(rows, path):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

