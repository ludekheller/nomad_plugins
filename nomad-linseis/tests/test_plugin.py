"""Tests for nomad-linseis. Run:  pytest -q tests/

tests/data/400MPa.txt: a real Linseis TMA export (NiTi wire, thermal cycle under 400 MPa);
its µ, ° and Czech month names are damaged by the export, as is common.
"""

import json
import shutil
from pathlib import Path

import pytest
from nomad.client import normalize_all, parse

DATA = Path(__file__).parent / 'data'
TXT = '400MPa.txt'
pytestmark = pytest.mark.skipif(not (DATA / TXT).exists(), reason='test data not available')


@pytest.fixture
def upload(tmp_path):
    shutil.copy(DATA / TXT, tmp_path / TXT)
    return tmp_path


def process(path):
    archive = parse(str(path))[0]
    normalize_all(archive)
    return archive


def test_dates_with_damaged_czech_months():
    from nomad_linseis.reader import _month, parse_date

    assert [_month(m) for m in ('z�?', '?�j', 'zář', 'říj', 'Sep', 'Oct', '?vn', '?vc')] == \
        [9, 10, 9, 10, 9, 10, 6, 7]
    assert parse_date('?t z�? 21 15:31:24 2023').isoformat() == '2023-09-21T15:31:24+02:00'
    assert parse_date('Thu Sep 21 15:31:24 2023').isoformat() == '2023-09-21T15:31:24+02:00'


def test_txt_is_matched_and_creates_entry(upload):
    from nomad.parsing.parsers import match_parser

    assert type(match_parser(str(upload / TXT))[0]).__name__ == 'LinseisTMAParser'
    (upload / 'other.txt').write_text('just some notes\n')
    parser = match_parser(str(upload / 'other.txt'))[0]
    assert parser is None or 'Linseis' not in type(parser).__name__
    raw = process(upload / TXT)
    assert raw.data.tma_entry == '400MPa.archive.json'
    assert json.loads((upload / '400MPa.archive.json').read_text())['data']['data_file'] == TXT


def test_entry_reads_export(upload):
    process(upload / TXT)
    a = process(upload / '400MPa.archive.json')
    d = a.data
    assert d.name == 'Niti5_15ms_chlazeni400MPa' and a.metadata.entry_name == d.name
    assert d.measurement_date.isoformat().startswith('2023-09-21T13:31:24')  # 15:31:24 CEST in UTC
    assert d.applied_stress.magnitude == pytest.approx(400.0)
    assert d.specimen.initial_length.magnitude == pytest.approx(30.1)
    assert len(d.time) == 3553 and d.delta_length.magnitude.max() == pytest.approx(2567.61)
    assert [s.kind for s in d.segments] == ['heating', 'isothermal', 'cooling', 'isothermal', 'heating', 'isothermal']
    cool = d.segments[2]
    assert cool.temperature_end.magnitude == pytest.approx(-4.0, abs=0.1)
    assert cool.rate.magnitude < 0
    labels = [f.label for f in d.figures]
    assert labels == ['Expansion vs temperature', 'Temperature and expansion vs time', 'Explorer (choose x and y)']
    assert len(d.figures[0].figure['data']) == 3  # the three ramps


def test_manual_values_kept(upload):
    process(upload / TXT)
    eln = upload / '400MPa.archive.json'
    doc = json.loads(eln.read_text())
    doc['data'].update(applied_stress=350.0, instrument='Linseis TMA PT1600')
    eln.write_text(json.dumps(doc))
    d = process(eln).data
    assert d.applied_stress.magnitude == pytest.approx(350.0) and d.instrument == 'Linseis TMA PT1600'
