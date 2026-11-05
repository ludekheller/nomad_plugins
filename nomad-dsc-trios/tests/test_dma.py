"""DMA runs from TRIOS JSON exports. Run:  pytest -q tests/

tests/data/niti1_dma_isostress.json is a reduced copy of a real DMA 850 export (every 5th
row, a subset of the channels): strain ramp to 15 % at -90 °C, unloading to 5 MPa, heating
to 200 °C at constant 5 MPa.
"""

import gzip
import json
import shutil
from pathlib import Path

import pytest
from nomad.client import normalize_all, parse

DATA = Path(__file__).parent / 'data'
JSON = 'niti1_dma_isostress.json'
pytestmark = pytest.mark.skipif(not (DATA / JSON).exists(), reason='test data not available')


@pytest.fixture
def upload(tmp_path):
    shutil.copy(DATA / JSON, tmp_path / JSON)
    return tmp_path


def process(path):
    archive = parse(str(path))[0]
    normalize_all(archive)
    return archive


def check_entry(a):
    d = a.data
    assert d.m_def.name == 'DMA_TRIOS'
    assert d.run_name == 'niti1_16ms_15%_-90C' and a.metadata.entry_name == 'niti1_16ms_15%_-90C'
    assert d.instrument_settings.instrument == 'TA Instruments DMA850'
    assert d.instrument_settings.instrument_serial == '0850-00187'
    assert d.instrument_settings.procedure_name == 'ConstStress_thermal_cycling_dma'
    assert d.specimen.clamp == 'Film Clamp' and d.specimen.length.magnitude == pytest.approx(21.43943)
    assert [s.name for s in d.segments] == ['Strain Ramp - 1', 'Stress Ramp - 2', 'IsoStress - 3']
    assert max(d.segments[0].strain) == pytest.approx(15.0, abs=0.2)
    assert d.segments[2].stress.magnitude.mean() == pytest.approx(5.0, abs=0.05)
    assert d.segments[2].temperature.magnitude.max() > 190
    labels = [f.label for f in d.figures]
    assert labels == ['Stress vs strain', 'Strain vs temperature', 'Explorer (choose x and y)']
    ex = d.figures[2].figure
    x_menu = ex['layout']['updatemenus'][0]
    assert x_menu['buttons'][x_menu['active']]['label'] == 'Temperature (°C)'
    assert [t['name'] for t in ex['data'] if t['visible'] is True] == ['Strain (%)']


def test_dma_json_creates_dma_entry(upload):
    raw = process(upload / JSON)
    assert raw.data.dsc_entry == 'niti1_dma_isostress.archive.json'
    eln = upload / 'niti1_dma_isostress.archive.json'
    assert json.loads(eln.read_text())['data']['m_def'].endswith('.DMA_TRIOS')
    check_entry(process(eln))


def test_dma_json_gz(upload):
    gz = upload / (JSON + '.gz')
    gz.write_bytes(gzip.compress((upload / JSON).read_bytes()))
    (upload / JSON).unlink()
    process(gz)
    check_entry(process(upload / 'niti1_dma_isostress.archive.json'))


def test_dsc_json_still_creates_dsc_entry(tmp_path):
    shutil.copy(DATA / 'niti_slm_hex74121.json', tmp_path / 'dsc.json')
    process(tmp_path / 'dsc.json')
    assert json.loads((tmp_path / 'dsc.archive.json').read_text())['data']['m_def'].endswith('.DSC_SMA')
