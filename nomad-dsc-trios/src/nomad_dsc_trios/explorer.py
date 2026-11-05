"""Interactive "explorer" figure (Plotly only, no extra GUI code):

* menu "x" (dropdown):       choose the variable on the x axis
* y buttons (3 columns):     one on/off button per variable in the colour of its line,
                             filled = shown - switch on any combination of y variables
Everything sits below the plot, so the plot keeps the full width.
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

    # layout (px): plot area, then below it x tick labels + axis title, menu row, y buttons
    plot_h, top, axis_space = 400, 30, 60
    menu_row = axis_space + 15          # offset of the x / y-scale dropdowns below the plot
    y_label = menu_row + 45             # "y (click to switch on/off):"
    y_first = y_label + 22              # first row of y buttons
    rows = int(np.ceil(len(keys) / BUTTON_COLUMNS))
    bottom = y_first + rows * BUTTON_ROW + 10
    below = lambda px: -px / plot_h  # noqa: E731  (paper coordinates below the plot area)

    menus = [
        {  # x variable
            'buttons': [{'label': lab, 'method': 'update',
                         'args': [{'x': [_rounded(cols[k], digits)]}, {'xaxis.title.text': lab}]}
                        for k, lab in variables],
            'direction': 'down', 'active': keys.index(x),
            'x': 0.04, 'xanchor': 'left', 'y': below(menu_row), 'yanchor': 'top',
        },
        {  # y scale
            'buttons': [{'label': lab, 'method': 'update',
                         'args': [{'y': [_rounded(_scaled(cols[k], mode), digits) for k in keys]},
                                  {'yaxis.title.text': y_title[mode]}]} for mode, lab in scales],
            'direction': 'down', 'active': 0,
            'x': 0.6, 'xanchor': 'left', 'y': below(menu_row), 'yanchor': 'top',
        },
    ]
    for i, k in enumerate(keys):  # one on/off button per y variable: filled = on, white = off
        row, col = divmod(i, BUTTON_COLUMNS)
        m = 2 + i  # index of this menu in layout.updatemenus
        on = {f'updatemenus[{m}].bgcolor': color[k], f'updatemenus[{m}].font.color': '#ffffff'}
        off = {f'updatemenus[{m}].bgcolor': '#ffffff', f'updatemenus[{m}].font.color': color[k]}
        menus.append({
            'type': 'buttons', 'showactive': False, 'active': 0 if k in ys else -1,
            'buttons': [{'label': label[k], 'method': 'update',
                         'args': [{'visible': True}, on, [i]], 'args2': [{'visible': False}, off, [i]]}],
            'bgcolor': color[k] if k in ys else '#ffffff', 'bordercolor': color[k],
            'font': {'color': '#ffffff' if k in ys else color[k], 'size': 11},
            'x': col / BUTTON_COLUMNS, 'xanchor': 'left', 'y': below(y_first + row * BUTTON_ROW), 'yanchor': 'top',
            'pad': {'t': 0, 'b': 0, 'l': 0, 'r': 0},
        })

    return {
        'data': traces,
        'layout': {
            'height': top + plot_h + bottom,
            'xaxis': {'title': {'text': label[x]}},
            'yaxis': {'title': {'text': label[ys[0]] if len(ys) == 1 else y_title['raw']}},
            'margin': {'t': top, 'b': bottom, 'r': 30},
            'showlegend': False,  # the y buttons, coloured like their lines, are the legend
            'updatemenus': menus,
            'annotations': [
                {'text': 'x:', 'x': 0.0, 'xref': 'paper', 'xanchor': 'left', 'y': below(menu_row + 5),
                 'yref': 'paper', 'yanchor': 'top', 'showarrow': False},
                {'text': 'y scale:', 'x': 0.5, 'xref': 'paper', 'xanchor': 'left', 'y': below(menu_row + 5),
                 'yref': 'paper', 'yanchor': 'top', 'showarrow': False},
                {'text': 'y (click to switch on/off):', 'x': 0.0, 'xref': 'paper', 'xanchor': 'left',
                 'y': below(y_label), 'yref': 'paper', 'yanchor': 'top', 'showarrow': False},
            ],
        },
    }
