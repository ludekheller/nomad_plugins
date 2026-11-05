"""Thermomechanical test on an SMA specimen: Instron WaveMatrix + Mercury RT DIC (+ IR temperature).

One entry per test folder. The entry reads the WaveMatrix set (TestNNN.*) and the Mercury
export named in `files`, synchronises the two records via force, and builds the plots.
Values typed in by hand (specimen description, notes ...) are never overwritten.
"""

import json
import math
import os

import numpy as np
from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.annotations import ELNAnnotation
from nomad.datamodel.metainfo.plot import PlotlyFigure, PlotSection
from nomad.metainfo import Datetime, MEnum, Quantity, Reference, SchemaPackage, Section, SubSection

from nomad_thermomech import readers as R
from nomad_thermomech.explorer import explorer_figure
from nomad_thermomech.sync import find_offset

m_package = SchemaPackage(name='Thermomechanical tests on SMAs (Instron WaveMatrix + Mercury RT)')

MAX_PLOT_POINTS = 6000  # per trace, keeps the stored figures small
MAX_LOOP_TRACES = 50  # explorer: one line per loop up to this many loops, else one line
EXPLORER_VARIABLES = [
    ('time', 'Time (s)'), ('loop', 'Loop'), ('step', 'Step'),
    ('position', 'Position (mm)'), ('load', 'Load (N)'), ('displacement', 'Displacement (mm)'),
    ('stress', 'Stress (MPa)'), ('strain_from_position', 'Strain from position (%)'),
    ('strain_dic_analog', 'Strain DIC, analogue input (%)'), ('strain_dic', 'Strain DIC, Mercury (%)'),
    ('temperature', 'Temperature (°C)'), ('temperature_dic', 'Temperature, Mercury (°C)'),
]


def _str(rich=False, **kw):
    comp = 'RichTextEditQuantity' if rich else 'StringEditQuantity'
    return Quantity(type=str, a_eln=ELNAnnotation(component=comp), **kw)


def _num(unit, **kw):
    return Quantity(type=np.float64, unit=unit, a_eln=ELNAnnotation(component='NumberEditQuantity'), **kw)


def _file(description):
    return Quantity(type=str, description=description,
                    a_eln=ELNAnnotation(component='FileEditQuantity'), a_browser=dict(adaptor='RawFileAdaptor'))


def _enum(values, **kw):
    return Quantity(type=MEnum(*values), a_eln=ELNAnnotation(component='EnumEditQuantity'), **kw)


LOADING_MODES = ['tension', 'compression', 'tension-compression', 'torsion', 'biaxial']
SHAPES = ['round', 'rectangular', 'tube', 'wire', 'other']
CAMPAIGN_FILE = 'campaign.archive.json'


def _arr(unit=None, **kw):
    return Quantity(type=np.float64, shape=['*'], unit=unit, **kw)


# ------------------------------------------------------------------ sections
class TestFiles(ArchiveSection):
    m_def = Section(a_eln=dict(overview=True))
    wavematrix_log = _file('TestNNN.log (WaveMatrix event log)')
    wavematrix_data = _file('TestNNN.Stop.csv (full record) or TestNNN.steps.tracking.csv')
    wavematrix_trends = _file('TestNNN.steps.trends.csv (per step/loop summary)')
    wavematrix_specimen = _file('TestNNN.specimen.txt')
    wavematrix_method = _file('TestNNN.itr_wma (method, Instron XML)')
    wavematrix_results = _file('TestNNN.im_gpf (results, Instron XML)')
    mercury_export = _file('Mercury RT export (;-separated CSV)')


class Specimen(ArchiveSection):
    m_def = Section(a_eln=dict(overview=True))
    specimen_id = _str()
    material = _str(description='e.g. NiTi, NiTiHf, NiTiNb')
    nominal_composition = _str()
    semi_product = _str(description='wire, ribbon, sheet, bar, LPBF part ...')
    processing_history = _str(rich=True, description='heat treatment, cold work, training ...')
    specimen_type = _str()
    cross_section_shape = _enum(SHAPES)
    diameter = _num('millimeter', description='round / wire; outer diameter of a tube')
    inner_diameter = _num('millimeter', description='tube only')
    width = _num('millimeter', description='rectangular only')
    thickness = _num('millimeter', description='rectangular only')
    cross_section_area = Quantity(type=np.float64, unit='millimeter ** 2',
                                  a_eln=ELNAnnotation(component='NumberEditQuantity'),
                                  description='From WaveMatrix specimen.txt, or computed from the dimensions')
    gauge_length = _num('millimeter', description='Initial length of the DIC virtual extensometer')


