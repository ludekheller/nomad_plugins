"""Tests for nomad-thermomech. Run:  pytest -q tests/

Needs one real test folder in tests/data/Test170/ (WaveMatrix Test170.* + Mercury export).
That folder is NOT in the public repository (research data); without it the tests skip.
"""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from nomad.client import normalize_all

DATA = Path(__file__).parent / 'data' / 'Test170'
pytestmark = pytest.mark.skipif(not (DATA / 'Test170.log').exists(), reason='test data not available')
NAME = 'Test170__R19_sa_30_after500_pulse20_cycles_V3'


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / 'raw' / 'R19_cycles'  # server-like layout: <upload>/raw/<folder>/
    shutil.copytree(DATA, d)
    return d


MERCURY = 'R19_sa_30_after500_pulse20_cycles_V3_export.csv'


def process(path):
    """Run the matching parser like the Oasis does: raw files resolved from the upload root."""
    from nomad.datamodel import EntryArchive
    from nomad.datamodel.context import ClientContext
    from nomad.utils import get_logger

    from nomad_thermomech.parsers.mercury_parser import MercuryExportParser
    from nomad_thermomech.parsers.wavematrix_parser import WaveMatrixTestParser

    parser = WaveMatrixTestParser() if str(path).endswith('.log') else MercuryExportParser()
    archive = EntryArchive(m_context=ClientContext(local_dir=str(Path(path).parents[1])))
    parser.parse(str(path), archive, logger=get_logger(__name__))
    return archive


def _entries(folder):
    return sorted(f.name for f in folder.glob('*.archive.json'))


def test_only_the_log_is_matched(folder):
    from nomad.parsing.parsers import match_parser

    matched = {f.name for f in folder.iterdir() if match_parser(str(f))[0] is not None}
    assert matched == {'Test170.log', 'R19_sa_30_after500_pulse20_cycles_V3_export.csv'}


def test_log_creates_entry_with_all_files(folder):
    raw = process(folder / 'Test170.log')
    assert raw.data.test_entry == f'R19_cycles/{NAME}.archive.json'  # upload-relative on the server
    files = json.loads((folder / f'{NAME}.archive.json').read_text())['data']['files']
    assert files['wavematrix_data'] == 'R19_cycles/Test170.Stop.csv'
    assert files['mercury_export'] == 'R19_cycles/R19_sa_30_after500_pulse20_cycles_V3_export.csv'
    assert len(files) == 7


def _process_entry(folder):
    """Process the created entry with paths relative to the upload root (as on the server)."""
    from nomad.datamodel import EntryArchive
    from nomad.datamodel.context import ClientContext

    from nomad_thermomech.schema_packages.thermomech import ThermomechTest

    process(folder / 'Test170.log')
    data = json.loads((folder / f'{NAME}.archive.json').read_text())['data']
    data.pop('m_def')
    archive = EntryArchive(m_context=ClientContext(local_dir=str(folder.parent)))
    archive.data = ThermomechTest.m_from_dict(data)
    normalize_all(archive)
    return archive.data


def test_entry_reads_and_synchronises(folder):
    d = _process_entry(folder)
    assert d.test_name == 'Test170' and d.method == 'NiTi_3mm_SE_SA'
    assert d.start_time.isoformat().startswith('2025-09-18T13:15:46')  # 15:15:46 Prague (CEST) in UTC
    assert d.specimen.cross_section_area.magnitude == pytest.approx(7.07)
    assert d.instrument.frame_serial == 'E10BMTB10267'
    assert len(d.wavematrix.time) == 49625 and len(d.mercury.time) == 18596
    s = d.synchronisation
    assert s.time_offset.magnitude == pytest.approx(27.835, abs=0.01)
    assert s.force_correlation > 0.9999
    assert s.pc_clock_offset.magnitude == pytest.approx(92.65, abs=0.1)  # clocks would be ~65 s off
    assert len(d.cycles) == 40
    labels = [f.label for f in d.figures]
    assert labels == ['Stress - strain (DIC)', 'Stress and temperature vs time', 'Strain vs time',
                      'Synchronisation check (force)']
    names = [t['name'] for t in d.figures[0].figure['data']]
    assert names == [f'loop {i}' for i in range(0, 21)]


