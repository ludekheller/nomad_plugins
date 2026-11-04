"""Tests for nomad-dsc-trios. Run:  pytest -q tests/

Simulates what the Oasis does: the TRIOS CSV is matched by the parser, which writes
<run>.archive.json; that entry is then processed and reads the CSV.
"""

import json
import shutil
from pathlib import Path

import pytest
from nomad.client import normalize_all, parse

DATA = Path(__file__).parent / 'data'
CSV = 'NiTiNb_23-1-1.csv'


@pytest.fixture
def upload(tmp_path):
    shutil.copy(DATA / CSV, tmp_path / CSV)
    return tmp_path


def process(path):
    archive = parse(str(path))[0]
    normalize_all(archive)
    return archive


def test_csv_creates_dsc_entry(upload):
    raw = process(upload / CSV)
    assert raw.data.m_def.name == 'TRIOS_DSC_Export'
    eln = json.loads((upload / 'NiTiNb_23-1-1.archive.json').read_text())
    assert eln['data']['m_def'].endswith('.DSC_SMA')
    assert eln['data']['data_file'] == CSV


def test_dsc_entry_reads_csv(upload):
    process(upload / CSV)
    d = process(upload / 'NiTiNb_23-1-1.archive.json').data
    assert d.operator == 'Eli'
    assert d.specimen.mass.to('mg').magnitude == pytest.approx(22.8)
    assert d.instrument_settings.number_of_cycles == 2
    assert [len(s.temperature) for s in d.measurement.segments][:3] == [10191, 1800, 10801]
    assert all(s.figures for s in d.measurement.segments)
    assert len(d.figures[0].figure['data']) == 5
    r = d.transformation_results
    assert r.Ms.magnitude == pytest.approx(-56.274)
    assert r.Af.magnitude == pytest.approx(5.708)


def test_manual_values_are_kept(upload):
    process(upload / CSV)
    eln = upload / 'NiTiNb_23-1-1.archive.json'
    data = json.loads(eln.read_text())
    data['data']['specimen'] = {'material': 'NiTiNb', 'processing_history': '<p>450 °C / 30 min, WQ</p>'}
    data['data']['transformation_results'] = {'Ms': -50.0}  # corrected by hand
    eln.write_text(json.dumps(data))
    d = process(eln).data
    assert d.specimen.material == 'NiTiNb'
    assert d.specimen.specimen_id == 'NiTiNb_23-1-1'  # empty field filled from the file
    assert d.transformation_results.Ms.magnitude == pytest.approx(-50.0)  # kept
    assert d.transformation_results.Mf.magnitude == pytest.approx(-83.147)  # filled


def test_other_csv_is_not_matched(upload):
    from nomad.parsing.parsers import match_parser

    (upload / 'other.csv').write_text('a,b\n1,2\n')
    parser, _ = match_parser(str(upload / 'other.csv'))
    assert parser is None or 'Trios' not in type(parser).__name__
    parser, _ = match_parser(str(upload / CSV))
    assert type(parser).__name__ == 'TriosDSCParser'
