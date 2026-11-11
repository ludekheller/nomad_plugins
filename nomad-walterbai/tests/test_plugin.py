"""Tests for nomad-walterbai. Run:  pytest -q tests/

tests/data: a real machine record (no extension) and its 1D DIC export (every 4th frame).
"""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

DATA = Path(__file__).parent / 'data'
NAME = 'NiTi1_pulse_16ms_150C_xdg1'
DIC = NAME + '_dic.csv'
pytestmark = pytest.mark.skipif(not (DATA / NAME).exists(), reason='test data not available')


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / 'raw' / 'pulse_tests'  # server-like layout: <upload>/raw/<folder>/
    d.mkdir(parents=True)
    return d


def run_parser(path):
    from nomad.datamodel import EntryArchive
    from nomad.datamodel.context import ClientContext
    from nomad.utils import get_logger

    from nomad_walterbai.parsers.parser import WalterBaiDICParser, WalterBaiParser

    parser = WalterBaiDICParser() if str(path).endswith('_dic.csv') else WalterBaiParser()
    archive = EntryArchive(m_context=ClientContext(local_dir=str(Path(path).parents[1])))
    parser.parse(str(path), archive, logger=get_logger(__name__))
    return archive


def process_entry(folder):
    from nomad.client import normalize_all
    from nomad.datamodel import EntryArchive, EntryMetadata
    from nomad.datamodel.context import ClientContext

    from nomad_walterbai.schema_packages.walterbai import WalterBaiTest

    data = json.loads((folder / f'{NAME}.archive.json').read_text())['data']
    data.pop('m_def')
    archive = EntryArchive(m_context=ClientContext(local_dir=str(folder.parent)),
                           metadata=EntryMetadata(mainfile=f'pulse_tests/{NAME}.archive.json'))
    archive.data = WalterBaiTest.m_from_dict(data)
    normalize_all(archive)
    return archive


def test_files_are_recognised_by_header(folder):
    from nomad.parsing.parsers import match_parser

    shutil.copy(DATA / NAME, folder / NAME)
    shutil.copy(DATA / DIC, folder / DIC)
    (folder / 'other').write_text('Time / s\tsomething else\n1\t2\n')
    assert type(match_parser(str(folder / NAME))[0]).__name__ == 'WalterBaiParser'
    assert type(match_parser(str(folder / DIC))[0]).__name__ == 'WalterBaiDICParser'
    parser = match_parser(str(folder / 'other'))[0]
    assert parser is None or 'WalterBai' not in type(parser).__name__


def test_machine_and_dic(folder):
    shutil.copy(DATA / NAME, folder / NAME)
    shutil.copy(DATA / DIC, folder / DIC)
    raw = run_parser(folder / NAME)
    assert raw.data.test_entry == f'pulse_tests/{NAME}.archive.json'
    a = process_entry(folder)
    d = a.data
    assert a.metadata.entry_name == NAME
    m = d.machine
    assert m.time.magnitude[0] == 0 and m.time.magnitude[-1] == pytest.approx(190.3, abs=0.05)  # zero-based
    assert m.strain.max() == pytest.approx(16.12, abs=0.01) and m.stress.magnitude.max() == pytest.approx(915.6, 0.1)
    assert m.laser_position is None and m.jh_resistance is None  # NaN / inf channels: explorer only
    assert d.test_temperature.magnitude == pytest.approx(151.2, abs=0.2)
    assert d.test_temperature_K.magnitude == pytest.approx(d.test_temperature.magnitude + 273.15)
    dic = d.dic
    assert len(dic.points) == 58 and len(dic.segments) == 57 and dic.segments[0] == 'T102–T103'
    assert dic.time.magnitude[0] == 0
    assert dic.local_strain.shape == (len(dic.time), 57)
    assert dic.gauge_points == 'T102–T159' and dic.gauge_length.magnitude == pytest.approx(28.379, abs=1e-3)
    assert dic.gauge_strain.max() == pytest.approx(16.5, abs=0.2)  # machine: 16.12 %
    assert d.specimen.gauge_length.magnitude == pytest.approx(28.379, abs=1e-3)
    assert d.date.isoformat().startswith('2018-09-28')
    # local strain = 100 (d_b - d_a) / |p_b(0) - p_a(0)|, checked for one segment by hand
    lines = (folder / DIC).read_text(encoding='utf-8-sig').splitlines()
    head, i = lines[0].split(';'), len(dic.time) // 2
    row, first = lines[1 + i].split(';'), lines[1].split(';')
    v = lambda r, c: float(r[head.index(c)])  # noqa: E731
    l0 = np.hypot(v(first, 'T103 - Position in X [mm]') - v(first, 'T102 - Position in X [mm]'),
                  v(first, 'T103 - Position in Y [mm]') - v(first, 'T102 - Position in Y [mm]'))
    expected = 100 * (v(row, 'T103 - Displacement [mm]') - v(row, 'T102 - Displacement [mm]')) / l0
    assert dic.local_strain[i, 0] == pytest.approx(expected)
    labels = [f.label for f in d.figures]
    assert labels == ['DIC strain map', 'Stress vs strain', 'Local strains vs time', 'Explorer (choose x and y)']
    hm = d.figures[0].figure['data'][0]
    assert hm['type'] == 'heatmap' and len(hm['x']) == len(hm['y']) == len(hm['z'])  # flat lists
    assert len(set(hm['y'])) == 57 and len(hm['z']) <= 30000 + 57
    assert [t['name'] for t in d.figures[1].figure['data']] == ['machine strain', 'DIC strain T102–T159']