def test_manual_values_are_kept(folder):
    process(folder / 'Test170.log')
    eln = folder / f'{NAME}.archive.json'
    data = json.loads(eln.read_text())
    data['data']['specimen'] = {'specimen_id': 'R19', 'material': 'NiTi', 'cross_section_area': 7.1}
    data['data']['test_description'] = '<p>superelastic cycling, 20 cycles</p>'
    eln.write_text(json.dumps(data))
    d = _process_entry_keep(folder)
    assert d.specimen.specimen_id == 'R19' and d.specimen.material == 'NiTi'
    assert d.specimen.cross_section_area.magnitude == pytest.approx(7.1)  # hand value kept
    assert d.specimen.gauge_length.magnitude == pytest.approx(5.0, abs=1e-3)  # empty -> filled
    assert 'superelastic' in d.test_description


def _process_entry_keep(folder):
    from nomad.datamodel import EntryArchive
    from nomad.datamodel.context import ClientContext

    from nomad_thermomech.schema_packages.thermomech import ThermomechTest

    data = json.loads((folder / f'{NAME}.archive.json').read_text())['data']
    data.pop('m_def')
    archive = EntryArchive(m_context=ClientContext(local_dir=str(folder.parent)))
    archive.data = ThermomechTest.m_from_dict(data)
    normalize_all(archive)
    return archive.data


@pytest.fixture
def wm_only(tmp_path):
    """Folder uploaded with the WaveMatrix files only (Mercury export comes later)."""
    d = tmp_path / 'raw' / 'R19_cycles'
    shutil.copytree(DATA, d, ignore=shutil.ignore_patterns(MERCURY))
    return d


def test_mercury_added_later(wm_only):
    process(wm_only / 'Test170.log')
    assert _entries(wm_only) == ['Test170.archive.json']
    eln = wm_only / 'Test170.archive.json'
    data = json.loads(eln.read_text())
    assert 'mercury_export' not in data['data']['files'] and data['data']['name'] == 'Test170'
    data['data']['specimen'] = {'specimen_id': 'R19', 'material': 'NiTi'}  # edited in the GUI
    eln.write_text(json.dumps(data))

    shutil.copy(DATA / MERCURY, wm_only / MERCURY)  # export from the DIC PC arrives
    raw = process(wm_only / MERCURY)
    assert raw.data.test_entry == 'R19_cycles/Test170.archive.json'
    assert _entries(wm_only) == ['Test170.archive.json']  # no second entry
    data = json.loads(eln.read_text())['data']
    assert data['files']['mercury_export'] == f'R19_cycles/{MERCURY}'
    assert data['name'] == NAME
    assert data['specimen'] == {'specimen_id': 'R19', 'material': 'NiTi'}  # hand values kept

    data.pop('m_def')
    from nomad.datamodel import EntryArchive
    from nomad.datamodel.context import ClientContext

    from nomad_thermomech.schema_packages.thermomech import ThermomechTest

    archive = EntryArchive(m_context=ClientContext(local_dir=str(wm_only.parent)))
    archive.data = ThermomechTest.m_from_dict(data)
    normalize_all(archive)
    d = archive.data
    assert d.specimen.specimen_id == 'R19' and len(d.mercury.time) == 18596
    assert d.synchronisation.time_offset.magnitude == pytest.approx(27.835, abs=0.01)


def test_mercury_before_wavematrix_is_noop(tmp_path):
    d = tmp_path / 'raw' / 'R19_cycles'
    d.mkdir(parents=True)
    shutil.copy(DATA / MERCURY, d / MERCURY)
    raw = process(d / MERCURY)
    assert raw.data.test_entry is None and _entries(d) == []
    for f in DATA.iterdir():  # WaveMatrix files arrive afterwards
        if f.name != MERCURY:
            shutil.copy(f, d / f.name)
    process(d / 'Test170.log')
    assert _entries(d) == [f'{NAME}.archive.json']
    assert 'mercury_export' in json.loads((d / f'{NAME}.archive.json').read_text())['data']['files']


def test_uploaded_together_one_entry(folder):
    for f in (MERCURY, 'Test170.log', MERCURY):  # any order, repeated
        process(folder / f)
    assert _entries(folder) == [f'{NAME}.archive.json']
    assert len(json.loads((folder / f'{NAME}.archive.json').read_text())['data']['files']) == 7


def test_hand_set_name_is_kept(wm_only):
    process(wm_only / 'Test170.log')
    eln = wm_only / 'Test170.archive.json'
    data = json.loads(eln.read_text())
    data['data']['name'] = 'R19 superelastic cycling'
    eln.write_text(json.dumps(data))
    shutil.copy(DATA / MERCURY, wm_only / MERCURY)
    process(wm_only / MERCURY)
    assert json.loads(eln.read_text())['data']['name'] == 'R19 superelastic cycling'
