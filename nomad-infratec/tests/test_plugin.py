"""Tests for nomad-infratec. Run:  pytest -q tests/"""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from make_data import make  # noqa: E402

REAL = Path('/mnt/user-data/uploads/dsc001/infratec/temp_profile (88).tdms')


def parse(path):
    from nomad.datamodel import EntryArchive
    from nomad.datamodel.context import ClientContext
    from nomad.utils import get_logger

    from nomad_infratec.parsers.parser import IRRecordParser

    archive = EntryArchive(m_context=ClientContext(local_dir=str(Path(path).parents[1])))
    IRRecordParser().parse(str(path), archive, logger=get_logger(__name__))
    return archive


def process(eln):
    from nomad.client import normalize_all
    from nomad.datamodel import EntryArchive, EntryMetadata
    from nomad.datamodel.context import ClientContext

    from nomad_infratec.schema_packages.ir import IRRecord

    data = json.loads(eln.read_text())['data']
    data.pop('m_def')
    archive = EntryArchive(m_context=ClientContext(local_dir=str(eln.parents[1])),
                           metadata=EntryMetadata(mainfile=f'{eln.parent.name}/{eln.name}'))
    archive.data = IRRecord.m_from_dict(data)
    normalize_all(archive)
    return archive


def test_reader(tmp_path):
    from nomad_infratec.reader import read_ir

    p, profiles = make(tmp_path / 'rec.tdms')
    d = read_ir(str(p))
    assert d['n_frames'] == 40 and d['valid'].sum() == 38 and not d['valid'][:2].any()
    assert np.allclose(d['time'][:2], [0, 7.3])
    assert d['rois']['ROI_00']['profiles'].shape == (40, 60) and d['rois']['ROI_01']['geometry'][0] == 10
    f = d['fields']['ROI_00']
    assert f['unit_in_file'] == 'K' and f['data'].shape[1:] == (60, 12)
    i = f['frames'].index(d['hottest_frame'])
    assert np.allclose(f['data'][i][:, 0], profiles[d['hottest_frame']], atol=1e-3)  # K -> °C


def test_entry(tmp_path):
    from nomad.parsing.parsers import match_parser

    p, _ = make(tmp_path / 'raw' / 'ir' / 'temp_profile (5).tdms')
    assert type(match_parser(str(p))[0]).__name__ == 'IRRecordParser'
    raw = parse(p)
    eln = p.with_name('temp_profile (5).archive.json')
    assert raw.data.ir_entry == 'ir/temp_profile (5).archive.json' and eln.exists()
    doc = json.loads(eln.read_text())
    doc['data']['purpose'] = 'heat treatment'
    doc['data']['rois'] = [{'name': 'ROI_01', 'description': 'gauge length'}]
    eln.write_text(json.dumps(doc))
    a = process(eln)
    e = a.data
    assert a.metadata.entry_name == 'temp_profile (5)' and e.purpose == 'heat treatment'
    assert (e.n_frames, e.valid_frames) == (40, 38) and abs(e.peak_temperature.magnitude - 425) < 1
    assert e.peak_temperature_K.magnitude == pytest.approx(e.peak_temperature.magnitude + 273.15)
    assert [r.name for r in e.rois] == ['ROI_00', 'ROI_01'] and e.rois[1].description == 'gauge length'
    assert e.rois[0].profiles.shape == (38, 60)
    assert [f.label for f in e.figures] == ['Temperature vs time', 'Explorer (choose x and y)',
                                           'Profiles vs time (map)', 'Profile at time (slider)',
                                           'Temperature field ROI_00 (slider)']


@pytest.mark.skipif(not REAL.exists(), reason='real example not available')
def test_real_file(tmp_path):
    import shutil

    d = tmp_path / 'raw' / 'ir'
    d.mkdir(parents=True)
    shutil.copy(REAL, d / REAL.name)
    parse(d / REAL.name)
    e = process(d / 'temp_profile (88).archive.json').data
    assert e.n_frames == 111 and e.valid_frames == 109 and abs(e.peak_temperature.magnitude - 422.37) < 0.01
    assert abs(e.frame_interval.magnitude - 7.3) < 0.1 and len(e.figures) == 5