class Instrument(ArchiveSection):
    m_def = Section(a_eln=dict(overview=True))
    testing_machine = _str()
    frame_serial = _str()
    wavematrix_version = Quantity(type=str)
    console_version = Quantity(type=str)
    controller_version = Quantity(type=str)
    computer_name = Quantity(type=str)
    dic_software = _str()
    dic_extensometer = _str()
    temperature_measurement = _str(rich=True)


class Synchronisation(ArchiveSection):
    m_def = Section(a_eln=dict(overview=True))
    method = Quantity(type=str)
    time_offset = Quantity(type=np.float64, unit='second',
                           description='Mercury time 0 on the WaveMatrix time axis')
    force_correlation = Quantity(type=np.float64, description='Pearson r of the aligned forces')
    force_scale = Quantity(type=np.float64, description='F_WaveMatrix = scale * F_Mercury + intercept')
    force_intercept = Quantity(type=np.float64, unit='newton')
    overlap_points = Quantity(type=int)
    pc_clock_offset = Quantity(type=np.float64, unit='second',
                               description='Offset from the two PC clocks (for information only)')


class WaveMatrixData(ArchiveSection):
    columns = Quantity(type=str, shape=['*'], description='All columns of the WaveMatrix file')
    time = _arr('second')
    step = _arr()
    loop = _arr()
    position = _arr('millimeter')
    load = _arr('newton')
    displacement = _arr('millimeter')
    stress = _arr('megapascal')
    strain_from_position = _arr(description='%')
    temperature = _arr('celsius')
    strain_dic_analog = _arr(description='% - DIC strain received through the analogue input')


class MercuryData(ArchiveSection):
    columns = Quantity(type=str, shape=['*'])
    time = _arr('second', description='Mercury computer clock time')
    time_aligned = _arr('second', description='Mercury time on the WaveMatrix time axis')
    frame_id = _arr()
    gauge_length = _arr('millimeter')
    strain = _arr(description='% - virtual extensometer')
    stress = _arr('megapascal')
    temperature = _arr('celsius')
    force = _arr('newton')


class CycleSummary(ArchiveSection):
    m_def = Section(label_quantity='label')
    label = Quantity(type=str)
    step = Quantity(type=int)
    loop = Quantity(type=int)
    start_time = Quantity(type=np.float64, unit='second')
    frequency = Quantity(type=np.float64, unit='hertz')
    load_max = Quantity(type=np.float64, unit='newton')
    load_min = Quantity(type=np.float64, unit='newton')
    stress_max = Quantity(type=np.float64, unit='megapascal')
    stress_min = Quantity(type=np.float64, unit='megapascal')
    stress_mean = Quantity(type=np.float64, unit='megapascal')
    displacement_max = Quantity(type=np.float64, unit='millimeter')
    displacement_min = Quantity(type=np.float64, unit='millimeter')
    temperature_max = Quantity(type=np.float64, unit='celsius')
    temperature_min = Quantity(type=np.float64, unit='celsius')


