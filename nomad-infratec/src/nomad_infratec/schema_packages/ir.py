"""InfraTec infrared camera record (.tdms from the LabVIEW acquisition).

An IR record is its own entry: it may belong to a thermomechanical test (Instron / Mercury,
Walter+Bai ...), to a heat treatment before a test, or to neither. `related_entries` links it to
any other entries (test, heat treatment, sample ...).

On processing the entry reads the .tdms: time, per ROI the mean / max / min temperature and the
profiles along the sample axis, and the temperature field at selected frames. Plots: temperature
vs time, explorer, profiles vs time (map), profile at a chosen time (slider), temperature field
at a chosen time (slider). Frames in which the camera does not yet measure the sample (maximum
below -100 °C) are shown as gaps. Values typed in by hand are never overwritten.
"""

import numpy as np
from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.annotations import ELNAnnotation
from nomad.datamodel.metainfo.plot import PlotlyFigure, PlotSection
from nomad.metainfo import Datetime, MEnum, Quantity, SchemaPackage, Section, SubSection

from nomad_infratec.explorer import explorer_figure
from nomad_infratec.reader import INVALID_BELOW, read_ir, select_frames

m_package = SchemaPackage(name='InfraTec IR records')

PURPOSES = ['heat treatment', 'thermomechanical test', 'calibration', 'other']
STYLE = {'max': 'solid', 'mean': 'dash', 'min': 'dot'}
COLORS = ['#d62728', '#1f77b4', '#2ca02c', '#ff7f0e', '#9467bd', '#8c564b']
STORE_PROFILES = 500   # frames of profiles kept in the archive
MAP_FRAMES, MAP_POINTS = 200, 160
SLIDER_FRAMES = 60
FIELD_PIXELS = 5000    # per frame in the field figure


def _str(rich=False, **kw):
    comp = 'RichTextEditQuantity' if rich else 'StringEditQuantity'
    return Quantity(type=str, a_eln=ELNAnnotation(component=comp), **kw)


def _num(unit=None, **kw):
    return Quantity(type=np.float64, unit=unit, a_eln=ELNAnnotation(component='NumberEditQuantity'), **kw)


def _r(v, digits=5):
    return [None if not np.isfinite(x) else float(f'{x:.{digits}g}') for x in np.asarray(v, float).ravel()]


def _kelvin(name):
    return Quantity(type=np.float64, unit='kelvin', description=(
        f'{name} in K, computed from the °C value (read-only). Used by the search filters: the NOMAD 2.0 '
        'GUI cannot draw histogram filters of °C quantities.'))


def kelvin_copies(section, names):
    """Set <name>_K = <name> converted to kelvin (or unset it if <name> is empty)."""
    for name in names:
        value = getattr(section, name)
        setattr(section, f'{name}_K', None if value is None else float(value.to('kelvin').magnitude))


class IRROI(ArchiveSection):
    m_def = Section(label_quantity='name')
    name = Quantity(type=str)
    description = _str(description='What the ROI covers, e.g. gauge length, whole sample, grip')
    rows = Quantity(type=np.int64, description='px along the sample axis (profile length)')
    columns = Quantity(type=np.int64, description='px across')
    offset = Quantity(type=str, description='ROI offset as stored by the acquisition (px)')
    peak_temperature = Quantity(type=np.float64, unit='celsius')
    mean_temperature = Quantity(type=np.float64, shape=['*'], unit='celsius')
    max_temperature = Quantity(type=np.float64, shape=['*'], unit='celsius')
    min_temperature = Quantity(type=np.float64, shape=['*'], unit='celsius')
    profile_time = Quantity(type=np.float64, shape=['*'], unit='second',
                            description=f'Frames of the stored profiles (up to {STORE_PROFILES})')
    profiles = Quantity(type=np.float64, shape=['*', '*'], unit='celsius',
                        description='Temperature along the sample axis (mean over the ROI width) per frame')


