"""Campaign entries: shared values for all tests in a folder tree. Run:  pytest -q tests/

Uses the real test folder tests/data/Test170/ (skipped if missing).
"""

import json
import shutil
from pathlib import Path

import pytest
from nomad.client import normalize_all

DATA = Path(__file__).parent / 'data' / 'Test170'
pytestmark = pytest.mark.skipif(not (DATA / 'Test170.log').exists(), reason='test data not available')
NAME = 'Test170__R19_sa_30_after500_pulse20_cycles_V3'
CAMPAIGN = {'m_def': 'nomad_thermomech.schema_packages.thermomech.ThermomechCampaign',
            'name': 'NiTi round, tension, superelastic cycling', 'loading_mode': 'tension',
            'test_type': 'superelastic cycling', 'test_temperature': 30.0, 'material': 'NiTi',
            'cross_section_shape': 'round', 'diameter': 3.0}


@pytest.fixture
def upload(tmp_path):
    raw = tmp_path / 'raw'
    shutil.copytree(DATA, raw / 'NiTi_tension' / 'R19_cycles')
    write_campaign(raw, CAMPAIGN)
    return raw


def write_campaign(raw, data):
    (raw / 'NiTi_tension' / 'campaign.archive.json').write_text(json.dumps({'data': data}))


def run_parser(raw):
    from nomad.datamodel import EntryArchive
    from nomad.datamodel.context import ClientContext
    from nomad.utils import get_logger

    from nomad_thermomech.parsers.wavematrix_parser import WaveMatrixTestParser

    log = raw / 'NiTi_tension' / 'R19_cycles' / 'Test170.log'
    WaveMatrixTestParser().parse(str(log), EntryArchive(m_context=ClientContext(local_dir=str(raw))),
                                 logger=get_logger(__name__))
    return raw / 'NiTi_tension' / 'R19_cycles' / f'{NAME}.archive.json'


def process(raw, rel, section):
    from nomad.datamodel import EntryArchive, EntryMetadata
    from nomad.datamodel.context import ClientContext

    data = json.loads((raw / rel).read_text())['data']
    data.pop('m_def')
    archive = EntryArchive(m_context=ClientContext(local_dir=str(raw)), metadata=EntryMetadata(mainfile=rel, upload_id='test_upload'))
    archive.data = section.m_from_dict(data)
    normalize_all(archive)
    return archive


def run_test(raw, eln):
    from nomad_thermomech.schema_packages.thermomech import ThermomechTest

    return process(raw, str(eln.relative_to(raw)), ThermomechTest)


def test_campaign_fills_empty_fields(upload):
    a = run_test(upload, run_parser(upload))
    d = a.data
    assert d.campaign_file == 'NiTi_tension/campaign.archive.json'
    assert d.loading_mode == 'tension' and d.test_type == 'superelastic cycling'
    assert d.test_temperature.magnitude == pytest.approx(30.0)
    assert d.test_temperature_K.magnitude == pytest.approx(303.15)  # kelvin copy, also for campaign values
    assert d.specimen.material == 'NiTi' and d.specimen.cross_section_shape == 'round'
    assert d.specimen.diameter.magnitude == pytest.approx(3.0)
    assert d.specimen.cross_section_area.magnitude == pytest.approx(7.07)  # specimen.txt wins over computed
    assert a.metadata.entry_name == NAME  # entry list shows the name, not the file name


def test_campaign_change_propagates_but_hand_values_stay(upload):
    eln = run_parser(upload)
    d = run_test(upload, eln).data
    # simulate a GUI save of the test: filled values are now in the file, material edited by hand
    doc = json.loads(eln.read_text())
    doc['data'].update(loading_mode=d.loading_mode, test_type=d.test_type, campaign_filled=d.campaign_filled,
                       specimen={'material': 'NiTi (batch 7)', 'diameter': 3.0, 'cross_section_shape': 'round'})
    eln.write_text(json.dumps(doc))
    write_campaign(upload, {**CAMPAIGN, 'loading_mode': 'compression', 'material': 'NiTiHf', 'diameter': 2.5})
    d = run_test(upload, eln).data
    assert d.loading_mode == 'compression'  # campaign value -> follows the campaign
    assert d.specimen.diameter.magnitude == pytest.approx(2.5)
    assert d.specimen.material == 'NiTi (batch 7)'  # edited by hand -> kept


def test_area_computed_from_dimensions(upload):
    (upload / 'NiTi_tension' / 'R19_cycles' / 'Test170.specimen.txt').unlink()
    d = run_test(upload, run_parser(upload)).data
    assert d.specimen.cross_section_area.magnitude == pytest.approx(3.141592653589793 * 3.0 ** 2 / 4)


def test_campaign_lists_its_tests(upload):
    from nomad_thermomech.schema_packages.thermomech import ThermomechCampaign

    run_parser(upload)
    a = process(upload, 'NiTi_tension/campaign.archive.json', ThermomechCampaign)
    assert a.data.n_tests == 1
    assert a.metadata.entry_name == CAMPAIGN['name']
    refs = a.data.m_to_dict()['tests']  # stored as a reference to the test entry (by entry id)
    assert len(refs) == 1 and refs[0].startswith('../upload/archive/') and refs[0].endswith('/data')


def test_no_campaign_no_change(tmp_path):
    raw = tmp_path / 'raw'
    shutil.copytree(DATA, raw / 'NiTi_tension' / 'R19_cycles')
    d = run_test(raw, run_parser(raw)).data
    assert d.campaign_file is None and d.loading_mode is None


def test_campaign_with_any_name_and_nearest_wins(upload):
    (upload / 'NiTi_tension' / 'campaign.archive.json').rename(upload / 'NiTi_tension' / 'NiTi tension SE.archive.json')
    sub = upload / 'NiTi_tension' / 'R19_cycles'
    (sub / 'local.archive.json').write_text(json.dumps({'data': {**CAMPAIGN, 'loading_mode': 'torsion'}}))
    d = run_test(upload, run_parser(upload)).data
    assert d.campaign_file == 'NiTi_tension/R19_cycles/local.archive.json' and d.loading_mode == 'torsion'
    (sub / 'local.archive.json').unlink()
    d = run_test(upload, run_parser(upload)).data
    assert d.campaign_file == 'NiTi_tension/NiTi tension SE.archive.json' and d.loading_mode == 'tension'
