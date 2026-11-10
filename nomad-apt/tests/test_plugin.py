"""Tests for nomad-apt (synthetic data from make_data.py). Run:  pytest -q tests/"""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from make_data import PEAKS, make  # noqa: E402

RUN = 'R6043_00349'


@pytest.fixture
def folder(tmp_path):
    return tmp_path / 'raw' / 'apt'  # server-like layout: <upload>/raw/<folder>/


def parse(path):
    from nomad.datamodel import EntryArchive
    from nomad.datamodel.context import ClientContext
    from nomad.utils import get_logger

    from nomad_apt.parsers.parser import APTParser

    archive = EntryArchive(m_context=ClientContext(local_dir=str(Path(path).parents[1])))
    APTParser().parse(str(path), archive, logger=get_logger(__name__))
    return archive


def process(folder, key):
    from nomad.client import normalize_all
    from nomad.datamodel import EntryArchive, EntryMetadata
    from nomad.datamodel.context import ClientContext

    from nomad_apt.schema_packages.apt import APTMeasurement

    data = json.loads((folder / f'{key}.archive.json').read_text())['data']
    data.pop('m_def')
    archive = EntryArchive(m_context=ClientContext(local_dir=str(folder.parent)),
                           metadata=EntryMetadata(mainfile=f'{folder.name}/{key}.archive.json'))
    archive.data = APTMeasurement.m_from_dict(data)
    normalize_all(archive)
    return archive


def test_readers(tmp_path):
    from nomad_apt.readers import analyse, open_ions, read_ranges, read_rng, run_key

    p = make(tmp_path)
    assert run_key('R6043_00349-v01.epos') == RUN and run_key('r6043_00349.hits') == RUN
    ions = open_ions(str(p['reconstruction']))
    ranges = read_ranges(str(p['range']))
    assert len(ions) == 50_000 and 'TiO' in [r['ion'] for r in ranges]
    a = analyse(ions, ranges)
    assert a['counts'].sum() == 50_000
    w = np.array([q for _, q in PEAKS]) / sum(q for _, q in PEAKS)
    ni = (w[0] + w[1] + w[4]) * 0.95
    assert abs(a['ion_counts']['Ni'] / 50_000 - ni) < 0.01
    assert abs(a['multiple_fraction'] - 0.04) < 0.001
    rng = read_rng('2 2\nNi\n0 1 0\nTi\n0 0 1\n------------------- Ni Ti\n. 28.8 29.2 1 0\n. 23.8 24.2 0 1\n')
    assert [r['ion'] for r in rng] == ['Ni', 'Ti'] and rng[0]['color'] == '#00ff00'


KEY = 'R6043_00349-v01'  # entry = reconstruction file stem


def test_only_reconstruction_is_required(folder):
    p = make(folder)
    p['range'].unlink()
    p['raw'].unlink()
    parse(p['reconstruction'])
    a = process(folder, KEY)
    assert a.metadata.entry_name == KEY and a.data.results.ions_reconstructed == 50_000
    assert a.data.raw_file is None and a.data.range_file is None
    assert [f.label for f in a.data.figures][:2] == ['Mass spectrum', 'Explorer: depth profile (choose x and y)']


def test_files_in_any_order(folder):
    p = make(folder)
    raw = parse(p['raw'])  # raw file alone: no entry
    assert raw.data.apt_entry is None or KEY in raw.data.apt_entry
    parse(p['reconstruction'])
    doc = json.loads((folder / f'{KEY}.archive.json').read_text())['data']
    assert doc['raw_file'] == f'apt/{RUN}.hits'  # same run number
    assert doc['reconstruction_file'] == f'apt/{KEY}.epos'
    assert doc['range_file'] == 'apt/NiTi.rrng'  # the only range file in the folder
    a = process(folder, KEY)
    r = a.data.results
    assert r.ions_reconstructed == 50_000 and 0.85 < r.ranged_fraction / 100 < 0.99
    comp = {c.element: c.atomic_percent for c in r.composition}
    assert set(comp) == {'Ni', 'Ti', 'O'} and abs(sum(comp.values()) - 100) < 1e-6
    labels = [f.label for f in a.data.figures]
    for lab in ('Mass spectrum', 'Composition', 'Composition profile (depth)', '2-D maps x-y',
                '2-D maps x-depth', 'Mass spectrum vs depth', 'Evaporation vs depth', '3-D atom map (sample)',
                'Voltage history', 'Detector hit map', 'Explorer: depth profile (choose x and y)'):
        assert lab in labels, lab
    prof = r.depth_profile
    assert len(prof.depth) == len(prof.ions) and prof.ions.sum() == 50_000
    assert {e.element for e in prof.elements} == {'Ni', 'Ti', 'O'}
    assert a.data.raw_file_size.magnitude > 0


