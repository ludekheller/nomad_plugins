"""Glue between the NOMAD DSC entry and the tangent-method engine (evaluation.py).

* `evaluate_entry`: runs the evaluation selected by the mode (entry field, else folder settings),
  stores the peaks, fills Ms/Mf/As/Af (+ numbered peaks, peak temperatures, enthalpies) and adds the
  plot 'Evaluation (tangent method)'.
* `fill`: writes automatic values into the results without overwriting values entered by hand.
* Folder settings: the nearest dsc_evaluation.archive.json (or any *.archive.json holding
  DSC_EvaluationSettings) in the entry's folder or a parent folder.
"""

import json
import os

import numpy as np

from nomad_dsc_trios import evaluation as E

SETTINGS_FILE = 'dsc_evaluation.archive.json'
PARAMS = ('sg_window', 'sg_order', 'min_height_percent', 'noise_factor', 'min_area', 'skip_start',
          'curvature_window', 'knee_fraction')
MAX_NUMBERED = 3
DEFAULT_MODE, DEFAULT_CYCLE = 'off', 1
DIGITS = 2  # stored temperatures (°C) and enthalpies (J/g)


def _r(x):
    return None if x is None or not np.isfinite(x) else round(float(x), DIGITS)


def defaults():
    """All parameters with their default values (units of the schema quantities)."""
    return {'mode': DEFAULT_MODE, 'cycle': DEFAULT_CYCLE, **{k: E.DEFAULTS[k] for k in PARAMS}}


def fill_defaults(section):
    """Fill empty parameter fields of a settings section with the defaults."""
    for k, v in defaults().items():
        if getattr(section, k) is None:
            setattr(section, k, v)


# ------------------------------------------------------------------ bookkeeping of automatic values
def _plain(v):
    v = getattr(v, 'magnitude', v)
    return float(v) if isinstance(v, (int, float, np.floating, np.integer)) else v


def _same(a, b):
    if isinstance(a, float) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-6 * max(1.0, abs(b))
    return a == b


def fill(results, values, source, clear=()):
    """Set results fields from `values` unless they hold a value entered by hand.

    A field may be (re)written if it is empty or still equals the value written automatically last
    time (recorded in results.auto_filled). Fields in `clear` that are not in `values` are emptied
    under the same condition (e.g. a numbered peak that is no longer found).
    """
    rec = json.loads(results.auto_filled) if results.auto_filled else {}
    for k, v in values.items():
        if v is None:
            continue
        cur = _plain(getattr(results, k))
        if cur is None or (k in rec and _same(cur, rec[k]['value'])):
            setattr(results, k, v)
            rec[k] = {'value': v, 'source': source}
    for k in clear:
        if k in values or k not in rec:
            continue
        cur = _plain(getattr(results, k))
        if cur is None or _same(cur, rec[k]['value']):
            setattr(results, k, None)
            del rec[k]
    results.auto_filled = json.dumps(rec) if rec else None


# ------------------------------------------------------------------ folder settings
def _raw_root(context):
    root = getattr(context, 'local_dir', None)
    if root is None:
        try:
            root = context.raw_path()
        except Exception:
            root = None
    return root


def find_settings_in(root, folder):
    """(settings dict, upload-relative path) of the nearest folder settings at or above `folder`."""
    if not root:
        return {}, None
    parts = folder.split('/') if folder else []
    for i in range(len(parts), -1, -1):
        rel = '/'.join(parts[:i])
        d = os.path.join(root, rel)
        if not os.path.isdir(d):
            continue
        names = sorted(n for n in os.listdir(d) if n.endswith('.archive.json'))
        names.sort(key=lambda n: n != SETTINGS_FILE)
        for n in names:
            try:
                with open(os.path.join(d, n)) as f:
                    data = json.load(f).get('data', {})
            except (OSError, ValueError):
                continue
            if str(data.get('m_def', '')).endswith('.DSC_EvaluationSettings'):
                return data, (os.path.join(rel, n) if rel else n)
    return {}, None