class ThermomechTest(PlotSection, EntryData):
    """One thermomechanical test (one folder: WaveMatrix TestNNN.* + Mercury export)."""

    m_def = Section(label='Thermomechanical test (WaveMatrix + Mercury)')

    name = _str(description='Entry name: <WaveMatrix test>__<Mercury export>')
    test_name = Quantity(type=str)
    method = _str()
    start_time = Quantity(type=Datetime, a_eln=ELNAnnotation(component='DateTimeEditQuantity'))
    end_time = Quantity(type=Datetime)
    duration = Quantity(type=np.float64, unit='second')
    status = Quantity(type=str)
    operator = _str()
    loading_mode = _enum(LOADING_MODES)
    test_type = _str(description='e.g. superelastic cycling, isothermal tensile test, thermal cycling under load')
    test_temperature = _num('celsius')
    strain_rate = _num('1 / second')
    campaign_file = Quantity(type=str, description='Campaign entry whose values filled the empty fields',
                             a_browser=dict(adaptor='RawFileAdaptor'))
    campaign_filled = Quantity(type=str, description='Values taken from the campaign (internal, JSON)')
    test_description = _str(rich=True, description='Test type and conditions, e.g. superelastic cycling ...')
    notes = _str(rich=True)

    files = SubSection(section_def=TestFiles)
    specimen = SubSection(section_def=Specimen)
    instrument = SubSection(section_def=Instrument)
    synchronisation = SubSection(section_def=Synchronisation)
    wavematrix = SubSection(section_def=WaveMatrixData)
    mercury = SubSection(section_def=MercuryData)
    cycles = SubSection(section_def=CycleSummary, repeats=True)
    log_events = Quantity(type=str, shape=['*'])

    # -------------------------------------------------------------- normalize
    def normalize(self, archive, logger):
        if self.files is not None and (self.files.wavematrix_data or self.files.wavematrix_log):
            try:
                self._read_files(archive, logger)
            except Exception as e:
                logger.error('could not read the test files', exc_info=e)
        try:
            self._apply_campaign(archive, logger)
        except Exception as e:
            logger.warning('could not apply the campaign values', exc_info=e)
        self._compute_area()
        if self.name and archive.metadata is not None:
            archive.metadata.entry_name = self.name
        super().normalize(archive, logger)

    # -------------------------------------------------------------- campaign
    def _folder(self):
        f = self.files.wavematrix_log if self.files is not None else None
        return os.path.dirname(f) if f else None

    def _apply_campaign(self, archive, logger):
        """Fill empty fields from the nearest campaign.archive.json in this or a parent folder.

        A field counts as empty if it has no value, or if it still holds the value taken from the
        campaign last time (so edits of the campaign propagate, hand-entered values are kept).
        """
        folder = self._folder()
        if folder is None:
            return
        context = archive.m_context
        path = find_campaign(_raw_root(context), folder)
        if path is None:
            self.campaign_file = None
            return
        with context.raw_file(path, 'r') as f:
            camp = json.load(f).get('data', {})
        self.campaign_file = path
        before = json.loads(self.campaign_filled) if self.campaign_filled else {}
        filled = {}
        for key, (sec_name, q) in CAMPAIGN_FIELDS.items():
            value = camp.get(key)
            if value in (None, ''):
                continue
            target = self
            if sec_name:
                if getattr(self, sec_name) is None:
                    setattr(self, sec_name, Specimen())
                target = getattr(self, sec_name)
            current = getattr(target, q)
            current = getattr(current, 'magnitude', current)
            if current is None or (key in before and _same(current, before[key])):
                setattr(target, q, value)
                filled[key] = value
            elif key in before and not _same(current, before[key]):
                pass  # changed by hand -> keep
        self.campaign_filled = json.dumps(filled) if filled else None
        if filled:
            logger.info('values filled from the campaign', campaign=path, fields=sorted(filled))

    def _compute_area(self):
        s = self.specimen
        if s is None or s.cross_section_area is not None or not s.cross_section_shape:
            return
        mm = lambda q: None if q is None else q.to('millimeter').magnitude  # noqa: E731
        d, di, w, t = mm(s.diameter), mm(s.inner_diameter), mm(s.width), mm(s.thickness)
        area = None
        if s.cross_section_shape in ('round', 'wire') and d:
            area = math.pi * d ** 2 / 4
        elif s.cross_section_shape == 'tube' and d and di:
            area = math.pi * (d ** 2 - di ** 2) / 4
        elif s.cross_section_shape == 'rectangular' and w and t:
            area = w * t
        if area:
            s.cross_section_area = area

    def _read(self, archive, path, encoding='utf-8-sig'):
        with archive.m_context.raw_file(path, 'r', encoding=encoding, errors='replace') as f:
            return f.read()

    def _fill(self, section_name, section_def, values):
        """Create the sub-section if needed; set only quantities that are still empty."""
        values = {k: v for k, v in values.items() if v is not None and not (isinstance(v, float) and np.isnan(v))}
        if not values:
            return
        if getattr(self, section_name) is None:
            setattr(self, section_name, section_def())
        target = getattr(self, section_name)
        for k, v in values.items():
            if getattr(target, k) is None:
                setattr(target, k, v)

    def _read_files(self, archive, logger):
        f = self.files
        log = R.read_log(self._read(archive, f.wavematrix_log)) if f.wavematrix_log else {}
        spec = R.read_specimen(self._read(archive, f.wavematrix_specimen)) if f.wavematrix_specimen else {}
        wm = R.read_wavematrix_data(self._read(archive, f.wavematrix_data)) if f.wavematrix_data else None
        trends = R.read_trends(self._read(archive, f.wavematrix_trends)) if f.wavematrix_trends else []
        mc = mm = None
        if f.mercury_export:
            mc, mm = R.read_mercury(self._read(archive, f.mercury_export, encoding='utf-8'))

        # ---- metadata (fill only empty)
        for q, v in (('test_name', log.get('test_name')), ('method', log.get('method')),
                     ('start_time', log.get('start_time')), ('end_time', log.get('end_time')),
                     ('status', log.get('Test Status')), ('duration', R._float(log.get('Total Time')))):
            if v is not None and getattr(self, q) is None and not (isinstance(v, float) and np.isnan(v)):
                setattr(self, q, v)
        if log.get('events'):
            self.log_events = log['events']
        area = spec.get('cross_section_area_mm2')
        self._fill('specimen', Specimen, {
            'specimen_type': spec.get('specimen_type'),
            'cross_section_area': area,
            'gauge_length': (mm or {}).get('gauge_length_mm'),
        })
        self._fill('instrument', Instrument, {
            'testing_machine': 'Instron ElectroPuls E10000' if log else None,
            'frame_serial': log.get('Frame Serial Number'),
            'wavematrix_version': log.get('Software Version'),
            'console_version': log.get('Console Version'),
            'controller_version': log.get('Controller Version'),
            'computer_name': log.get('Computer Name'),
            'dic_software': 'Mercury RT' if mc is not None else None,
            'dic_extensometer': ', '.join((mm or {}).get('extensometers', [])) or None,
        })

        # ---- WaveMatrix record (always rebuilt)
        if wm is not None:
            col = lambda *c: R.find_column(wm, *c)  # noqa: E731
            w = WaveMatrixData(columns=list(wm))
            for q, names in (('time', ['Total Time']), ('step', ['Step']), ('loop', ['Loop']),
                             ('position', ['Axial Position']), ('load', ['Axial Load']),
                             ('displacement', ['Axial Displacement']), ('stress', ['Axial Stress']),
                             ('strain_from_position', ['Axial Strain from position', 'Axial Strain']),
                             ('temperature', ['Temperature']), ('strain_dic_analog', ['Strain DIC'])):
                c = col(*names)
                if c is not None:
                    setattr(w, q, np.nan_to_num(wm[c]))
            self.wavematrix = w

        # ---- per-cycle summary (always rebuilt)
        if trends:
            def g(row, *names):
                for n in names:
                    for k, v in row.items():
                        if k.startswith(n):
                            return None if np.isnan(v) else v
                return None
            cyc = []
            for row in trends:
                c = CycleSummary(step=int(g(row, 'Step') or 0), loop=int(g(row, 'Loop') or 0))
                c.label = f'loop {c.loop}, step {c.step}'
                for q, n in (('start_time', 'PC:Cycle Start Time'), ('frequency', 'PC:Frequency'),
                             ('load_max', 'Axial Load:Maximum'), ('load_min', 'Axial Load:Minimum'),
                             ('stress_max', 'Axial Stress:Maximum'), ('stress_min', 'Axial Stress:Minimum'),
                             ('stress_mean', 'Axial Stress:Average'),
                             ('displacement_max', 'Axial Displacement:Maximum'),
                             ('displacement_min', 'Axial Displacement:Minimum'),
                             ('temperature_max', 'Temperature:Maximum'), ('temperature_min', 'Temperature:Minimum')):
                    v = g(row, n)
                    if v is not None:
                        setattr(c, q, v)
                cyc.append(c)
            self.cycles = cyc

        # ---- Mercury record + synchronisation (always rebuilt)
        sync = None
        if mc is not None:
            t_m = mc[R.find_column(mc, 'Computer Clock Time')]
            f_m_col = R.find_column(mc, 'Testing Machine: Force', 'Force')
            if wm is not None and f_m_col is not None and self.wavematrix.load is not None:
                sync = find_offset(self.wavematrix.time, self.wavematrix.load, t_m, mc[f_m_col])
                pc = None
                tstamp = R.find_column(wm, 'Time Stamp')
                if tstamp is not None:
                    pc = (mm['start_time'] - R.excel_to_datetime(wm[tstamp][0])).total_seconds()
                self.synchronisation = Synchronisation(
                    method='normalised cross-correlation of the force recorded by both systems',
                    time_offset=sync['offset'], force_correlation=sync['r'],
                    force_scale=sync['scale'], force_intercept=sync['intercept'],
                    overlap_points=sync['n_points'], pc_clock_offset=pc)
                if sync['r'] < 0.99:
                    logger.warning('weak force correlation - check the synchronisation', r=sync['r'])
            ext = (mm.get('extensometers') or ['A1'])[0]
            m = MercuryData(columns=list(mc) + ['Absolute Timestamp'], time=t_m)
            if sync:
                m.time_aligned = t_m + sync['offset']
            for q, names in (('frame_id', ['Frame ID']), ('gauge_length', [f'{ext} - Length [']),
                             ('strain', [f'{ext} - Length: Extension']), ('stress', [f'{ext} - Stress']),
                             ('temperature', ['Default [°C]', 'Temperature']), ('force', ['Testing Machine: Force'])):
                c = R.find_column(mc, *names)
                if c is not None:
                    setattr(m, q, np.nan_to_num(mc[c]))
            self.mercury = m

        self.figures = self._figures()
        logger.info('thermomechanical test read', wavematrix_points=0 if wm is None else len(self.wavematrix.time),
                    mercury_points=0 if mc is None else len(self.mercury.time),
                    time_offset=None if sync is None else sync['offset'],
                    force_r=None if sync is None else sync['r'])

    # -------------------------------------------------------------- figures
    @staticmethod
    def _thin(*arrays):
        n = len(arrays[0])
        step = max(1, int(np.ceil(n / MAX_PLOT_POINTS)))
        return [np.asarray(a)[::step].tolist() for a in arrays]

    def _figures(self):
        figs = []
        w, m = self.wavematrix, self.mercury
        mag = lambda q: None if q is None else np.asarray(getattr(q, 'magnitude', q))  # noqa: E731

        # 1) stress vs DIC strain, one line per loop
        if m is not None and m.time_aligned is not None and m.strain is not None and w is not None:
            tm, tw = mag(m.time_aligned), mag(w.time)
            stress = np.interp(tm, tw, mag(w.stress), left=np.nan, right=np.nan)
            # loop number: nearest WaveMatrix sample (no interpolation between loops)
            idx = np.clip(np.searchsorted(tw, tm), 0, len(tw) - 1)
            loop = np.where((tm < tw[0]) | (tm > tw[-1]), np.nan, mag(w.loop)[idx])
            strain = mag(m.strain)
            data = []
            for lp in np.unique(loop[~np.isnan(loop)]).astype(int):
                sel = (np.round(loop) == lp) & ~np.isnan(stress)
                if sel.sum() < 2:
                    continue
                x, y = self._thin(strain[sel], stress[sel])
                data.append({'type': 'scattergl', 'mode': 'lines', 'name': f'loop {lp}', 'x': x, 'y': y})
            figs.append(PlotlyFigure(label='Stress - strain (DIC)', index=0, figure={'data': data, 'layout': {
                'title': {'text': 'Stress (WaveMatrix) vs strain (DIC extensometer)'},
                'xaxis': {'title': {'text': 'Strain DIC (%)'}}, 'yaxis': {'title': {'text': 'Stress (MPa)'}}}}))

        # 2) stress and temperature vs time
        if w is not None and w.time is not None:
            t, s, T = self._thin(mag(w.time), mag(w.stress), mag(w.temperature))
            figs.append(PlotlyFigure(label='Stress and temperature vs time', index=1, figure={'data': [
                {'type': 'scattergl', 'mode': 'lines', 'name': 'stress', 'x': t, 'y': s},
                {'type': 'scattergl', 'mode': 'lines', 'name': 'temperature', 'x': t, 'y': T, 'yaxis': 'y2'}],
                'layout': {'title': {'text': 'Stress and temperature vs time'},
                           'xaxis': {'title': {'text': 'Time (s)'}},
                           'yaxis': {'title': {'text': 'Stress (MPa)'}},
                           'yaxis2': {'title': {'text': 'Temperature (°C)'}, 'overlaying': 'y', 'side': 'right'}}}))

        # 3) strain vs time: DIC (Mercury, aligned) and from position (WaveMatrix)
        if w is not None and w.time is not None:
            data = []
            if m is not None and m.time_aligned is not None and m.strain is not None:
                x, y = self._thin(mag(m.time_aligned), mag(m.strain))
                data.append({'type': 'scattergl', 'mode': 'lines', 'name': 'DIC (Mercury)', 'x': x, 'y': y})
            if w.strain_from_position is not None:
                x, y = self._thin(mag(w.time), mag(w.strain_from_position))
                data.append({'type': 'scattergl', 'mode': 'lines', 'name': 'from position (WaveMatrix)', 'x': x, 'y': y})
            figs.append(PlotlyFigure(label='Strain vs time', index=2, figure={'data': data, 'layout': {
                'title': {'text': 'Strain vs time'}, 'xaxis': {'title': {'text': 'Time (s)'}},
                'yaxis': {'title': {'text': 'Strain (%)'}}}}))

        # 4) synchronisation check: both forces on the WaveMatrix time axis
        if m is not None and m.time_aligned is not None and m.force is not None and w is not None:
            x1, y1 = self._thin(mag(w.time), mag(w.load))
            x2, y2 = self._thin(mag(m.time_aligned), mag(m.force))
            r = self.synchronisation.force_correlation if self.synchronisation else None
            figs.append(PlotlyFigure(label='Synchronisation check (force)', index=3, figure={'data': [
                {'type': 'scattergl', 'mode': 'lines', 'name': 'WaveMatrix', 'x': x1, 'y': y1},
                {'type': 'scattergl', 'mode': 'lines', 'name': 'Mercury (shifted)', 'x': x2, 'y': y2}],
                'layout': {'title': {'text': f'Force from both systems after alignment (r = {r:.5f})' if r else 'Force'},
                           'xaxis': {'title': {'text': 'Time (s)'}}, 'yaxis': {'title': {'text': 'Force (N)'}}}}))
        explorer = self._explorer()
        if explorer:
            figs.append(PlotlyFigure(label='Explorer (choose x and y)', figure=explorer))
        return figs

    def _explorer(self):
        """x/y explorer over the WaveMatrix record (+ Mercury values interpolated onto it)."""
        w, m = self.wavematrix, self.mercury
        if w is None or w.time is None:
            return None
        mag = lambda q: None if q is None else np.asarray(getattr(q, 'magnitude', q), dtype=float)  # noqa: E731
        cols = {k: mag(getattr(w, k)) for k, _ in EXPLORER_VARIABLES if k in WaveMatrixData.m_def.all_quantities}
        tw = cols['time']
        if m is not None and m.time_aligned is not None:
            tm = mag(m.time_aligned)
            for key, q in (('strain_dic', m.strain), ('temperature_dic', m.temperature)):
                if q is not None:
                    cols[key] = np.interp(tw, tm, mag(q), left=np.nan, right=np.nan)
        cols = {k: v for k, v in cols.items() if v is not None and len(v) == len(tw)}
        loop = cols.get('loop')
        loops = np.unique(np.round(loop[~np.isnan(loop)])) if loop is not None else []
        if 1 < len(loops) <= MAX_LOOP_TRACES:
            groups = [(f'loop {int(lp)}', {k: v[np.round(loop) == lp] for k, v in cols.items()}) for lp in loops]
        else:
            groups = [('all data', cols)]
        x = 'strain_dic' if 'strain_dic' in cols else 'strain_dic_analog' if 'strain_dic_analog' in cols else 'time'
        return explorer_figure(groups, EXPLORER_VARIABLES, x, ['stress'],
                               title='Explorer: x menu, y on/off buttons (below), y scale menu')


