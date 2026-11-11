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
    from nomad_dsc_trios.results_table import COLUMNS, row

    process(upload / CSV)
    eln = upload / 'NiTiNb_23-1-1.archive.json'
    _set(eln, evaluation={'mode': 'automatic', 'cycle': 2})
    archive = process(eln)
    r = row({'entry_id': 'x', 'archive': archive.m_to_dict()})
    assert set(r) == set(COLUMNS)
    assert r['Ms'] == pytest.approx(archive.data.transformation_results.Ms.magnitude, abs=1e-3)  # °C
    assert r['mode'] == 'automatic' and r['n_peaks_cooling'] == 1


def test_default_settings_created_once_per_folder(tmp_path):
    from nomad_dsc_trios.evaluation_nomad import defaults

    sub = tmp_path / 'series' / 'DSC'
    sub.mkdir(parents=True)
    shutil.copy(DATA / CSV, sub / CSV)
    shutil.copy(DATA / CSV, sub / 'second.csv')
    process(sub / CSV)
    settings = sub / 'dsc_evaluation.archive.json'
    data = json.loads(settings.read_text())['data']
    assert data['m_def'].endswith('.DSC_EvaluationSettings')
    assert {k: data[k] for k in defaults()} == defaults() and data['mode'] == 'off'
    settings.write_text(json.dumps({'data': {**data, 'mode': 'automatic'}}))  # edited by the user
    process(sub / 'second.csv')
    assert json.loads(settings.read_text())['data']['mode'] == 'automatic'  # not overwritten
    # locally the upload root is the file's folder; on the server it is the project: check the helper
    from types import SimpleNamespace

    from nomad_dsc_trios.evaluation_nomad import create_default_settings

    (sub / 'more').mkdir()
    ctx = SimpleNamespace(local_dir=str(tmp_path), process_updated_raw_file=lambda *a, **k: None)
    sdef = 'nomad_dsc_trios.schema_packages.dsc.DSC_EvaluationSettings'
    assert create_default_settings(ctx, 'series/DSC/more', sdef) is None  # covered by series/DSC
    (tmp_path / 'other').mkdir()
    assert create_default_settings(ctx, 'other', sdef) == 'other/dsc_evaluation.archive.json'
    assert create_default_settings(ctx, 'other', sdef) is None  # second call: already there


def test_settings_entry_shows_defaults(tmp_path):
    from nomad_dsc_trios.evaluation_nomad import defaults

    f = tmp_path / 'dsc_evaluation.archive.json'
    f.write_text(json.dumps({'data': {'m_def': 'nomad_dsc_trios.schema_packages.dsc.DSC_EvaluationSettings',
                                      'mode': 'automatic', 'min_height_percent': 20}}))
    d = process(f).data
    assert d.mode == 'automatic' and d.min_height_percent == 20  # set values kept
    assert d.sg_window.magnitude == defaults()['sg_window'] and d.knee_fraction == defaults()['knee_fraction']
    assert d.cycle == 1
    assert [f.label for f in d.figures] == ['What the parameters do']