def test_hand_values_kept(folder):
    p = make(folder)
    parse(p['reconstruction'])
    f = folder / f'{KEY}.archive.json'
    doc = json.loads(f.read_text())
    doc['data']['instrument'] = 'CAMECA LEAP 5000 XR'
    doc['data']['acquisition'] = {'pulse_mode': 'laser', 'base_temperature': 40.0}
    f.write_text(json.dumps(doc))
    parse(p['raw'])
    a = process(folder, KEY)
    assert a.data.instrument == 'CAMECA LEAP 5000 XR' and a.data.acquisition.base_temperature.magnitude == 40.0


def test_range_file_owner(folder):
    from nomad_apt.parsers.parser import plan

    make(folder)
    (folder / f'{KEY}.epos').rename(folder / 'R6043_00450.epos')
    import shutil
    shutil.copy(folder / 'R6043_00450.epos', folder / 'R6043_00450_konec microfrac.epos')
    shutil.copy(folder / 'R6043_00450.epos', folder / 'R6043_00777.epos')
    (folder / 'NiTi.rrng').rename(folder / 'R6043_00450_konec microfrac Top Level ROI.RRNG')
    pl = plan(str(folder))
    assert pl['R6043_00450_konec_microfrac']['range_file'] == 'R6043_00450_konec microfrac Top Level ROI.RRNG'
    assert pl['R6043_00450']['range_file'] == 'R6043_00450_konec microfrac Top Level ROI.RRNG'  # same run
    assert 'range_file' not in pl['R6043_00777']  # the only range file, but named for another run
def test_files_recognised(folder):
    from nomad.parsing.parsers import match_parser

    p = make(folder)
    for path in p.values():
        assert type(match_parser(str(path))[0]).__name__ == 'APTParser'


def test_apt_reader(tmp_path):
    from make_data import make_export

    from nomad_apt.readers import analyse, read_apt6, read_ranges

    folder, ids = make_export(tmp_path)
    ions = read_apt6(str(folder / f'{ids[0]}.apt'))
    assert set(ions.names) >= {'x', 'y', 'z', 'm', 'vdc'} and len(ions) == 20_000
    a = analyse(ions, read_ranges(str(folder / 'NiTi.rrng')))
    assert a['counts'].sum() == 20_000 and a['channels']['temperature_K'] == 30.0 and 'vdc' in a


def test_ap_suite_export(tmp_path):
    from make_data import make_export

    folder, ids = make_export(tmp_path / 'raw' / 'apt')
    xml = folder / 'R6043_00450.xml'
    xml_text = xml.read_text()
    xml.unlink()
    parse(folder / f'{ids[0]}.apt')  # .apt alone is enough: entry named by the reconstruction id
    a = process(folder, ids[0])
    assert a.data.name == ids[0] and a.data.results.ions_reconstructed == 20_000
    xml.write_text(xml_text)
    out = parse(xml)  # the .xml arrives later: both reconstructions get its data
    assert out.data.apt_entry == f'apt/{ids[0]}.archive.json, apt/{ids[1]}.archive.json'
    for rid in ids:
        doc = json.loads((folder / f'{rid}.archive.json').read_text())['data']
        assert doc['reconstruction_file'] == f'apt/{rid}.apt' and doc['raw_file'] == 'apt/R6043_00450.HITS'
        assert doc['experiment_file'] == 'apt/R6043_00450.xml' and doc['range_file'] == 'apt/NiTi.rrng'
    e = process(folder, ids[0]).data
    assert e.name == 'R6043_00450' and e.run_number == 'R6043_00450'  # title from the .xml
    assert process(folder, ids[1]).data.name == 'R6043_00450_bezH'
    assert e.instrument == 'CAMECA LEAP 5000 XR' and e.specimen.specimen_id == '20260513_Tyc_NiTi:M-18'
    assert e.measurement_date.strftime('%Y-%m-%d') == '2026-08-19'
    acq = e.acquisition
    assert (acq.pulse_mode, acq.laser_energy.magnitude, acq.base_temperature.magnitude, acq.detection_rate,
            acq.laser_wavelength.magnitude, acq.run_outcome) == ('laser', 30.0, 30.0, 0.2, 258.0, 'fractured')
    assert 'Specimen fractured' in acq.run_comments and e.reconstruction.comments == '13ms400C1h_M18'
    assert e.results.ions_reconstructed == 20_000 and len(e.results.composition) == 3
    assert 'Voltage history' in [f.label for f in e.figures]