def _raw_root(context):
    """Absolute path of the upload's raw folder (local: ClientContext.local_dir)."""
    root = getattr(context, 'local_dir', None)
    if root is None:
        try:
            root = context.raw_path()
        except Exception:
            root = None
    return root


def _m_def(path):
    try:
        with open(path) as f:
            return str(json.load(f).get('data', {}).get('m_def', ''))
    except Exception:
        return ''


def find_campaign(root, folder):
    """Upload-relative path of the nearest campaign entry in `folder` or a parent folder.

    Any *.archive.json with a ThermomechCampaign counts; campaign.archive.json is checked first.
    """
    if root is None or folder is None:
        return None
    parts = folder.split('/') if folder else []
    for i in range(len(parts), -1, -1):
        rel = '/'.join(parts[:i])
        d = os.path.join(root, rel)
        if not os.path.isdir(d):
            continue
        names = sorted(n for n in os.listdir(d) if n.endswith('.archive.json'))
        names.sort(key=lambda n: n != CAMPAIGN_FILE)
        for n in names:
            if _m_def(os.path.join(d, n)).endswith('.ThermomechCampaign'):
                return os.path.join(rel, n) if rel else n
    return None


def _same(a, b):
    if isinstance(a, (int, float, np.floating)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=1e-9)
    return a == b


