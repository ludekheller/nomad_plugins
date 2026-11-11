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


def find_settings(archive):
    """(settings dict, upload-relative path) of the nearest folder settings, or ({}, None)."""
    mainfile = getattr(archive.metadata, 'mainfile', None) if archive.metadata is not None else None
    root = _raw_root(archive.m_context) if archive.m_context is not None else None
    if not mainfile or not root:
        return {}, None
    parts = os.path.dirname(mainfile).split('/') if os.path.dirname(mainfile) else []
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
            except Exception:
                continue
            if str(data.get('m_def', '')).endswith('.DSC_EvaluationSettings'):
                return data, (os.path.join(rel, n) if rel else n)
    return {}, None


# ------------------------------------------------------------------ evaluation
def select_ramps(segments, cycle):
    """{'cooling': (T, q, t), 'heating': (T, q, t)} of the given cycle (1-based)."""
    parts, c = {'cooling': [], 'heating': []}, 0
    for s in segments:
        kind = s.segment_type or ''
        if kind == 'ramp_cooling':
            c += 1
        if c != cycle or not kind.startswith('ramp_') or s.temperature is None:
            continue
        parts['cooling' if kind == 'ramp_cooling' else 'heating'].append(s)
    out = {}
    for name, segs in parts.items():
        if segs:
            out[name] = tuple(np.concatenate([np.asarray(getattr(getattr(s, q), 'magnitude', getattr(s, q)),
                                                         dtype=float) for s in segs])
                              for q in ('temperature', 'heat_flow_normalized', 'time'))
    return out, c


def _effective(ev, settings):
    p = {}
    for k in PARAMS:
        v = _plain(getattr(ev, k)) if ev is not None else None
        if v is None:
            v = settings.get(k)
        if v is not None:
            p[k] = v
    return p


def _windows(ev, settings):
    out = {'cooling': [], 'heating': []}
    src = [(w.ramp, _plain(w.T1), _plain(w.T2)) for w in (ev.windows or [])] if ev is not None else []
    if not src:
        src = [(w.get('ramp'), w.get('T1'), w.get('T2')) for w in settings.get('windows') or []]
    for ramp, a, b in src:
        if ramp in out and a is not None and b is not None:
            out[ramp].append((a, b))
    return out


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
    mode = (ev.mode if ev is not None else None) or settings.get('mode') or 'off'
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
    cycle = (ev.cycle or settings.get('cycle') or 1)
    params = _effective(ev, settings)
    ramps, n_cycles = select_ramps(entry.measurement.segments, int(cycle))
    st = entry.instrument_settings
    exo_up = not str((st.exotherm_direction if st is not None else None) or 'Up').lower().startswith('down')
    windows = _windows(ev, settings) if mode == 'semi-automatic' else {'cooling': None, 'heating': None}
    messages, results_by_ramp, peaks = [], {}, []
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
        for pk in res.peaks:
            peaks.append(DSC_Peak(
                label=f'{name} peak {pk.index}', ramp=name, number=pk.index, start=pk.start.temperature,
                end=pk.end.temperature, peak_temperature=pk.peak_temperature, enthalpy=pk.enthalpy,
                height=pk.height, inflection_start=pk.start.inflection, inflection_end=pk.end.inflection,
                T1=pk.window[0], T2=pk.window[1], flags='; '.join(pk.flags) or None))
    ev.peaks = peaks
    ev.messages = '\n'.join(messages) or None
    ev.parameters_used = json.dumps({'mode': mode, 'cycle': cycle, **{**E.DEFAULTS, **params},
                                     'windows': windows if mode == 'semi-automatic' else None})
    if mode == 'automatic' and (not ev.windows or ev.windows_from_automatic):
        ev.windows = [DSC_Window(ramp=name, T1=pk.window[0], T2=pk.window[1])
                      for name, res in results_by_ramp.items() for pk in res.peaks]
        ev.windows_from_automatic = True
    elif mode == 'semi-automatic':
        ev.windows_from_automatic = False

    # results
    values = {}
    for name, (a, b) in (('cooling', ('Ms', 'Mf')), ('heating', ('As', 'Af'))):
        res = results_by_ramp.get(name)
        if res is None or not res.peaks:
            continue
        values[a], values[b] = res.peaks[0].start.temperature, res.peaks[-1].end.temperature
        for pk in res.peaks[:MAX_NUMBERED]:
            values[f'{a}{pk.index}'], values[f'{b}{pk.index}'] = pk.start.temperature, pk.end.temperature
        if len(res.peaks) > MAX_NUMBERED:
            messages.append(f'{name}: {len(res.peaks)} peaks, only the first {MAX_NUMBERED} have numbered fields')
        main = max(res.peaks, key=lambda pk: pk.height)
        values[f'peak_temperature_{name}'] = main.peak_temperature
        values[f'enthalpy_{name}'] = float(np.nansum([pk.enthalpy for pk in res.peaks]))
    if values:
        values['evaluation_method'] = (f'tangent method ({mode}, cycle {cycle}): inflection tangent x baseline; '
                                       'NOMAD plugin nomad-dsc-trios')
        if entry.transformation_results is None:
            entry.transformation_results = DSC_Results()
    if entry.transformation_results is not None:
        # numbered peaks no longer found are cleared, only for the ramps evaluated now
        prefixes = tuple(p for name, p in (('cooling', ('Ms', 'Mf')), ('heating', ('As', 'Af')))
                         if name in results_by_ramp for p in p)
        clear = [f for f in DSC_PEAK_FIELDS if f[:2] in prefixes]
        fill(entry.transformation_results, values, 'evaluation', clear=clear)
    ev.messages = '\n'.join(messages) or None

    figs = [f for f in (entry.figures or []) if f.label != 'Evaluation (tangent method)']
    fig = figure(results_by_ramp, exo_up, cycle)
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
