"""Synthetic test data: a NiTi-like .epos, a .rrng range file and a dummy .hits."""
from pathlib import Path

import numpy as np

from nomad_apt.readers import EPOS_DTYPE

RRNG = """[Ions]
Number=3
Ion1=Ni
Ion2=Ti
Ion3=O
[Ranges]
Number=6
Range1=28.80 29.25 Vol:0.01094 Ni:1 Color:00AA00
Range2=29.80 30.25 Vol:0.01094 Ni:1 Color:00AA00
Range3=57.80 58.25 Vol:0.01094 Ni:1 Color:00AA00
Range4=23.30 23.70 Vol:0.01764 Ti:1 Color:3366FF
Range5=23.80 24.20 Vol:0.01764 Ti:1 Color:3366FF
Range6=31.80 32.20 Vol:0.02 Ti:1 O:1 Name:TiO Color:FF6600
"""
PEAKS = [(29.0, 0.30), (30.0, 0.12), (24.0, 0.35), (23.5, 0.05), (58.0, 0.06), (32.0, 0.04), (16.0, 0.03)]


def make(folder: Path, n=50_000, run='R6043_00349'):
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(1)
    w = np.array([p for _, p in PEAKS])
    which = rng.choice(len(PEAKS), size=n, p=w / w.sum())
    m = np.array([PEAKS[i][0] for i in which]) + rng.normal(0, 0.03, n)
    noise = rng.random(n) < 0.05
    m[noise] = rng.uniform(1, 80, noise.sum())
    e = np.zeros(n, dtype=EPOS_DTYPE)
    e['x'], e['y'], e['z'], e['m'] = rng.normal(0, 12, n), rng.normal(0, 12, n), np.linspace(0, 150, n), m
    e['vdc'] = np.linspace(3000, 7500, n)
    e['det_x'], e['det_y'] = rng.normal(0, 15, n), rng.normal(0, 15, n)
    mult = np.ones(n, dtype='>i4')
    mult[::50], mult[1::50] = 2, 0
    e['multiplicity'] = mult
    paths = {'reconstruction': folder / f'{run}-v01.epos', 'range': folder / 'NiTi.rrng',
             'raw': folder / f'{run}.hits'}
    e.tofile(paths['reconstruction'])
    paths['range'].write_text(RRNG)
    paths['raw'].write_bytes(b'\x00dummy hits' + rng.bytes(4096))
    return paths


def write_apt6(path, ions, extra=None):
    """Minimal AP Suite .apt (header + Mass + Position [+ extra 1-D float sections])."""
    from nomad_apt.readers import APT_HEADER, APT_SECTION

    n = len(ions)
    h = np.zeros(1, APT_HEADER)
    h['sig'] = list(b'APT\0')
    h['header_size'], h['header_version'], h['ion_count'] = 540, 2, n

    def section(name, data, unit, width, extra_header=b''):
        s = np.zeros(1, APT_SECTION)
        s['sig'] = list(b'SEC\0')
        s['header_size'] = 148 + len(extra_header)
        s['header_version'] = 2
        s['type'][0][:len(name)] = [ord(c) for c in name]
        s['section_version'], s['relationship'], s['record_type'], s['data_type'] = 1, 1, 1, 3
        s['type_size'], s['record_size'] = 32, 4 * width
        s['unit'][0][:len(unit)] = [ord(c) for c in unit]
        raw = np.ascontiguousarray(data, dtype='<f4').tobytes()
        s['record_count'], s['byte_count'] = n, len(raw)
        return s.tobytes() + extra_header + raw

    body = section('Mass', ions['m'], 'Da', 1)
    xyz = np.stack([ions['x'], ions['y'], ions['z']], axis=1)
    body += section('Position', xyz, 'nm', 3, extra_header=np.zeros(6, '<f4').tobytes())
    for name, (data, unit) in (extra or {}).items():
        body += section(name, data, unit, 1)
    path.write_bytes(h.tobytes() + body)


def write_export_xml(path, raw, recons, notes):
    """AP Suite experiment export .xml with a ROOT-like parameter blob holding the run header."""
    import base64
    import zlib

    def tstring(t):
        b = t.encode()
        return (bytes([len(b)]) if len(b) < 255 else b'\xff' + len(b).to_bytes(4, 'big')) + b

    payload = b'\x00\x01TObjArray\x00CRunHeader\x00' + tstring(notes['title']) + b'\x00\x02CLasHeader\x00' + \
        tstring(notes['title']) + b'\x00\x00' + tstring(notes['comments']) + b'\x00' + tstring('Good Run') + \
        b'\x00' + tstring('Fractured') + b'\x00' + tstring('IPG YLPP 258nm') + b'\x00CRefSpatMap\x00' + \
        b'cReflectron=26913-1041-A\x00 5000R Default version 1\x00'
    z = zlib.compress(payload)
    blob = base64.b64encode(b'root' + b'\x00' * 20 + b'ZL\x08' + b'\x00' * 6 + z).decode()
    recs = ''.join(f'<ExportReconstruction><ReconstructionId>{rid}</ReconstructionId><Name>{name}</Name>'
                   f'<Comments>{comment}</Comments><Parameters>{blob}</Parameters>'
                   f'<TimeOfCreation>2026-10-08T18:13:59.1244539</TimeOfCreation><UserName>Admin</UserName>'
                   f'<CreationMethod>Wizard</CreationMethod></ExportReconstruction>'
                   for rid, name, comment in recons)
    path.write_text('<?xml version="1.0" encoding="utf-16"?>\n<ExportExperiment><Filename>' + raw +
                    '</Filename><ExportReconstructions>' + recs + '</ExportReconstructions></ExportExperiment>')


def make_export(folder: Path, n=20_000):
    """AP Suite experiment export: .HITS, two reconstructions (.apt named by id) and the .xml."""
    folder.mkdir(parents=True, exist_ok=True)
    p = make(folder / '_tmp', n=n)
    ions = np.fromfile(p['reconstruction'], dtype=EPOS_DTYPE)
    ids = ['2a1343fa-e66e-4e68-b58e-6c95283a0df9', 'c74fbc30-0376-4d07-b891-e8d22b3c728b']
    write_apt6(folder / f'{ids[0]}.apt', ions, extra={'Voltage': (ions['vdc'], ''), 'Temp': (np.full(n, 30.0), 'K')})
    write_apt6(folder / f'{ids[1]}.apt', ions[ions['m'] > 3])
    (folder / 'R6043_00450.HITS').write_bytes(b'\x00dummy' * 100)
    write_export_xml(folder / 'R6043_00450.xml', 'R6043_00450.HITS',
                     [(ids[0], 'R6043_00450', '13ms400C1h_M18'), (ids[1], 'R6043_00450_bezH', '')],
                     {'title': 'R6043_00450 20260513_Tyc_NiTi:M-18 08-19-2026',
                      'comments': 'DR0.2%, Temp30K, start 1000V, eff en 30pJ\nSpecimen fractured at 19.6 M ions'})
    import shutil
    shutil.copy(p['range'], folder / 'NiTi.rrng')
    shutil.rmtree(folder / '_tmp')
    return folder, ids