def test_default_settings_parallel_creates_one(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    from nomad_dsc_trios.evaluation_nomad import create_default_settings

    calls = []
    ctx = SimpleNamespace(local_dir=str(tmp_path), process_updated_raw_file=lambda *a, **k: calls.append(a))
    sdef = 'nomad_dsc_trios.schema_packages.dsc.DSC_EvaluationSettings'
    with ThreadPoolExecutor(16) as pool:
        created = list(pool.map(lambda _: create_default_settings(ctx, '', sdef), range(64)))
    assert sum(c is not None for c in created) == 1 and len(calls) == 1
    assert json.loads((tmp_path / 'dsc_evaluation.archive.json').read_text())['data']['mode'] == 'off'


def test_north_files_without_gui(tmp_path, monkeypatch):
    """Jupyter helper: find DSC folders in mounted projects, evaluate a run, save windows to the file."""
    from nomad_dsc_trios import evaluation_nomad as EVN
    from nomad_dsc_trios import north

    root = tmp_path / 'uploads' / 'my-project-TG_S6zI2RMCID31b_3DG5g'
    sub = root / 'series' / 'DSC'
    sub.mkdir(parents=True)
    shutil.copy(DATA / CSV, sub / CSV)
    (sub / 'run.archive.json').write_text(json.dumps({'data': {
        'm_def': north.DSC_DEF, 'data_file': f'series/DSC/{CSV}', 'specimen': {'material': 'NiTiNb'}}}))
    assert north.dsc_folders(str(tmp_path / 'uploads')) == [str(sub)]
    run = north.Run(str(sub / 'run.archive.json'))
    assert north.upload_id(run.root) == 'TG_S6zI2RMCID31b_3DG5g' and run.rel == 'series/DSC/run.archive.json'
    segments, exo_up = run.load()
    res = EVN.evaluate(segments, exo_up, {'mode': 'automatic', 'cycle': 2}, {})
    assert res.values['Ms'] == pytest.approx(-56.3, abs=0.3)
    monkeypatch.delenv('NOMAD_CLIENT_ACCESS_TOKEN', raising=False)
    msg = run.save_evaluation({'mode': 'semi-automatic', 'windows': [{'ramp': 'cooling', 'T1': -30, 'T2': -110}]})
    assert 'saved to the file' in msg
    saved = json.loads((sub / 'run.archive.json').read_text())['data']
    assert saved['evaluation']['mode'] == 'semi-automatic' and saved['specimen'] == {'material': 'NiTiNb'}


def test_buttons_in_the_entry(upload):
    process(upload / CSV)
    eln = upload / 'NiTiNb_23-1-1.archive.json'
    _set(eln, evaluation={'mode': 'automatic', 'cycle': 2})
    d = process(eln).data
    auto = [(w.ramp, w.T1.magnitude, w.T2.magnitude) for w in d.evaluation.windows]
    ms = d.transformation_results.Ms.magnitude
    doc = json.loads(eln.read_text())
    doc['data'] = d.m_to_dict()
    doc['data']['evaluation']['edit_automatic_windows'] = True  # button
    eln.write_text(json.dumps(doc))
    d = process(eln).data
    ev = d.evaluation
    assert ev.mode == 'semi-automatic' and not ev.edit_automatic_windows and not ev.windows_from_automatic
    assert [(w.ramp, w.T1.magnitude, w.T2.magnitude) for w in ev.windows] == auto
    assert d.transformation_results.Ms.magnitude == pytest.approx(ms, abs=0.01)  # same windows, same result
    doc['data'] = d.m_to_dict()
    doc['data']['evaluation']['use_folder_settings'] = True  # button
    eln.write_text(json.dumps(doc))
    ev = process(eln).data.evaluation
    assert ev.mode is None and ev.cycle is None and not ev.windows and not ev.use_folder_settings


def test_apply_to_folder_button(tmp_path):
    from types import SimpleNamespace

    from nomad_dsc_trios.evaluation_nomad import reprocess_folder

    sub = tmp_path / 'series' / 'DSC'
    (sub / 'more').mkdir(parents=True)
    dsc = {'data': {'m_def': 'nomad_dsc_trios.schema_packages.dsc.DSC_SMA'}}
    for p in (sub / 'a.archive.json', sub / 'more' / 'b.archive.json'):
        p.write_text(json.dumps(dsc))
    (sub / 'other.archive.json').write_text(json.dumps({'data': {'m_def': 'x.Other'}}))
    calls = []
    ctx = SimpleNamespace(local_dir=str(tmp_path), process_updated_raw_file=lambda p, **k: calls.append(p))
    archive = SimpleNamespace(metadata=SimpleNamespace(mainfile='series/DSC/dsc_evaluation.archive.json'),
                              m_context=ctx)
    assert reprocess_folder(archive) == 2
    assert sorted(calls) == ['series/DSC/a.archive.json', 'series/DSC/more/b.archive.json']