def reprocess_folder(archive, logger=None, folder=None):
    """Send all DSC entries in `folder` (default: the folder of `archive`) and its sub-folders to
    processing again; the entry of `archive` itself is skipped."""
    mainfile = getattr(archive.metadata, 'mainfile', None) if archive.metadata is not None else None
    root = _raw_root(archive.m_context) if archive.m_context is not None else None
    if not mainfile or not root:
        return 0
    if folder is None:
        folder = os.path.dirname(mainfile)
    n = 0
    for dirpath, _, files in os.walk(os.path.join(root, folder)):
        for name in sorted(files):
            if not name.endswith('.archive.json'):
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path) as f:
                    m_def = str(json.load(f).get('data', {}).get('m_def', ''))
            except (OSError, ValueError):
                continue
            if m_def.endswith('.DSC_SMA') and os.path.relpath(path, root) != mainfile:
                try:
                    archive.m_context.process_updated_raw_file(os.path.relpath(path, root), allow_modify=True)
                    n += 1
                except NotImplementedError:
                    pass
                except Exception as e:
                    if logger:
                        logger.warning('could not process DSC entry', path=path, exc_info=e)
    return n


def find_settings(archive):
    mainfile = getattr(archive.metadata, 'mainfile', None) if archive.metadata is not None else None
    root = _raw_root(archive.m_context) if archive.m_context is not None else None
    if not mainfile:
        return {}, None
    return find_settings_in(root, os.path.dirname(mainfile))


def create_default_settings(context, folder, settings_def, logger=None):
    """Create <folder>/dsc_evaluation.archive.json with all defaults (mode off), unless settings exist
    at or above `folder`. Atomic: when many curves of one upload are processed at once, exactly one
    creates the file; returns its path or None."""
    root = _raw_root(context)
    if not root or find_settings_in(root, folder)[1] is not None:
        return None
    rel = os.path.join(folder, SETTINGS_FILE) if folder else SETTINGS_FILE
    try:
        fd = os.open(os.path.join(root, rel), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return None
    except OSError as e:
        if logger:
            logger.warning('could not create the DSC evaluation settings', path=rel, exc_info=e)
        return None
    with os.fdopen(fd, 'w') as f:
        json.dump({'data': {'m_def': settings_def, **defaults()}}, f, indent=2)
    try:
        context.process_updated_raw_file(rel, allow_modify=True)
    except NotImplementedError:
        pass
    except Exception as e:
        if logger:
            logger.warning('could not process the DSC evaluation settings', path=rel, exc_info=e)
    if logger:
        logger.info('created DSC evaluation settings for the folder (mode off)', path=rel)
    return rel


# ------------------------------------------------------------------ evaluation
def _get(obj, key):
    """Field of a metainfo section or of a dict (archive JSON), as a plain value."""
    if obj is None:
        return None
    return _plain(obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None))


def select_ramps(segments, cycle):
    """{'cooling': (T, q, t), 'heating': (T, q, t)} of the given cycle (1-based); sections or dicts."""
    parts, c = {'cooling': [], 'heating': []}, 0
    for s in segments:
        kind = _get(s, 'segment_type') or ''
        if kind == 'ramp_cooling':
            c += 1
        if c != cycle or not kind.startswith('ramp_') or _get(s, 'temperature') is None:
            continue
        parts['cooling' if kind == 'ramp_cooling' else 'heating'].append(s)
    out = {}
    for name, segs in parts.items():
        if segs:
            out[name] = tuple(np.concatenate([np.asarray(_get(s, q), dtype=float) for s in segs])
                              for q in ('temperature', 'heat_flow_normalized', 'time'))
    return out, c


def _effective(ev, settings):
    p = {}
    for k in PARAMS:
        v = _get(ev, k)
        if v is None:
            v = settings.get(k)
        if v is not None:
            p[k] = v
    return p


def _windows(ev, settings):
    out = {'cooling': [], 'heating': []}
    src = [(_get(w, 'ramp'), _get(w, 'T1'), _get(w, 'T2')) for w in (_get(ev, 'windows') or [])]
    if not src:
        src = [(_get(w, 'ramp'), _get(w, 'T1'), _get(w, 'T2')) for w in settings.get('windows') or []]
    for ramp, a, b in src:
        if ramp in out and a is not None and b is not None:
            out[ramp].append((a, b))
    return out