# campaign quantity -> (sub-section of the test or '' for the test itself, quantity name)
CAMPAIGN_FIELDS = {
    'loading_mode': ('', 'loading_mode'), 'test_type': ('', 'test_type'),
    'test_temperature': ('', 'test_temperature'), 'strain_rate': ('', 'strain_rate'),
    'material': ('specimen', 'material'), 'nominal_composition': ('specimen', 'nominal_composition'),
    'semi_product': ('specimen', 'semi_product'), 'processing_history': ('specimen', 'processing_history'),
    'cross_section_shape': ('specimen', 'cross_section_shape'), 'diameter': ('specimen', 'diameter'),
    'inner_diameter': ('specimen', 'inner_diameter'), 'width': ('specimen', 'width'),
    'thickness': ('specimen', 'thickness'),
}


class ThermomechCampaign(EntryData):
    """A campaign of thermomechanical tests sharing loading mode, material and specimen geometry.

    Create it in a folder (any name; campaign.archive.json is a good choice): every test entry in
    that folder and its subfolders fills its empty fields from the nearest campaign, and the
    campaign lists those tests.
    """

    m_def = Section(label='Thermomechanical test campaign')
    name = _str()
    description = _str(rich=True)
    loading_mode = _enum(LOADING_MODES)
    test_type = _str(description='e.g. superelastic cycling, isothermal tensile test, thermal cycling under load')
    test_temperature = _num('celsius')
    strain_rate = _num('1 / second')
    material = _str(description='e.g. NiTi, NiTiHf, NiTiNb')
    nominal_composition = _str()
    semi_product = _str(description='wire, ribbon, sheet, bar, LPBF part ...')
    processing_history = _str(rich=True)
    cross_section_shape = _enum(SHAPES)
    diameter = _num('millimeter', description='round / wire; outer diameter of a tube')
    inner_diameter = _num('millimeter', description='tube only')
    width = _num('millimeter', description='rectangular only')
    thickness = _num('millimeter', description='rectangular only')
    n_tests = Quantity(type=int)
    tests = Quantity(type=Reference(ThermomechTest.m_def), shape=['*'],
                     description='Test entries in this folder and its subfolders')

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if self.name and archive.metadata is not None:
            archive.metadata.entry_name = self.name
        mainfile = archive.metadata.mainfile if archive.metadata is not None else None
        context = archive.m_context
        root = _raw_root(context)
        if not mainfile or not root:
            return
        folder = os.path.dirname(mainfile)
        found = []
        for dirpath, _, names in os.walk(os.path.join(root, folder)):
            for n in sorted(names):
                if not n.endswith('.archive.json'):
                    continue
                full = os.path.join(dirpath, n)
                if not _m_def(full).endswith('.ThermomechTest'):
                    continue
                rel = os.path.relpath(full, root)
                if find_campaign(root, os.path.dirname(rel)) == mainfile:  # not claimed by a nearer campaign
                    found.append(rel)
        found.sort()
        self.n_tests = len(found)
        self.tests = [f'../upload/archive/mainfile/{p}#data' for p in found] or None
        # reprocess the tests so they pick up the (changed) campaign values
        for p in found:
            try:
                context.process_updated_raw_file(p, allow_modify=True)
            except NotImplementedError:
                break  # local processing
            except Exception as e:
                logger.warning('could not reprocess test entry', entry=p, exc_info=e)


class WaveMatrixTestLog(EntryData):
    """Raw WaveMatrix test log; the test itself is in the linked thermomechanical-test entry."""

    m_def = Section(label='WaveMatrix test log (raw file)')
    test_entry = Quantity(type=str, description='Thermomechanical-test entry created for this folder')


class MercuryExport(EntryData):
    """Raw Mercury RT export; its data are in the thermomechanical-test entry of the folder."""

    m_def = Section(label='Mercury RT export (raw file)')
    test_entry = Quantity(type=str, description='Thermomechanical-test entry this export was added to')


m_package.__init_metainfo__()
