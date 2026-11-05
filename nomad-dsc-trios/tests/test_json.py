"""TRIOS JSON export (TRIOS >= 5.8). Run:  pytest -q tests/

tests/data/niti_slm_hex74121.json is a reduced copy of a real export (every 10th row,
only the columns the plugin reads).
"""

import json
import shutil
from pathlib import Path

import pytest
from nomad.client import normalize_all, parse

DATA = Path(__file__).parent / 'data'
JSON = 'niti_slm_hex74121.json'
pytestmark = pytest.mark.skipif(not (DATA / JSON).exists(), reason='test data not available')


@pytest.fixture
def upload(tmp_path):
    shutil.copy(DATA / JSON, tmp_path / JSON)
    return tmp_path


def process(path):
    archive = parse(str(path))[0]
    normalize_all(archive)
    return archive


def test_json_is_matched_but_not_archive_json(upload):
    from nomad.parsing.parsers import match_parser

    parser, _ = match_parser(str(upload / JSON))
    assert type(parser).__name__ == 'TriosDSCParser'
    (upload / 'x.archive.json').write_text(json.dumps({'data': {'m_def': 'nomad.datamodel.data.EntryData'}}))
    parser, _ = match_parser(str(upload / 'x.archive.json'))
    assert parser is None or type(parser).__name__ != 'TriosDSCParser'
    (upload / 'other.json').write_text('{"a": 1}')
    parser, _ = match_parser(str(upload / 'other.json'))
    assert parser is None or type(parser).__name__ != 'TriosDSCParser'


def test_json_creates_and_fills_dsc_entry(upload):
    raw = process(upload / JSON)
    assert raw.data.m_def.name == 'TRIOS_DSC_Export'
    eln = upload / 'niti_slm_hex74121.archive.json'
    assert json.loads(eln.read_text())['data']['data_file'] == JSON
    a = process(eln)
    d = a.data
    assert d.run_name == 'niti_slm_hex74/121' and d.operator == 'Eli'
    assert a.metadata.entry_name == 'niti_slm_hex74/121'
    assert d.date.isoformat().startswith('2026-08-21T10:53:36')  # 12:53:36 Prague (CEST)
    assert d.specimen.mass.to('mg').magnitude == pytest.approx(99.2, abs=1e-3)
    s = d.instrument_settings
    assert s.instrument_serial == 'DSC2A-00304' and s.purge_gas == 'Nitrogen'
    assert s.purge_flow.magnitude == pytest.approx(50.0)
    assert s.number_of_cycles == 1 and s.heating_rate.magnitude == pytest.approx(20.0)
    types = [seg.segment_type for seg in d.measurement.segments]
    assert types == ['ramp_cooling', 'isothermal', 'ramp_heating', 'isothermal']
    assert all(seg.figures for seg in d.measurement.segments)
    assert [t['name'] for t in d.figures[0].figure['data']] == ['1: cycle 1 cooling to -100 °C',
                                                               '2: cycle 1 heating to 100 °C']


def test_reader_rejects_non_trios_json():
    from nomad_dsc_trios.trios import read_trios_json

    with pytest.raises(ValueError):
        read_trios_json({'a': 1}, 'x.json')