class Evaluation:
    """Result of `evaluate`: ramps, values for the results section, messages, parameters used."""

    def __init__(self, mode, cycle, params, windows, results_by_ramp, messages):
        self.mode, self.cycle, self.params, self.windows = mode, cycle, params, windows
        self.results_by_ramp, self.messages = results_by_ramp, messages
        self.values = result_values(results_by_ramp, mode, cycle, messages)

    @property
    def used(self):
        used = {'mode': self.mode, 'cycle': self.cycle, **{k: {**E.DEFAULTS, **self.params}[k] for k in PARAMS}}
        if self.mode == 'semi-automatic':
            used['windows'] = self.windows
        return used


def evaluate(segments, exo_up, ev=None, settings=None, mode=None):
    """Tangent-method evaluation of one run.

    segments: DSC segments (sections or dicts as in the archive JSON); ev: the entry's evaluation
    (section or dict) whose empty fields fall back to `settings` (folder) and the defaults.
    Returns None if the mode is off.
    """
    settings = settings or {}
    mode = mode or _get(ev, 'mode') or settings.get('mode') or DEFAULT_MODE
    if mode == 'off':
        return None
    cycle = int(_get(ev, 'cycle') or settings.get('cycle') or DEFAULT_CYCLE)
    params = _effective(ev, settings)
    ramps, n_cycles = select_ramps(segments, cycle)
    windows = _windows(ev, settings) if mode == 'semi-automatic' else {'cooling': None, 'heating': None}
    messages, results_by_ramp = [], {}
    if not ramps:
        messages.append(f'cycle {cycle} not found (the file has {n_cycles} cycles)')
    for name in ('cooling', 'heating'):
        if name not in ramps:
            continue
        if mode == 'semi-automatic' and not windows[name]:
            messages.append(f'{name}: no window given, not evaluated')
            continue
        T, q, t = ramps[name]
        res = E.evaluate_ramp(T, q, t, name == 'cooling', exo_up, windows=windows[name], **params)
        results_by_ramp[name] = res
        messages += [f'{name}: {m}' for m in res.messages]
    return Evaluation(mode, cycle, params, windows, results_by_ramp, messages)


def result_values(results_by_ramp, mode, cycle, messages):
    """Ms/Mf/As/Af, numbered peaks, peak temperatures, enthalpies (°C, J/g, rounded)."""
    values = {}
    for name, (a, b) in (('cooling', ('Ms', 'Mf')), ('heating', ('As', 'Af'))):
        res = results_by_ramp.get(name)
        if res is None or not res.peaks:
            continue
        values[a], values[b] = _r(res.peaks[0].start.temperature), _r(res.peaks[-1].end.temperature)
        for pk in res.peaks[:MAX_NUMBERED]:
            values[f'{a}{pk.index}'], values[f'{b}{pk.index}'] = _r(pk.start.temperature), _r(pk.end.temperature)
        if len(res.peaks) > MAX_NUMBERED:
            messages.append(f'{name}: {len(res.peaks)} peaks, only the first {MAX_NUMBERED} have numbered fields')
        main = max(res.peaks, key=lambda pk: pk.height)
        values[f'peak_temperature_{name}'] = _r(main.peak_temperature)
        values[f'enthalpy_{name}'] = _r(np.nansum([pk.enthalpy for pk in res.peaks]))
    if values:
        values['evaluation_method'] = (f'tangent method ({mode}, cycle {cycle}): inflection tangent x baseline; '
                                       'NOMAD plugin nomad-dsc-trios')
    return values


def exo_up_of(settings_section):
    return not str(_get(settings_section, 'exotherm_direction') or 'Up').lower().startswith('down')