class IRRecord(PlotSection, EntryData):
    """One InfraTec IR camera record (.tdms)."""

    m_def = Section(label='IR record (InfraTec)')

    data_file = Quantity(type=str, description='.tdms file in this upload; read on save',
                         a_eln=ELNAnnotation(component='FileEditQuantity'), a_browser=dict(adaptor='RawFileAdaptor'))
    name = _str()
    purpose = Quantity(type=MEnum(*PURPOSES), a_eln=ELNAnnotation(component='EnumEditQuantity'))
    related_entries = Quantity(type=EntryData, shape=['*'],
                               description='Test, heat treatment or sample entries this record belongs to',
                               a_eln=ELNAnnotation(component='ReferenceEditQuantity'))
    date = Quantity(type=Datetime, a_eln=ELNAnnotation(component='DateTimeEditQuantity'))
    operator = _str()
    camera = _str(description='e.g. InfraTec ImageIR 8300')
    lens = _str()
    emissivity = _num(description='Emissivity set in the camera software')
    specimen = _str(description='Specimen / sample id')
    description = _str(rich=True, description='What was recorded: heat treatment, test, conditions')
    notes = _str(rich=True)

    n_frames = Quantity(type=np.int64)
    valid_frames = Quantity(type=np.int64, description=f'Frames with maximum above {INVALID_BELOW:g} °C')
    frame_interval = Quantity(type=np.float64, unit='second', description='Median time between frames')
    duration = Quantity(type=np.float64, unit='second')
    time = Quantity(type=np.float64, shape=['*'], unit='second', description='From the first frame')
    time_stamp_start = Quantity(type=np.float64, unit='millisecond',
                                description='First time stamp of the acquisition (PC time base, not clock time)')
    peak_temperature = Quantity(type=np.float64, unit='celsius')
    peak_temperature_K = _kelvin('peak_temperature')
    groups_in_file = Quantity(type=str, shape=['*'])
    rois = SubSection(section_def=IRROI, repeats=True)

    def normalize(self, archive, logger):
        if self.data_file:
            try:
                self._read(archive, logger)
            except Exception as e:
                logger.error('could not read the IR record', data_file=self.data_file, exc_info=e)
        kelvin_copies(self, ('peak_temperature',))
        if self.name and archive.metadata is not None:
            archive.metadata.entry_name = self.name
        super().normalize(archive, logger)

    def _read(self, archive, logger):
        with archive.m_context.raw_file(self.data_file, 'rb') as f:
            path = f.name
        d = read_ir(path)
        t, valid, n = d['time'], d['valid'], d['n_frames']
        self.n_frames, self.valid_frames = n, int(valid.sum())
        self.time = t
        self.time_stamp_start = d.get('time_stamp_start_ms')
        if n > 1:
            self.frame_interval = float(np.median(np.diff(t)))
            self.duration = float(t[-1] - t[0])
        self.groups_in_file = d['groups']
        old = {r.name: r for r in self.rois or []}  # keep ROI descriptions typed in by hand
        rois, peaks = [], []
        for name, r in d['rois'].items():
            g = r['geometry']
            roi = IRROI(name=name, rows=g[0] if g else None, columns=g[1] if len(g) > 1 else None,
                        offset=' '.join(str(v) for v in g[2:]) or None,
                        description=old[name].description if name in old else None)
            for k in ('mean', 'max', 'min'):
                if k in r:
                    setattr(roi, f'{k}_temperature', r[k])
            if 'max' in r and valid[:len(r['max'])].any():
                roi.peak_temperature = float(np.max(r['max'][valid[:len(r['max'])]]))
                peaks.append(roi.peak_temperature.magnitude)
            if 'profiles' in r:
                fr = select_frames(len(r['profiles']), valid[:len(r['profiles'])], STORE_PROFILES)
                roi.profile_time, roi.profiles = t[fr], r['profiles'][fr]
            rois.append(roi)
        self.rois = rois
        self.peak_temperature = max(peaks) if peaks else None
        self.figures = [PlotlyFigure(label=lab, figure=fig) for lab, fig in self._figures(d)]
        logger.info('IR record read', frames=n, rois=list(d['rois']))

    # ------------------------------------------------------------------ figures
    @staticmethod
    def _figures(d):
        t, valid = d['time'], d['valid']
        rois = d['rois']
        color = {name: COLORS[i % len(COLORS)] for i, name in enumerate(rois)}
        masked = lambda a: np.where(valid[:len(a)], a, np.nan)  # noqa: E731
        figs = []

        data = []
        for name, r in rois.items():
            for k in ('max', 'mean', 'min'):
                if k in r:
                    data.append({'type': 'scattergl', 'mode': 'lines', 'name': f'{name} {k}', 'x': _r(t[:len(r[k])]),
                                 'y': _r(masked(r[k])), 'line': {'color': color[name], 'dash': STYLE[k]}})
        if data:
            figs.append(('Temperature vs time', {'data': data, 'layout': {
                'title': {'text': 'ROI temperature vs time (max solid, mean dashed, min dotted)'},
                'showlegend': True, 'xaxis': {'title': {'text': 'Time (s)'}},
                'yaxis': {'title': {'text': 'Temperature (°C)'}}}}))

            cols = {'time': t}
            variables = [('time', 'Time (s)')]
            for name, r in rois.items():
                for k in ('max', 'mean', 'min'):
                    if k in r:
                        cols[f'{name}_{k}'] = masked(r[k])
                        variables.append((f'{name}_{k}', f'{name} {k} (°C)'))
            ys = [f'{name}_max' for name, r in rois.items() if 'max' in r]
            ex = explorer_figure([('record', cols)], variables, 'time', ys,
                                 title='Explorer: x menu, y on/off buttons, y scale menu')
            if ex:
                figs.append(('Explorer (choose x and y)', ex))

        prof = {name: r['profiles'] for name, r in rois.items() if 'profiles' in r}
        if prof:
            # profiles vs time: one map per ROI (menu)
            options = []
            for name, P in prof.items():
                fr = select_frames(len(P), valid[:len(P)], MAP_FRAMES)
                step = max(1, int(np.ceil(P.shape[1] / MAP_POINTS)))
                pos = np.arange(P.shape[1])[::step]
                Z = P[fr][:, ::step]
                options.append((name, np.repeat(t[fr], len(pos)), np.tile(pos, len(fr)), Z.ravel()))
            name, x, y, z = options[0]
            figs.append(('Profiles vs time (map)', {
                'data': [{'type': 'heatmap', 'x': _r(x), 'y': _r(y), 'z': _r(z, 4), 'colorscale': 'Inferno',
                          'colorbar': {'title': {'text': '°C'}}, 'hoverongaps': False}],
                'layout': {'title': {'text': 'Temperature along the sample axis vs time'}, 'height': 550,
                           'xaxis': {'title': {'text': 'Time (s)'}},
                           'yaxis': {'title': {'text': 'Position along the sample axis (px)'}},
                           'updatemenus': [{'buttons': [{'label': nm, 'method': 'restyle',
                                                         'args': [{'x': [_r(xx)], 'y': [_r(yy)], 'z': [_r(zz, 4)]}]}
                                                        for nm, xx, yy, zz in options],
                                            'direction': 'down', 'x': 0, 'xanchor': 'left', 'y': 1.12,
                                            'yanchor': 'top'}] if len(options) > 1 else []}}))

            # profile at a chosen time (slider)
            n = min(len(P) for P in prof.values())
            fr = select_frames(n, valid[:n], SLIDER_FRAMES, must=[d['hottest_frame']])
            active = fr.index(d['hottest_frame']) if d['hottest_frame'] in fr else 0
            names = list(prof)
            data = [{'type': 'scatter', 'mode': 'lines', 'name': nm, 'x': list(range(prof[nm].shape[1])),
                     'y': _r(prof[nm][fr[active]]), 'line': {'color': color[nm]}} for nm in names]
            lo = min(np.nanmin(prof[nm][fr]) for nm in names)
            hi = max(np.nanmax(prof[nm][fr]) for nm in names)
            steps = [{'label': f'{t[i]:.1f} s', 'method': 'restyle',
                      'args': [{'y': [_r(prof[nm][i]) for nm in names]}, list(range(len(names)))]} for i in fr]
            figs.append(('Profile at time (slider)', {'data': data, 'layout': {
                'title': {'text': 'Temperature along the sample axis (mean over the ROI width)'}, 'showlegend': True,
                'xaxis': {'title': {'text': 'Position along the sample axis (px)'}},
                'yaxis': {'title': {'text': 'Temperature (°C)'}, 'range': [lo - 0.05 * (hi - lo), hi + 0.05 * (hi - lo)]},
                'sliders': [{'active': active, 'steps': steps, 'currentvalue': {'prefix': 'time: '},
                             'pad': {'t': 50}}]}}))

        for roi, fld in d['fields'].items():
            data3 = fld['data']
            nf, rows, cols = data3.shape
            k = max(1, int(np.ceil(np.sqrt(rows * cols / FIELD_PIXELS))))
            sub = data3[:, ::k, ::k]
            yy, xx = np.meshgrid(np.arange(rows)[::k], np.arange(cols)[::k], indexing='ij')
            ok = [i for i, f in enumerate(fld['frames']) if valid[f]] or list(range(nf))
            lo, hi = float(np.nanmin(sub[ok])), float(np.nanmax(sub[ok]))
            frames = fld['frames']
            active = frames.index(d['hottest_frame']) if d['hottest_frame'] in frames else 0
            steps = [{'label': f'{t[f]:.1f} s', 'method': 'restyle', 'args': [{'z': [_r(sub[i].ravel(), 4)]}, [0]]}
                     for i, f in enumerate(frames)]
            figs.append((f'Temperature field {roi} (slider)', {
                'data': [{'type': 'heatmap', 'x': _r(xx.ravel()), 'y': _r(yy.ravel()), 'z': _r(sub[active].ravel(), 4),
                          'colorscale': 'Inferno', 'zmin': lo, 'zmax': hi, 'colorbar': {'title': {'text': '°C'}}}],
                'layout': {'title': {'text': f'Temperature field {roi} ({cols}×{rows} px'
                                             + (f', every {k}. px shown)' if k > 1 else ')')},
                           'height': 700, 'xaxis': {'title': {'text': 'px'}, 'constrain': 'domain'},
                           'yaxis': {'title': {'text': 'px (sample axis)'}, 'autorange': 'reversed',
                                     'scaleanchor': 'x'},
                           'sliders': [{'active': active, 'steps': steps, 'currentvalue': {'prefix': 'time: '},
                                        'pad': {'t': 50}}]}}))
        return figs


class IRRawFile(EntryData):
    """InfraTec .tdms file; its data are in the IR record entry."""

    m_def = Section(label='InfraTec .tdms (raw file)')
    ir_entry = Quantity(type=str, description='IR record entry (.archive.json) created for this file')


m_package.__init_metainfo__()