def test_dic_added_later(folder):
    shutil.copy(DATA / NAME, folder / NAME)
    run_parser(folder / NAME)
    eln = folder / f'{NAME}.archive.json'
    assert 'dic_file' not in json.loads(eln.read_text())['data']['files']
    doc = json.loads(eln.read_text())
    doc['data']['specimen'] = {'material': 'NiTi'}  # typed in the GUI
    eln.write_text(json.dumps(doc))
    assert [f.label for f in process_entry(folder).data.figures] == ['Stress vs strain', 'Explorer (choose x and y)']

    shutil.copy(DATA / DIC, folder / DIC)
    raw = run_parser(folder / DIC)
    assert raw.data.test_entry == f'pulse_tests/{NAME}.archive.json'
    data = json.loads(eln.read_text())['data']
    assert data['files']['dic_file'] == f'pulse_tests/{DIC}' and data['specimen'] == {'material': 'NiTi'}
    d = process_entry(folder).data
    assert d.dic is not None and d.specimen.material == 'NiTi'


def test_dic_before_machine_is_noop(folder):
    shutil.copy(DATA / DIC, folder / DIC)
    raw = run_parser(folder / DIC)
    assert raw.data.test_entry is None and not list(folder.glob('*.archive.json'))


def test_machine_detected_and_hand_value_kept(folder):
    shutil.copy(DATA / NAME, folder / NAME)
    run_parser(folder / NAME)
    assert process_entry(folder).data.testing_machine == 'Walter+Bai (UTTRMO)'
    eln = folder / f'{NAME}.archive.json'
    doc = json.loads(eln.read_text())
    doc['data']['testing_machine'] = 'other'  # changed by hand
    eln.write_text(json.dumps(doc))
    assert process_entry(folder).data.testing_machine == 'other'


def test_mitter_record(folder):
    """MITTER: same software and format as Walter+Bai, recognised by its columns; no DIC."""
    from nomad.client import normalize_all
    from nomad.datamodel import EntryArchive, EntryMetadata
    from nomad.datamodel.context import ClientContext
    from nomad.parsing.parsers import match_parser

    from nomad_walterbai.schema_packages.walterbai import WalterBaiTest

    name = '15ms_tahzk_20C'
    shutil.copy(DATA / name, folder / name)
    assert type(match_parser(str(folder / name))[0]).__name__ == 'WalterBaiParser'
    raw = run_parser(folder / name)
    assert raw.data.test_entry == f'pulse_tests/{name}.archive.json'
    data = json.loads((folder / f'{name}.archive.json').read_text())['data']
    assert 'dic_file' not in data['files']
    data.pop('m_def')
    a = EntryArchive(m_context=ClientContext(local_dir=str(folder.parent)),
                     metadata=EntryMetadata(mainfile=f'pulse_tests/{name}.archive.json'))
    a.data = WalterBaiTest.m_from_dict(data)
    normalize_all(a)
    d = a.data
    assert d.testing_machine == 'MITTER' and a.metadata.entry_name == name
    assert d.dic is None and d.machine.water_temperature_down is not None
    assert d.machine.stress.magnitude.max() == pytest.approx(1033.0, abs=0.1)
    assert d.machine.strain.max() == pytest.approx(55.81, abs=0.01)
    assert d.test_temperature.magnitude == pytest.approx(20.0, abs=0.2)
    assert [f.label for f in d.figures] == ['Stress vs strain', 'Explorer (choose x and y)']
