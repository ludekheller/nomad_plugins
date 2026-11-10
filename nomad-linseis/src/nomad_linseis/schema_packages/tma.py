"""Linseis TMA (PT1000LT / PT1600, thermomechanical analyzer) run from a text export.

`data_file` points to the export (.txt) in the upload. On processing the entry reads it:
sample name, measurement date, initial length, the record (time, ΔL, relative expansion,
temperature), splits it into heating / cooling / hold segments and builds the plots:
relative expansion vs temperature (one line per segment), temperature and expansion vs time,
and the explorer. The applied stress is taken from the sample name ('…400MPa') if not entered.
Values typed in by hand are never overwritten; data and plots are rebuilt from the file.
"""

import numpy as np
from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.annotations import ELNAnnotation
from nomad.datamodel.metainfo.plot import PlotlyFigure, PlotSection
from nomad.metainfo import Datetime, MEnum, Quantity, SchemaPackage, Section, SubSection

from nomad_linseis.explorer import explorer_figure
from nomad_linseis.reader import read_tma, segments

m_package = SchemaPackage(name='Linseis TMA (thermomechanical analyzer)')

TIME_ZONE = 'Europe/Prague'
MAX_PLOT_POINTS = 6000
INSTRUMENTS = ['Linseis TMA PT1000LT', 'Linseis TMA PT1600']


def _str(rich=False, **kw):
    comp = 'RichTextEditQuantity' if rich else 'StringEditQuantity'
    return Quantity(type=str, a_eln=ELNAnnotation(component=comp), **kw)


def _num(unit, **kw):
    return Quantity(type=np.float64, unit=unit, a_eln=ELNAnnotation(component='NumberEditQuantity'), **kw)


def _arr(unit=None, **kw):
    return Quantity(type=np.float64, shape=['*'], unit=unit, **kw)


class TMASpecimen(ArchiveSection):
    m_def = Section(a_eln=dict(overview=True))
    specimen_id = _str()
    material = _str(description='e.g. NiTi, NiTiHf, NiTiNb')
    nominal_composition = _str()
    semi_product = _str(description='wire, ribbon, sheet ...')
    processing_history = _str(rich=True, description='heat treatment, pulses, training ...')
    initial_length = _num('millimeter', description='From the export header')
    diameter = _num('millimeter')
    cross_section_area = _num('millimeter ** 2')


class TMASegment(ArchiveSection):
    m_def = Section(label_quantity='name')
    name = Quantity(type=str)
    kind = Quantity(type=MEnum('heating', 'cooling', 'isothermal'))
    rate = Quantity(type=np.float64, unit='kelvin / minute', description='Mean rate (signed)')
    temperature_start = Quantity(type=np.float64, unit='celsius')
    temperature_end = Quantity(type=np.float64, unit='celsius')
    time = _arr('second')
    temperature = _arr('celsius')
    delta_length = _arr('micrometer')
    relative_expansion = _arr(description='%')


