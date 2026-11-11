"""Thermomechanical test on the Walter+Bai (UTTRMO) or MITTER machine (same control software),
optionally with 1D DIC.

One entry per test: the machine record `<name>` (no extension) and, if present, the 1D DIC
export `<name>_dic.csv` in the same folder. Both records are synchronised; their times are
shifted to start at zero. The DIC gives one local strain per pair of neighbouring points and
the gauge strain between the first and the last point. Values typed in by hand are never
overwritten; data and plots are rebuilt from the files on every processing.
"""

import numpy as np
from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.annotations import ELNAnnotation
from nomad.datamodel.metainfo.plot import PlotlyFigure, PlotSection
from nomad.metainfo import Datetime, MEnum, Quantity, SchemaPackage, Section, SubSection

from nomad_walterbai import readers as R
from nomad_walterbai.explorer import explorer_figure

m_package = SchemaPackage(name='Walter+Bai (UTTRMO) and MITTER thermomechanical tests')

MAX_PLOT_POINTS = 6000
MAP_MAX_CELLS = 30000  # strain map: frames x segments kept (flat lists; NOMAD mangles 2D z)
LOCAL_MAX_POINTS = 1500  # local strain vs time: points per line

# machine column header -> (quantity, unit)
MACHINE_COLUMNS = {
    'Time / s': ('time', 'second'),
    'Position / mm': ('position', 'millimeter'),
    'Force / N': ('force', 'newton'),
    'Resistance / Ohm': ('resistance', 'ohm'),
    'Base_Temperature / C': ('base_temperature', 'celsius'),
    'Position_laser_sensor / mm': ('laser_position', 'millimeter'),
    'Water_Temp_Up / C': ('water_temperature', 'celsius'),
    'Water_Temp_Down / C': ('water_temperature_down', 'celsius'),
    'Strain / %': ('strain', None),
    'Stress / MPa': ('stress', 'megapascal'),
    'Cycle number 1': ('cycle_number_1', None),
    'Cycle number 2': ('cycle_number_2', None),
    'JH_Voltage / V': ('jh_voltage', 'volt'),
    'JH_Current / A': ('jh_current', 'ampere'),
    'JH_Power / W': ('jh_power', 'watt'),
    'JH_Resistance / Ohm': ('jh_resistance', 'ohm'),
}


def _str(rich=False, **kw):
    comp = 'RichTextEditQuantity' if rich else 'StringEditQuantity'
    return Quantity(type=str, a_eln=ELNAnnotation(component=comp), **kw)


def _num(unit, **kw):
    return Quantity(type=np.float64, unit=unit, a_eln=ELNAnnotation(component='NumberEditQuantity'), **kw)


def _arr(unit=None, **kw):
    return Quantity(type=np.float64, shape=['*'], unit=unit, **kw)


def _kelvin(name):
    return Quantity(type=np.float64, unit='kelvin', description=(
        f'{name} in K, computed from the °C value (read-only). Used by the search filters: the NOMAD 2.0 '
        'GUI cannot draw histogram filters of °C quantities.'))


def kelvin_copies(section, names):
    """Set <name>_K = <name> converted to kelvin (or unset it if <name> is empty)."""
    for name in names:
        value = getattr(section, name)
        setattr(section, f'{name}_K', None if value is None else float(value.to('kelvin').magnitude))


def _file(description):
    return Quantity(type=str, description=description, a_eln=ELNAnnotation(component='FileEditQuantity'),
                    a_browser=dict(adaptor='RawFileAdaptor'))


class TestFiles(ArchiveSection):
    machine_file = _file('Walter+Bai machine record (no extension)')
    dic_file = _file('1D DIC export <name>_dic.csv (optional)')


class Specimen(ArchiveSection):
    m_def = Section(a_eln=dict(overview=True))
    specimen_id = _str()
    material = _str(description='e.g. NiTi, NiTiHf, NiTiNb')
    nominal_composition = _str()
    semi_product = _str(description='wire, ribbon, sheet ...')
    processing_history = _str(rich=True, description='heat treatment, cold work, pulses ...')
    diameter = _num('millimeter')
    cross_section_area = _num('millimeter ** 2')
    gauge_length = _num('millimeter', description='DIC gauge length (first to last tracked point)')


class MachineData(ArchiveSection):
    """Machine record; time shifted to start at zero. Channels with missing values are only
    shown in the explorer plot."""

    time = _arr('second')
    position = _arr('millimeter')
    force = _arr('newton')
    resistance = _arr('ohm')
    base_temperature = _arr('celsius')
    laser_position = _arr('millimeter')
    water_temperature = _arr('celsius')
    water_temperature_down = _arr('celsius')
    strain = _arr(description='%')
    stress = _arr('megapascal')
    cycle_number_1 = _arr()
    cycle_number_2 = _arr()
    jh_voltage = _arr('volt')
    jh_current = _arr('ampere')
    jh_power = _arr('watt')
    jh_resistance = _arr('ohm')
    columns = Quantity(type=str, shape=['*'], description='All column headers of the record')


