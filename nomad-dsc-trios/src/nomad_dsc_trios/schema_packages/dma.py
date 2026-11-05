"""DMA (TA Instruments, e.g. DMA 850) from TRIOS JSON exports.

`data_file` points to the TRIOS JSON (.json or .json.gz) in the upload. On save/processing
the entry reads it: sample, clamp geometry, instrument, procedure, one segment per results
step (time, temperature, strain, stress, force, displacement, modulus ... as present), and
plots: stress vs strain, strain vs temperature, and the explorer (any channel on x, several
on y, optional normalisation). Values typed in by hand are never overwritten; segments and
plots are always rebuilt from the file.
"""

import gzip
import io
import json

import numpy as np
from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.annotations import ELNAnnotation
from nomad.datamodel.metainfo.plot import PlotlyFigure, PlotSection
from nomad.metainfo import Datetime, Quantity, SchemaPackage, Section, SubSection

from nomad_dsc_trios.explorer import explorer_figure
from nomad_dsc_trios.trios_dma import read_trios_dma_json

m_package = SchemaPackage(name='DMA (TA Instruments TRIOS)')

TIME_ZONE = 'Europe/Prague'
MAX_PLOT_POINTS = 6000
# explorer menu: these first (if present), then all other numeric channels
EXPLORER_FIRST = ['Time_s', 'Step time_s', 'Temperature_°C', 'Temperature set point_°C', 'Strain_%',
                  'Stress_MPa', 'Force_N', 'Displacement_mm', 'Length_mm', 'Modulus_MPa']


def _str(rich=False, **kw):
    comp = 'RichTextEditQuantity' if rich else 'StringEditQuantity'
    return Quantity(type=str, a_eln=ELNAnnotation(component=comp), **kw)


def _num(unit, **kw):
    return Quantity(type=np.float64, unit=unit, a_eln=ELNAnnotation(component='NumberEditQuantity'), **kw)


def _arr(unit=None, **kw):
    return Quantity(type=np.float64, shape=['*'], unit=unit, **kw)


class DMA_Specimen(ArchiveSection):
    m_def = Section(a_eln=dict(overview=True))
    specimen_id = _str()
    material = _str(description='e.g. NiTi, NiTiHf, NiTiNb')
    nominal_composition = _str()
    semi_product = _str(description='wire, ribbon, sheet ...')
    processing_history = _str(rich=True, description='heat treatment, cold work, training ...')
    clamp = _str(description='TRIOS geometry, e.g. Film Clamp, Tension, 3-point bending')
    length = _num('millimeter', description='Sample length in the clamp (TRIOS geometry)')
    diameter = _num('millimeter')
    width = _num('millimeter')
    thickness = _num('millimeter')
    geometry_notes = _str(description='Notes of the TRIOS geometry')


class DMA_Settings(ArchiveSection):
    m_def = Section(a_eln=dict(overview=True))
    instrument = _str()
    instrument_serial = _str()
    temperature_option = _str()
    procedure_name = _str()
    procedure_steps = Quantity(type=str, shape=['*'], description='TRIOS procedure steps (full text)')


class DMA_Segment(ArchiveSection):
    m_def = Section(label_quantity='name')
    name = Quantity(type=str)
    time = _arr('second')
    temperature = _arr('celsius')
    temperature_set_point = _arr('celsius')
    strain = _arr(description='%')
    stress = _arr('megapascal')
    force = _arr('newton')
    displacement = _arr('millimeter')
    length = _arr('millimeter')
    modulus = _arr('megapascal')
    storage_modulus = _arr('megapascal')
    loss_modulus = _arr('megapascal')
    tan_delta = _arr()
    frequency = _arr('hertz')