def evaluate_entry(entry, archive, logger):
    from nomad.datamodel.metainfo.plot import PlotlyFigure

    from nomad_dsc_trios.schema_packages.dsc import (  # noqa: PLC0415 (circular import)
        DSC_PEAK_FIELDS,
        DSC_Evaluation,
        DSC_Peak,
        DSC_Results,
        DSC_Window,
    )

    settings, settings_path = find_settings(archive)
    ev = entry.evaluation
    if ev is not None and ev.use_folder_settings:  # button: back to the folder settings
        for k in ('mode', 'cycle', *PARAMS):
            setattr(ev, k, None)
        ev.windows, ev.windows_from_automatic, ev.use_folder_settings = [], None, False
    if ev is not None and ev.edit_automatic_windows:  # button: correct the automatic windows by hand
        ev.edit_automatic_windows = False
        if not ev.windows:  # no automatic windows yet: find them first
            auto = evaluate(entry.measurement.segments if entry.measurement else [],
                            exo_up_of(entry.instrument_settings), ev, settings, mode='automatic')
            ev.windows = [DSC_Window(ramp=name, T1=_r(pk.window[0]), T2=_r(pk.window[1]))
                          for name, res in (auto.results_by_ramp.items() if auto else []) for pk in res.peaks]
        ev.mode, ev.windows_from_automatic = 'semi-automatic', False
    if ev is not None and ev.apply_to_folder:  # button: evaluate all curves sharing these settings
        ev.apply_to_folder = False
        folder = os.path.dirname(settings_path) if settings_path else None
        n = reprocess_folder(archive, logger, folder)
        logger.info('DSC entries of the folder sent to processing', n=n, folder=folder)
    mode = _get(ev, 'mode') or settings.get('mode') or DEFAULT_MODE
    if mode == 'off':
        if ev is not None:
            ev.settings_file = settings_path
        return
    if entry.measurement is None or not entry.measurement.segments:
        logger.warning('tangent-method evaluation: no measurement data')
        return
    if ev is None:
        ev = entry.evaluation = DSC_Evaluation()
    ev.settings_file = settings_path
    exo_up = exo_up_of(entry.instrument_settings)
    result = evaluate(entry.measurement.segments, exo_up, ev, settings)
    ev.peaks = [DSC_Peak(
        label=f'{name} peak {pk.index}', ramp=name, number=pk.index, start=_r(pk.start.temperature),
        end=_r(pk.end.temperature), peak_temperature=_r(pk.peak_temperature), enthalpy=_r(pk.enthalpy),
        height=float(pk.height), inflection_start=_r(pk.start.inflection), inflection_end=_r(pk.end.inflection),
        T1=_r(pk.window[0]), T2=_r(pk.window[1]), flags='; '.join(pk.flags) or None)
        for name, res in result.results_by_ramp.items() for pk in res.peaks]
    ev.messages = '\n'.join(result.messages) or None
    ev.parameters_used = json.dumps(result.used)
    if result.mode == 'automatic' and (not ev.windows or ev.windows_from_automatic):
        ev.windows = [DSC_Window(ramp=name, T1=_r(pk.window[0]), T2=_r(pk.window[1]))
                      for name, res in result.results_by_ramp.items() for pk in res.peaks]
        ev.windows_from_automatic = True
    elif result.mode == 'semi-automatic':
        ev.windows_from_automatic = False

    if result.values and entry.transformation_results is None:
        entry.transformation_results = DSC_Results()
    if entry.transformation_results is not None:
        # numbered peaks no longer found are cleared, only for the ramps evaluated now
        prefixes = tuple(p for name, p in (('cooling', ('Ms', 'Mf')), ('heating', ('As', 'Af')))
                         if name in result.results_by_ramp for p in p)
        clear = [f for f in DSC_PEAK_FIELDS if f[:2] in prefixes]
        fill(entry.transformation_results, result.values, 'evaluation', clear=clear)

    figs = [f for f in (entry.figures or []) if f.label != 'Evaluation (tangent method)']
    fig = figure(result.results_by_ramp, exo_up, result.cycle)
    if fig:
        figs.append(PlotlyFigure(label='Evaluation (tangent method)', figure=fig))
    entry.figures = figs