class LinseisTMA(PlotSection, EntryData):
    """One Linseis TMA run (text export)."""

    m_def = Section(label='TMA (Linseis)')

    data_file = Quantity(type=str, description='Linseis TMA text export in this upload; read on save',
                         a_eln=ELNAnnotation(component='FileEditQuantity'), a_browser=dict(adaptor='RawFileAdaptor'))
    name = _str(description='Sample name from the export')
    instrument = Quantity(type=MEnum(*INSTRUMENTS), a_eln=ELNAnnotation(component='EnumEditQuantity'))
    measurement_date = Quantity(type=Datetime, a_eln=ELNAnnotation(component='DateTimeEditQuantity'))
    export_date = Quantity(type=Datetime)
    operator = _str()
    applied_stress = _num('megapascal', description='Constant stress of the run (from the sample name if given)')
    applied_force = _num('newton')
    test_description = _str(rich=True, description='e.g. thermal cycling under constant stress')
    notes = _str(rich=True)

    specimen = SubSection(section_def=TMASpecimen)
    time = _arr('second')
    temperature = _arr('celsius')
    delta_length = _arr('micrometer')
    relative_expansion = _arr(description='%')
    segments = SubSection(section_def=TMASegment, repeats=True)

    def normalize(self, archive, logger):
        if self.data_file:
            try:
                self._read(archive, logger)
            except Exception as e:
                logger.error('could not read the Linseis TMA file', data_file=self.data_file, exc_info=e)
        if self.name and archive.metadata is not None:
            archive.metadata.entry_name = self.name
        super().normalize(archive, logger)

    def _read(self, archive, logger):
        with archive.m_context.raw_file(self.data_file, 'r', encoding='utf-8', errors='replace') as f:
            d = read_tma(f.read().splitlines(), tz=TIME_ZONE)
        if self.name is None and d['name']:
            self.name = d['name']
        if self.measurement_date is None and d['measurement_date']:
            self.measurement_date = d['measurement_date']
        if d['export_date']:
            self.export_date = d['export_date']
        if self.applied_stress is None and d['stress_from_name'] is not None:
            self.applied_stress = d['stress_from_name']
        if self.specimen is None:
            self.specimen = TMASpecimen()
        if self.specimen.specimen_id is None and d['name']:
            self.specimen.specimen_id = d['name']
        if self.specimen.initial_length is None and d['initial_length']:
            self.specimen.initial_length = d['initial_length']

        for q in ('time', 'temperature', 'delta_length', 'relative_expansion'):
            setattr(self, q, d.get(q))
        t, T = d['time'], d['temperature']
        segs = []
        for i, (kind, a, b) in enumerate(segments(T, t)):
            dt = (t[b - 1] - t[a]) / 60
            seg = TMASegment(name=f'{i + 1}: {kind} {T[a]:.0f} → {T[b - 1]:.0f} °C', kind=kind,
                             rate=(T[b - 1] - T[a]) / dt if dt > 0 else 0.0,
                             temperature_start=T[a], temperature_end=T[b - 1],
                             time=t[a:b], temperature=T[a:b])
            for q in ('delta_length', 'relative_expansion'):
                if d.get(q) is not None:
                    setattr(seg, q, d[q][a:b])
            segs.append(seg)
        self.segments = segs
        self.figures = self._figures(d, segs)
        logger.info('Linseis TMA file read', points=len(t), segments=[s.name for s in segs])

    @staticmethod
    def _figures(d, segs):
        def thin(*arrays):
            step = max(1, int(np.ceil(len(arrays[0]) / MAX_PLOT_POINTS)))
            return [[float(f'{v:.6g}') for v in np.asarray(a)[::step]] for a in arrays]

        figs = []
        y_key = 'relative_expansion' if d.get('relative_expansion') is not None else 'delta_length'
        y_label = 'Relative expansion (%)' if y_key == 'relative_expansion' else 'ΔL (µm)'
        data = []
        for s in segs:
            if s.kind == 'isothermal':
                continue
            x, y = thin(s.temperature.magnitude, getattr(s, y_key) if y_key == 'relative_expansion'
                        else s.delta_length.magnitude)
            data.append({'type': 'scattergl', 'mode': 'lines', 'name': s.name, 'x': x, 'y': y})
        if data:
            figs.append(PlotlyFigure(label='Expansion vs temperature', figure={'data': data, 'layout': {
                'title': {'text': f'{y_label.split(" (")[0]} vs temperature (one line per ramp)'},
                'showlegend': True,
                'xaxis': {'title': {'text': 'Temperature (°C)'}}, 'yaxis': {'title': {'text': y_label}}}}))

        t, T, y = thin(d['time'], d['temperature'], d[y_key])
        figs.append(PlotlyFigure(label='Temperature and expansion vs time', figure={
            'data': [{'type': 'scattergl', 'mode': 'lines', 'name': 'temperature', 'x': t, 'y': T},
                     {'type': 'scattergl', 'mode': 'lines', 'name': y_label.split(' (')[0].lower(), 'x': t, 'y': y,
                      'yaxis': 'y2'}],
            'layout': {'title': {'text': 'Temperature and expansion vs time'}, 'showlegend': True,
                       'xaxis': {'title': {'text': 'Time (s)'}}, 'yaxis': {'title': {'text': 'Temperature (°C)'}},
                       'yaxis2': {'title': {'text': y_label}, 'overlaying': 'y', 'side': 'right'}}}))

        variables = [('time', 'Time (s)'), ('temperature', 'Temperature (°C)'),
                     ('delta_length', 'ΔL (µm)'), ('relative_expansion', 'Relative expansion (%)')]
        groups = [(s.name, {'time': d['time'][i0:i1], 'temperature': d['temperature'][i0:i1],
                            **{k: d[k][i0:i1] for k in ('delta_length', 'relative_expansion') if d.get(k) is not None}})
                  for s, (i0, i1) in zip(segs, _bounds(segs))]
        fig = explorer_figure(groups, variables, 'temperature', [y_key])
        if fig:
            figs.append(PlotlyFigure(label='Explorer (choose x and y)', figure=fig))
        return figs


def _bounds(segs):
    out, start = [], 0
    for s in segs:
        out.append((start, start + len(s.time)))
        start += len(s.time)
    return out


class LinseisTMAExport(EntryData):
    """Raw Linseis TMA export; its data are in the TMA entry."""

    m_def = Section(label='Linseis TMA export (raw file)')
    tma_entry = Quantity(type=str, description='TMA entry (.archive.json) created for this file')


m_package.__init_metainfo__()