class DICData(ArchiveSection):
    """1D DIC: tracked points and local strains between neighbouring points (%). The point
    displacements stay in the DIC export (raw file)."""

    time = _arr('second')
    points = Quantity(type=str, shape=['*'])
    x0 = _arr('millimeter', description='Point positions in the first frame')
    y0 = _arr('millimeter')
    segments = Quantity(type=str, shape=['*'], description='Neighbouring point pairs')
    segment_position = _arr('millimeter', description='Segment centre along the specimen, from the first point')
    segment_length = _arr('millimeter', description='Initial segment length (first frame)')
    local_strain = Quantity(type=np.float64, shape=['*', '*'], description='frames x segments, %')
    gauge_points = Quantity(type=str)
    gauge_length = Quantity(type=np.float64, unit='millimeter')
    gauge_strain = _arr(description='First to last point, %')
    stress = _arr('megapascal', description='Machine stress interpolated onto the DIC time')


class WalterBaiTest(PlotSection, EntryData):
    """One thermomechanical test on the Walter+Bai (UTTRMO) machine (+ 1D DIC)."""

    m_def = Section(label='Walter+Bai / MITTER test')

    name = _str()
    testing_machine = Quantity(type=MEnum(*R.MACHINES), a_eln=ELNAnnotation(component='EnumEditQuantity'),
                       description='Testing machine; detected from the record columns, can be changed by hand')
    date = Quantity(type=Datetime, a_eln=ELNAnnotation(component='DateTimeEditQuantity'),
                    description='Test date (from the DIC export if present)')
    operator = _str()
    test_type = _str(description='e.g. pulse heating, superelastic cycling, actuation ...')
    test_temperature = _num('celsius', description='Mean base temperature of the record')
    test_temperature_K = _kelvin('test_temperature')
    test_description = _str(rich=True)
    notes = _str(rich=True)

    files = SubSection(section_def=TestFiles)
    specimen = SubSection(section_def=Specimen)
    machine = SubSection(section_def=MachineData)
    dic = SubSection(section_def=DICData)

    def normalize(self, archive, logger):
        if self.files is not None and self.files.machine_file:
            try:
                self._read(archive, logger)
            except Exception as e:
                logger.error('could not read the test files', exc_info=e)
        kelvin_copies(self, ('test_temperature',))
        if self.name and archive.metadata is not None:
            archive.metadata.entry_name = self.name
        super().normalize(archive, logger)

    # ------------------------------------------------------------------ reading
    def _read(self, archive, logger):
        ctx = archive.m_context
        with ctx.raw_file(self.files.machine_file, 'r', encoding='utf-8-sig', errors='replace') as f:
            cols, labels = R.read_machine(f.read().splitlines())
        machine = MachineData(columns=[h for h, _ in labels])
        for h, (q, _) in MACHINE_COLUMNS.items():
            v = cols.get(h)
            if v is not None and v.size and np.all(np.isfinite(v)):  # incomplete channels: explorer only
                setattr(machine, q, v)
        self.machine = machine
        if self.testing_machine is None:
            self.testing_machine = R.detect_machine(machine.columns)
        if self.test_temperature is None and 'Base_Temperature / C' in cols:
            bt = cols['Base_Temperature / C']
            if np.isfinite(bt).any():
                self.test_temperature = float(np.nanmean(bt))

        dic = None
        if self.files.dic_file:
            with ctx.raw_file(self.files.dic_file, 'r', encoding='utf-8-sig', errors='replace') as f:
                dic = R.read_dic(f.read().splitlines())
            d = DICData(time=dic['time'], points=dic['points'], x0=dic['x0'], y0=dic['y0'],
                        segments=dic['segments'],
                        segment_position=dic['segment_position'], segment_length=dic['segment_length'],
                        local_strain=np.nan_to_num(dic['local_strain']), gauge_points=dic['gauge_points'],
                        gauge_length=dic['gauge_length'], gauge_strain=np.nan_to_num(dic['gauge_strain']))
            t_m, s_m = cols.get('Time / s'), cols.get('Stress / MPa')
            if t_m is not None and s_m is not None:
                ok = np.isfinite(t_m) & np.isfinite(s_m)
                dic['stress'] = np.interp(dic['time'], t_m[ok], s_m[ok], left=np.nan, right=np.nan)
                d.stress = np.nan_to_num(dic['stress'])
            self.dic = d
            if self.specimen is None:
                self.specimen = Specimen()
            if self.specimen.gauge_length is None:
                self.specimen.gauge_length = dic['gauge_length']
            if self.date is None and dic['date']:
                self.date = dic['date']
        else:
            self.dic = None

        self.figures = self._figures(cols, labels, dic)
        logger.info('Walter+Bai test read', machine_points=len(cols['Time / s']),
                    dic_frames=None if dic is None else len(dic['time']))

    # ------------------------------------------------------------------ plots
    @staticmethod
    def _figures(cols, labels, dic):
        def thin(n, limit):
            return max(1, int(np.ceil(n / limit)))

        def clean(a):
            return [None if not np.isfinite(v) else float(f'{v:.6g}') for v in np.asarray(a, dtype=float)]

        figs = []
        if dic is not None:  # strain map: time on x, position along the specimen on y, colour = local strain
            n_seg = len(dic['segments'])
            st = thin(len(dic['time']), max(100, MAP_MAX_CELLS // n_seg))
            t_map, pos = dic['time'][::st], dic['segment_position']
            strain = dic['local_strain'][::st]  # frames x segments
            figs.append(PlotlyFigure(label='DIC strain map', figure={
                'data': [{'type': 'heatmap',  # flat x / y / z: one entry per cell
                          'x': clean(np.repeat(t_map, n_seg)), 'y': clean(np.tile(pos, len(t_map))),
                          'z': clean(strain.ravel()), 'colorscale': 'Viridis',
                          'colorbar': {'title': {'text': 'Strain (%)'}},
                          'hovertemplate': 't = %{x} s<br>position = %{y} mm<br>strain = %{z} %<extra></extra>'}],
                'layout': {'title': {'text': 'Local strain (1D DIC): time × position along the specimen'},
                           'xaxis': {'title': {'text': 'Time (s)'}},
                           'yaxis': {'title': {'text': f'Position along the specimen from {dic["points"][0]} (mm)'}}},
            }))

        data = []  # stress vs strain: machine and DIC gauge strain
        if 'Strain / %' in cols and 'Stress / MPa' in cols:
            st = thin(len(cols['Strain / %']), MAX_PLOT_POINTS)
            data.append({'type': 'scattergl', 'mode': 'lines', 'name': 'machine strain',
                         'x': clean(cols['Strain / %'][::st]), 'y': clean(cols['Stress / MPa'][::st])})
        if dic is not None and 'stress' in dic:
            st = thin(len(dic['time']), MAX_PLOT_POINTS)
            data.append({'type': 'scattergl', 'mode': 'lines', 'name': f'DIC strain {dic["gauge_points"]}',
                         'x': clean(dic['gauge_strain'][::st]), 'y': clean(dic['stress'][::st])})
        if data:
            figs.append(PlotlyFigure(label='Stress vs strain', figure={'data': data, 'layout': {
                'title': {'text': 'Stress vs strain (machine and DIC gauge)'}, 'showlegend': True,
                'xaxis': {'title': {'text': 'Strain (%)'}}, 'yaxis': {'title': {'text': 'Stress (MPa)'}}}}))

        if dic is not None:  # local strains vs time, one line per segment
            st = thin(len(dic['time']), LOCAL_MAX_POINTS)
            t = clean(dic['time'][::st])
            data = [{'type': 'scattergl', 'mode': 'lines', 'name': seg, 'x': t,
                     'y': clean(dic['local_strain'][::st, k])} for k, seg in enumerate(dic['segments'])]
            data.append({'type': 'scattergl', 'mode': 'lines', 'name': f'gauge {dic["gauge_points"]}', 'x': t,
                         'y': clean(dic['gauge_strain'][::st]), 'line': {'color': 'black', 'width': 3}})
            figs.append(PlotlyFigure(label='Local strains vs time', figure={'data': data, 'layout': {
                'title': {'text': 'Local DIC strains vs time (one line per point pair)'}, 'showlegend': True,
                'xaxis': {'title': {'text': 'Time (s)'}}, 'yaxis': {'title': {'text': 'Strain (%)'}}}}))

        # explorer: all machine channels (+ DIC gauge strain on the machine time)
        groups_cols = dict(cols)
        variables = [(h, lab) for h, lab in labels if np.isfinite(cols[h]).any()]  # skip empty channels
        if dic is not None:
            groups_cols['dic_gauge_strain'] = np.interp(cols['Time / s'], dic['time'], dic['gauge_strain'],
                                                        left=np.nan, right=np.nan)
            variables.append(('dic_gauge_strain', f'DIC strain {dic["gauge_points"]} (%)'))
        keys = [k for k, _ in variables]
        x = 'Strain / %' if 'Strain / %' in keys else keys[0]
        y = ['Stress / MPa'] if 'Stress / MPa' in keys else keys[1:2]
        fig = explorer_figure([('test', groups_cols)], variables, x, y)
        if fig:
            figs.append(PlotlyFigure(label='Explorer (choose x and y)', figure=fig))
        return figs


class WalterBaiRawFile(EntryData):
    """Raw Walter+Bai machine record or DIC export; its data are in the test entry."""

    m_def = Section(label='Walter+Bai / MITTER raw file')
    test_entry = Quantity(type=str, description='Test entry this file belongs to')


m_package.__init_metainfo__()
