"""Interactive "explorer" figure (Plotly only, no extra GUI code):

* menu "x" (dropdown):       choose the variable on the x axis
* y buttons (below the plot, 3 columns): one on/off button per variable, in the colour of
                             its line - switch on any combination of y variables
* menu "y scale" (dropdown): raw values | normalised by max |value| (0…1, or −1…1 if
                             negative values) | min-max (0…1) - to compare variables of
                             different size on one axis

groups:    [(group name, {variable key: 1-D array}), ...]  e.g. one group per loop or step;
           groups are drawn one after the other, separated by gaps
variables: [(variable key, label), ...]                     menu entries, in this order
Each variable is one line. Values are thinned and rounded; NaN becomes a gap. One x array
is shared by all lines (Plotly applies a single array to every trace), so the stored
figure stays small.
"""

import math

import numpy as np

COLORS = ['#1f77b4', '#d62728', '#2ca02c', '#ff7f0e', '#9467bd', '#8c564b', '#e377c2', '#17becf',
          '#bcbd22', '#7f7f7f', '#393b79', '#ad494a', '#637939', '#8c6d31', '#7b4173', '#3182bd']
BUTTON_ROW = 28  # px per row of y buttons
BUTTON_COLUMNS = 3


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
    color = {k: COLORS[i % len(COLORS)] for i, k in enumerate(keys)}
    scales = [('raw', 'raw values'), ('max', 'normalised: ÷ max |value| (0…1 or −1…1)'),
              ('minmax', 'normalised: min–max (0…1)')]
    y_title = {'raw': 'value', 'max': 'normalised value', 'minmax': 'normalised value (0…1)'}
    xs = _rounded(cols[x], digits)
    traces = [{'type': 'scattergl', 'mode': 'lines', 'name': label[k], 'x': xs, 'y': _rounded(cols[k], digits),
               'line': {'color': color[k]}, 'visible': k in ys} for k in keys]

    menus = [
        {  # x variable
            'buttons': [{'label': lab, 'method': 'update',
                         'args': [{'x': [_rounded(cols[k], digits)]}, {'xaxis.title.text': lab}]}
                        for k, lab in variables],
            'direction': 'down', 'active': keys.index(x), 'x': 0.03, 'xanchor': 'left', 'y': 1.2, 'yanchor': 'top',
        },
        {  # y scale
            'buttons': [{'label': lab, 'method': 'update',
                         'args': [{'y': [_rounded(_scaled(cols[k], mode), digits) for k in keys]},
                                  {'yaxis.title.text': y_title[mode]}]} for mode, lab in scales],
            'direction': 'down', 'active': 0, 'x': 0.55, 'xanchor': 'left', 'y': 1.2, 'yanchor': 'top',
        },
    ]
    rows = int(np.ceil(len(keys) / BUTTON_COLUMNS))
    plot_h = 400  # height of the plotting area in px
    top, below_axis = 120, 95  # px: menus above the plot; x tick labels + axis title below it
    bottom = below_axis + 25 + rows * BUTTON_ROW
    height = top + plot_h + bottom
    for i, k in enumerate(keys):  # one on/off button per y variable (toggle: args / args2)
        row, col = divmod(i, BUTTON_COLUMNS)
        menus.append({
            'type': 'buttons', 'showactive': True, 'active': 0 if k in ys else -1,
            'buttons': [{'label': label[k], 'method': 'restyle',
                         'args': [{'visible': True}, [i]], 'args2': [{'visible': False}, [i]]}],
            'font': {'color': color[k], 'size': 11},
            'x': col / BUTTON_COLUMNS, 'xanchor': 'left',
            'y': -(below_axis + 25 + row * BUTTON_ROW) / plot_h, 'yanchor': 'top',
            'pad': {'t': 0, 'b': 0, 'l': 0, 'r': 0},
        })

    return {
        'data': traces,
        'layout': {
            'title': {'text': title},
            'height': height,
            'xaxis': {'title': {'text': label[x]}},
            'yaxis': {'title': {'text': label[ys[0]] if len(ys) == 1 else y_title['raw']}},
            'margin': {'t': top, 'b': bottom, 'r': 30},
            'showlegend': False,  # the y buttons, coloured like their lines, are the legend
            'updatemenus': menus,
            'annotations': [
                {'text': 'x:', 'x': 0.0, 'xref': 'paper', 'y': 1.18, 'yref': 'paper', 'showarrow': False},
                {'text': 'y scale:', 'x': 0.47, 'xref': 'paper', 'y': 1.18, 'yref': 'paper', 'showarrow': False},
                {'text': 'y (click to switch on/off):', 'x': 0.0, 'xref': 'paper', 'xanchor': 'left',
                 'y': -(below_axis + 4) / plot_h, 'yref': 'paper', 'yanchor': 'top', 'showarrow': False},
            ],
        },
    }
