"""Interactive "explorer" figure (Plotly only, no extra GUI code):

* menu "x": choose the variable on the x axis
* legend:   click entries to show/hide y variables (several at once; double-click = only this one)
* menu "y scale": raw values | normalised by max |value| (0…1, or −1…1 if negative values)
                  | min-max (0…1)

groups:    [(group name, {variable key: 1-D array}), ...]  e.g. one group per loop or step;
           groups are drawn one after the other, separated by gaps
variables: [(variable key, label), ...]                     menu / legend entries, in this order
Each variable is one line. Values are thinned to at most `max_points` per variable and
rounded; NaN becomes a gap. One x array is shared by all lines (Plotly applies a single
array to every trace), so the stored figure stays small.
"""

import math

import numpy as np


def _rounded(a, digits):
    return [None if v is None or not math.isfinite(v) else float(f'{v:.{digits}g}') for v in a]


def _scaled(a, mode):
    v = np.asarray(a, dtype=float)
    finite = v[np.isfinite(v)]
    if mode == 'raw' or finite.size == 0:
        return v
    if mode == 'max':  # 0…1, or −1…1 when there are negative values; zero stays zero
        m = np.max(np.abs(finite))
        return v / m if m > 0 else v
    lo, hi = np.min(finite), np.max(finite)  # min-max
    return (v - lo) / (hi - lo) if hi > lo else v - lo


def explorer_figure(groups, variables, x, ys, title='Explorer', max_points=3000, digits=6):
    groups = [(n, d) for n, d in groups if d]
    variables = [(k, lab) for k, lab in variables if any(d.get(k) is not None for _, d in groups)]
    keys = [k for k, _ in variables]
    ys = [y for y in ys if y in keys]
    if x not in keys or not ys or not groups:
        return None
    lengths = [len(next(iter(d.values()))) for _, d in groups]
    max_points = min(max_points, max(1000, 40000 // len(keys)))  # many channels: fewer points each
    step = max(1, int(np.ceil(sum(lengths) / max_points)))

    def column(k):  # all groups one after the other, NaN between groups (line break)
        parts = []
        for (_, d), n in zip(groups, lengths):
            a = d.get(k)
            a = np.full(n, np.nan) if a is None else np.asarray(getattr(a, 'magnitude', a), dtype=float)
            parts += [a[::step], [np.nan]]
        return np.concatenate(parts[:-1])

    cols = {k: column(k) for k in keys}
    label = dict(variables)
    scales = [('raw', 'raw values'), ('max', 'normalised: ÷ max |value| (0…1 or −1…1)'),
              ('minmax', 'normalised: min–max (0…1)')]
    y_title = {'raw': 'value (see legend)', 'max': 'normalised value', 'minmax': 'normalised value (0…1)'}
    xs = _rounded(cols[x], digits)
    traces = [{'type': 'scattergl', 'mode': 'lines', 'name': label[k], 'x': xs,
               'y': _rounded(cols[k], digits), 'visible': True if k in ys else 'legendonly'} for k in keys]

    x_menu = {
        'buttons': [{'label': lab, 'method': 'update',
                     'args': [{'x': [_rounded(cols[k], digits)]}, {'xaxis.title.text': lab}]}
                    for k, lab in variables],
        'direction': 'down', 'active': keys.index(x), 'x': 0.06, 'xanchor': 'left', 'y': 1.2, 'yanchor': 'top',
    }
    scale_menu = {
        'buttons': [{'label': lab, 'method': 'update',
                     'args': [{'y': [_rounded(_scaled(cols[k], mode), digits) for k in keys]},
                              {'yaxis.title.text': y_title[mode]}]} for mode, lab in scales],
        'direction': 'down', 'active': 0, 'x': 0.62, 'xanchor': 'left', 'y': 1.2, 'yanchor': 'top',
    }
    first_y = label[ys[0]] if len(ys) == 1 else y_title['raw']
    return {
        'data': traces,
        'layout': {
            'title': {'text': title},
            'xaxis': {'title': {'text': label[x]}}, 'yaxis': {'title': {'text': first_y}},
            'margin': {'t': 120},
            'legend': {'title': {'text': 'y (click to show/hide)'}},
            'updatemenus': [x_menu, scale_menu],
            'annotations': [
                {'text': 'x:', 'x': 0.0, 'xref': 'paper', 'y': 1.18, 'yref': 'paper', 'showarrow': False},
                {'text': 'y scale:', 'x': 0.5, 'xref': 'paper', 'y': 1.18, 'yref': 'paper', 'showarrow': False},
            ],
        },
    }
