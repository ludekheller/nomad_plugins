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
    assert d.specimen.mass.to('mg').magnitude == pytest.approx(99.2, abs=1e-9)  # float32 noise rounded
    s = d.instrument_settings
    assert s.instrument_serial == 'DSC2A-00304' and s.purge_gas == 'Nitrogen'
    assert s.purge_flow.magnitude == pytest.approx(50.0)
    assert s.number_of_cycles == 1 and s.heating_rate.magnitude == pytest.approx(20.0)
    types = [seg.segment_type for seg in d.measurement.segments]
    assert types == ['ramp_cooling', 'isothermal', 'ramp_heating', 'isothermal']
    assert all(seg.figures for seg in d.measurement.segments)
    assert [t['name'] for t in d.figures[0].figure['data']] == ['1: cycle 1 cooling to -100 °C',
                                                               '2: cycle 1 heating to 100 °C']
    ex = d.figures[1].figure
    assert d.figures[1].label == 'Explorer (choose x and y)'
    assert [t['name'] for t in ex['data']] == ['Time (s)', 'Temperature (°C)', 'Heat flow (W/g)']  # one line per y
    assert [t['visible'] for t in ex['data']] == ['legendonly', 'legendonly', True]
    x_menu, scale_menu = ex['layout']['updatemenus']
    assert x_menu['buttons'][x_menu['active']]['label'] == 'Temperature (°C)'
    assert len(x_menu['buttons'][0]['args'][0]['x']) == 1  # one x array shared by all lines
    y_max = scale_menu['buttons'][1]['args'][0]['y'][2]  # heat flow, normalised by max |value|
    vals = [v for v in y_max if v is not None]
    assert max(abs(v) for v in vals) == pytest.approx(1.0) and min(vals) < 0  # −1…1 (negative values)
    y_mm = [v for v in scale_menu['buttons'][2]['args'][0]['y'][1] if v is not None]  # temperature, min-max
    assert min(y_mm) == pytest.approx(0.0) and max(y_mm) == pytest.approx(1.0)


def test_reader_rejects_non_trios_json():
    from nomad_dsc_trios.trios import read_trios_json

    with pytest.raises(ValueError):
        read_trios_json({'a': 1}, 'x.json')


def test_gzipped_json(upload):
    import gzip

    from nomad.parsing.parsers import match_parser

    gz = upload / (JSON + '.gz')
    gz.write_bytes(gzip.compress((upload / JSON).read_bytes()))
    (upload / JSON).unlink()
    parser, _ = match_parser(str(gz))
    assert type(parser).__name__ == 'TriosDSCParser'
    raw = process(gz)
    assert raw.data.dsc_entry == 'niti_slm_hex74121.archive.json'
    eln = upload / 'niti_slm_hex74121.archive.json'
    assert json.loads(eln.read_text())['data']['data_file'] == JSON + '.gz'
    d = process(eln).data
    assert d.run_name == 'niti_slm_hex74/121'
    assert [seg.segment_type for seg in d.measurement.segments][:3] == ['ramp_cooling', 'isothermal', 'ramp_heating']