def figure(results_by_ramp, exo_up, cycle, max_points=1500):
    """Curves in the instrument's sign convention, baselines, inflection tangents, onset/end markers."""
    if not results_by_ramp:
        return None
    colors = {'cooling': '#1f77b4', 'heating': '#d62728'}
    data, bx, by, tx, ty, mx, my, mt = [], [], [], [], [], [], [], []
    for name, res in results_by_ramp.items():
        sign = 1.0 if (name == 'cooling') == exo_up else -1.0
        step = max(1, len(res.T) // max_points)
        data.append({'type': 'scattergl', 'mode': 'lines', 'name': f'{name} (cycle {cycle})',
                     'x': res.T[::step].tolist(), 'y': (sign * res.y[::step]).tolist(),
                     'line': {'color': colors[name], 'width': 1.5}})
        a_, b_ = ('Ms', 'Mf') if name == 'cooling' else ('As', 'Af')
        for pk in res.peaks:
            n = '' if len(res.peaks) == 1 else str(pk.index)
            for e, lab, cursor in ((pk.start, f'{a_}{n}', pk.window[0]), (pk.end, f'{b_}{n}', pk.window[1])):
                a, b = e.baseline
                xs = [cursor, e.temperature]
                bx += xs + [None]
                by += [sign * (a * x + b) for x in xs] + [None]
                T0, y0 = e.tangent
                xt = [T0 + 0.8 * (T0 - e.temperature), e.temperature]
                tx += xt + [None]
                ty += [sign * (y0 + e.slope * (x - T0)) for x in xt] + [None]
                mx.append(e.temperature)
                my.append(sign * (a * e.temperature + b))
                mt.append(f'{lab} {e.temperature:.1f} °C')
    data.append({'type': 'scatter', 'mode': 'lines', 'name': 'baseline (tangent at the cursor)', 'x': bx, 'y': by,
                 'line': {'color': '#2ca02c', 'width': 2, 'dash': 'dash'}})
    data.append({'type': 'scatter', 'mode': 'lines', 'name': 'inflection tangent', 'x': tx, 'y': ty,
                 'line': {'color': '#333333', 'width': 1.5}})
    data.append({'type': 'scatter', 'mode': 'markers+text', 'name': 'onset / end', 'x': mx, 'y': my, 'text': mt,
                 'textposition': 'top center', 'marker': {'size': 8, 'color': '#000000'}, 'showlegend': True})
    return {'data': data, 'layout': {
        'title': {'text': 'Tangent method: check the baselines and tangents'},
        'xaxis': {'title': {'text': 'Temperature (°C)'}},
        'yaxis': {'title': {'text': f"Heat flow, smoothed (W/g, exo {'up' if exo_up else 'down'})"}},
        'showlegend': True, 'legend': {'orientation': 'h', 'y': -0.2}, 'hovermode': 'closest'}}


# ------------------------------------------------------------------ schematic of the parameters
def _synthetic_cooling(rate=10.0):
    """Cooling ramp 60 -> -100 °C: start-up transient, a small peak, the main peak, a spike, noise."""
    t = np.arange(0, 160 / rate * 60, 0.1)
    T = 60 - rate / 60 * t
    rng = np.random.default_rng(1)
    q = (0.10 + 0.0002 * T + 0.05 * np.exp(-t / 15)
         + 0.004 * np.exp(-0.5 * ((T - 22) / 3) ** 2)  # small peak (6.7 % of the main one)
         + 0.06 * np.exp(-0.5 * ((T + 30) / 9) ** 2)  # main peak
         + 0.02 * np.exp(-0.5 * ((T + 75) / 0.25) ** 2)  # spike: high but tiny area
         + 3e-4 * rng.standard_normal(t.size))
    return T, q, t, rate


def schematic_figure(params):
    """Synthetic DSC cooling curve evaluated with `params`, annotated with what each parameter does."""
    p = {**E.DEFAULTS, **{k: v for k, v in params.items() if v is not None}}
    T, q, t, rate = _synthetic_cooling()
    res = E.evaluate_ramp(T, q, t, True, **p)
    skip_T = 60 - rate * (0.15 + p['skip_start'])  # ramp start + transient + skipped minutes (approx.)
    data = [
        {'type': 'scatter', 'mode': 'lines', 'name': 'measured (synthetic)', 'x': T[::4].tolist(),
         'y': q[::4].tolist(), 'line': {'color': '#bbbbbb', 'width': 1}},
        {'type': 'scatter', 'mode': 'lines', 'name': f"smoothed (window {p['sg_window']:g} K)",
         'x': res.T[::4].tolist(), 'y': res.y[::4].tolist(), 'line': {'color': '#1f77b4', 'width': 2}},
    ]
    shapes, notes = [], []

    def note(x, y, text, ax=0, ay=-40):
        notes.append({'x': x, 'y': y, 'text': text, 'showarrow': True, 'arrowhead': 2, 'ax': ax, 'ay': ay,
                      'font': {'size': 11}, 'bgcolor': 'rgba(255,255,255,0.85)'})

    shapes.append({'type': 'rect', 'x0': skip_T, 'x1': 60, 'y0': 0, 'y1': 1, 'yref': 'paper',
                   'fillcolor': 'rgba(150,150,150,0.15)', 'line': {'width': 0}})
    note((skip_T + 60) / 2, float(np.max(q)), f"skipped at the ramp start<br>(transient + {p['skip_start']:g} min)",
         ay=-30)
    if res.peaks:
        pk = max(res.peaks, key=lambda k: k.height)
        a, b = pk.start.baseline
        off = p['min_height_percent'] / 100 * pk.height  # threshold, parallel to the baseline
        data.append({'type': 'scatter', 'mode': 'lines', 'name': 'min. peak height above the baseline',
                     'x': [skip_T, -100], 'y': [a * skip_T + b + off, a * -100 + b + off],
                     'line': {'color': '#ff7f0e', 'dash': 'dot', 'width': 1.5}})
        note(-97, a * -97 + b + off, f"min. peak height:<br>{p['min_height_percent']:g} % of the largest peak<br>"
             f"and ≥ {p['noise_factor']:g} × noise", ax=-10, ay=-45)
        first = True
        for e, lab, cursor in ((pk.start, 'Ms', pk.window[0]), (pk.end, 'Mf', pk.window[1])):
            ba, bb = e.baseline
            T0, y0 = e.tangent
            data.append({'type': 'scatter', 'mode': 'lines', 'name': 'baseline (tangent at the baseline point)',
                         'showlegend': first, 'legendgroup': 'b', 'x': [cursor, e.temperature],
                         'y': [ba * cursor + bb, ba * e.temperature + bb],
                         'line': {'color': '#2ca02c', 'width': 2, 'dash': 'dash'}})
            xt = [T0 + 0.8 * (T0 - e.temperature), e.temperature]
            data.append({'type': 'scatter', 'mode': 'lines', 'name': 'tangent at the steepest point',
                         'showlegend': first, 'legendgroup': 't', 'x': xt,
                         'y': [y0 + e.slope * (x - T0) for x in xt], 'line': {'color': '#333333', 'width': 1.5}})
            data.append({'type': 'scatter', 'mode': 'markers', 'showlegend': False, 'x': [e.temperature],
                         'y': [ba * e.temperature + bb], 'marker': {'size': 9, 'color': '#000000'}})
            data.append({'type': 'scatter', 'mode': 'markers', 'showlegend': False, 'x': [cursor],
                         'y': [ba * cursor + bb], 'marker': {'size': 9, 'color': '#2ca02c', 'symbol': 'diamond'}})
            side = -1 if lab == 'Ms' else 1  # reversed x axis: +ax = towards lower temperature
            note(e.temperature, ba * e.temperature + bb, f'{lab}: steepest-point tangent × baseline',
                 ax=side * -40, ay=45)
            note(cursor, ba * cursor + bb, 'baseline point: the curvature has<br>'
                 f"dropped to {p['knee_fraction']:g} × its maximum<br>(curvature window ≤ {p['curvature_window']:g} K)",
                 ax=side * -25 if lab == 'Ms' else 10, ay=-115)
            first = False
        note(pk.peak_temperature, float(np.interp(pk.peak_temperature, res.T, res.y)),
             f'peak: {pk.enthalpy:.1f} J/g (area to the baseline)', ay=-35)
    note(22, float(np.interp(22, res.T, res.y)), 'small peak: below<br>the threshold → ignored', ax=-70, ay=-30)
    note(-75, float(np.max(q[np.abs(T + 75) < 1])), f"spike: area < {p['min_area']:g} J/g<br>→ ignored", ax=45, ay=80)
    note(-50, float(np.interp(-50, res.T, res.y)), f"Savitzky-Golay smoothing:<br>{p['sg_window']:g} K window, "
         f"order {int(p['sg_order'])}", ax=60, ay=85)
    return {'data': data, 'layout': {
        'title': {'text': 'What the parameters do (synthetic cooling curve, evaluated with these settings)'},
        'xaxis': {'title': {'text': 'Temperature (°C)'}, 'autorange': 'reversed'},
        'yaxis': {'title': {'text': 'Heat flow (W/g, exo up)'}},
        'shapes': shapes, 'annotations': notes, 'showlegend': True,
        'legend': {'orientation': 'h', 'y': -0.2}, 'height': 600}}