class DMA_TRIOS(PlotSection, EntryData):
    """One DMA run (TA Instruments TRIOS JSON export)."""

    m_def = Section(label='DMA (TRIOS)')

    data_file = Quantity(type=str, description='TRIOS JSON export (.json / .json.gz) in this upload; read on save',
                         a_eln=ELNAnnotation(component='FileEditQuantity'), a_browser=dict(adaptor='RawFileAdaptor'))
    run_name = _str()
    operator = _str()
    date = Quantity(type=Datetime, a_eln=ELNAnnotation(component='DateTimeEditQuantity'))
    test_description = _str(rich=True, description='Purpose and conditions of the test')
    notes = _str(rich=True)

    specimen = SubSection(section_def=DMA_Specimen)
    instrument_settings = SubSection(section_def=DMA_Settings)
    segments = SubSection(section_def=DMA_Segment, repeats=True)

    def normalize(self, archive, logger):
        if self.data_file:
            try:
                self._read(archive, logger)
            except Exception as e:
                logger.error('could not read the TRIOS DMA file', data_file=self.data_file, exc_info=e)
        if self.run_name and archive.metadata is not None:
            archive.metadata.entry_name = self.run_name
        super().normalize(archive, logger)

    def _read(self, archive, logger):
        with archive.m_context.raw_file(self.data_file, 'rb') as f:
            raw = gzip.open(f) if self.data_file.lower().endswith('.gz') else f
            doc = json.load(io.TextIOWrapper(raw, encoding='utf-8-sig'))
        data, explorer, variables = read_trios_dma_json(doc, self.data_file, tz=TIME_ZONE)

        for q in ('run_name', 'operator', 'date'):
            if q in data and getattr(self, q) is None:
                self.m_update_from_dict({q: data[q]})
        for name, section_def in (('specimen', DMA_Specimen), ('instrument_settings', DMA_Settings)):
            values = data.get(name, {})
            if getattr(self, name) is None:
                if not values:
                    continue
                setattr(self, name, section_def())
            target = getattr(self, name)
            missing = {k: v for k, v in values.items() if getattr(target, k) is None}
            if missing:
                target.m_update_from_dict(missing)

        self.segments = [DMA_Segment.m_from_dict(s) for s in data['segments']]
        self.figures = self._figures(data['segments'], explorer, variables)
        logger.info('TRIOS DMA file read', data_file=self.data_file, segments=len(self.segments))

    @staticmethod
    def _figures(segments, explorer, variables):
        def thin(*arrays):
            step = max(1, int(np.ceil(len(arrays[0]) / MAX_PLOT_POINTS)))
            return [list(a[::step]) for a in arrays]

        figs = []
        for label, xq, yq, xt, yt in (
            ('Stress vs strain', 'strain', 'stress', 'Strain (%)', 'Stress (MPa)'),
            ('Strain vs temperature', 'temperature', 'strain', 'Temperature (°C)', 'Strain (%)'),
        ):
            data = []
            for i, s in enumerate(segments):
                if s.get(xq) and s.get(yq):
                    x, y = thin(s[xq], s[yq])
                    data.append({'type': 'scattergl', 'mode': 'lines', 'name': f'{i + 1}: {s["name"]}', 'x': x, 'y': y})
            if data:
                figs.append(PlotlyFigure(label=label, figure={'data': data, 'layout': {
                    'title': {'text': f'{label} (one line per step)'},
                    'xaxis': {'title': {'text': xt}}, 'yaxis': {'title': {'text': yt}}}}))
        order = {k: i for i, k in enumerate(EXPLORER_FIRST)}
        variables = sorted(variables, key=lambda kv: order.get(kv[0], len(order)))
        keys = [k for k, _ in variables]
        x = 'Temperature_°C' if 'Temperature_°C' in keys else keys[0]
        ys = [y for y in ('Strain_%', 'Stress_MPa') if y in keys][:1] or keys[1:2]
        fig = explorer_figure(explorer, variables, x, ys,
                              title='Explorer: choose x, click legend for y variables, choose y scale')
        if fig:
            figs.append(PlotlyFigure(label='Explorer (choose x and y)', figure=fig))
        return figs


m_package.__init_metainfo__()
