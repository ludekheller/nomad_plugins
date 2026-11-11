"""Tests for nomad-dsc-trios. Run:  pytest -q tests/

Simulates what the Oasis does: the TRIOS CSV is matched by the parser, which writes
<run>.archive.json; that entry is then processed and reads the CSV.
"""

import json
import sys
import shutil
from pathlib import Path

import pytest
from nomad.client import normalize_all, parse

DATA = Path(__file__).parent / 'data'
CSV = 'NiTiNb_23-1-1.csv'
# the TRIOS example is research data and not in the public repository
pytestmark = pytest.mark.skipif(not (DATA / CSV).exists(), reason='test data not available')


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
    assert r.Ms_K.to('kelvin').magnitude == pytest.approx(-56.274 + 273.15)  # kelvin copies for the search page
    assert r.Af_K.to('kelvin').magnitude == pytest.approx(5.708 + 273.15)


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
    assert d.transformation_results.Ms_K.magnitude == pytest.approx(223.15)  # follows the hand value
    assert d.transformation_results.Mf.magnitude == pytest.approx(-83.147)  # filled


def test_other_csv_is_not_matched(upload):
    from nomad.parsing.parsers import match_parser

    (upload / 'other.csv').write_text('a,b\n1,2\n')
    parser, _ = match_parser(str(upload / 'other.csv'))
    assert parser is None or 'Trios' not in type(parser).__name__
    parser, _ = match_parser(str(upload / CSV))
    assert type(parser).__name__ == 'TriosDSCParser'


def _set(eln, **data):
    doc = json.loads(eln.read_text())
    doc['data'].update(data)
    eln.write_text(json.dumps(doc))


def test_evaluation_off_by_default(upload):
    process(upload / CSV)
    d = process(upload / 'NiTiNb_23-1-1.archive.json').data
    assert d.evaluation is None  # nothing computed unless asked for
    assert d.transformation_results.Ms.magnitude == pytest.approx(-56.274)  # TRIOS value
    assert d.transformation_results.Ms1 is None


def test_evaluation_automatic(upload):
    process(upload / CSV)
    eln = upload / 'NiTiNb_23-1-1.archive.json'
    _set(eln, evaluation={'mode': 'automatic', 'cycle': 2})
    d = process(eln).data
    r, ev = d.transformation_results, d.evaluation
    assert [p.label for p in ev.peaks] == ['cooling peak 1', 'heating peak 1']
    assert r.Ms.magnitude == pytest.approx(-56.3, abs=0.3)  # TRIOS: -56.274
    assert r.Af.magnitude == pytest.approx(5.0, abs=0.5)  # TRIOS: 5.708
    assert r.Ms1.magnitude == r.Ms.magnitude and r.Mf1.magnitude == r.Mf.magnitude
    assert r.Ms_K.magnitude == pytest.approx(r.Ms.magnitude + 273.15)
    assert r.enthalpy_cooling.magnitude > 1
    assert 'automatic' in r.evaluation_method
    assert {(w.ramp) for w in ev.windows} == {'cooling', 'heating'} and ev.windows_from_automatic
    assert any(f.label == 'Evaluation (tangent method)' for f in d.figures)


def test_evaluation_keeps_hand_values_and_semi_windows(upload):
    process(upload / CSV)
    eln = upload / 'NiTiNb_23-1-1.archive.json'
    _set(eln, evaluation={'mode': 'automatic', 'cycle': 2})
    d = process(eln).data
    doc = json.loads(eln.read_text())
    doc['data'] = d.m_to_dict()
    doc['data']['transformation_results']['Mf'] = -80.0  # corrected by hand
    doc['data']['evaluation']['mode'] = 'semi-automatic'
    doc['data']['evaluation']['windows'] = [{'ramp': 'cooling', 'T1': -30.0, 'T2': -110.0}]
    eln.write_text(json.dumps(doc))
    d = process(eln).data
    r = d.transformation_results
    assert r.Mf.magnitude == pytest.approx(-80.0)  # kept
    assert r.Ms.magnitude == pytest.approx(-56.3, abs=1.0)  # re-evaluated from the window
    assert r.As1 is not None  # heating: no window -> old automatic values stay
    assert 'heating: no window given' in d.evaluation.messages


def test_folder_settings(upload):
    process(upload / CSV)
    (upload / 'dsc_evaluation.archive.json').write_text(json.dumps({'data': {
        'm_def': 'nomad_dsc_trios.schema_packages.dsc.DSC_EvaluationSettings',
        'mode': 'automatic', 'cycle': 2, 'min_height_percent': 20}}))
    d = process(upload / 'NiTiNb_23-1-1.archive.json').data
    assert d.evaluation.settings_file.endswith('dsc_evaluation.archive.json')
    assert json.loads(d.evaluation.parameters_used)['min_height_percent'] == 20
    assert d.transformation_results.Ms.magnitude == pytest.approx(-56.3, abs=0.3)


def test_results_csv_row(upload):
    sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
    from dsc_results_csv import COLUMNS, row

    process(upload / CSV)
    eln = upload / 'NiTiNb_23-1-1.archive.json'
    _set(eln, evaluation={'mode': 'automatic', 'cycle': 2})
    archive = process(eln)
    r = row({'entry_id': 'x', 'archive': archive.m_to_dict()})
    assert set(r) == set(COLUMNS)
    assert r['Ms'] == pytest.approx(archive.data.transformation_results.Ms.magnitude, abs=1e-3)  # °C
    assert r['mode'] == 'automatic' and r['n_peaks_cooling'] == 1
