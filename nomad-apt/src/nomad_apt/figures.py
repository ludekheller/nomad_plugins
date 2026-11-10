"""Plotly figures of an APT reconstruction, built from the dict returned by `readers.analyse`.

All figures are plain Plotly dicts (NOMAD shows them in the entry). Heatmaps use flat x / y / z
lists, as NOMAD mangles 2-D z arrays. Everything is computed from all ions except the 3-D map,
which shows a random sample.
"""

import numpy as np

from nomad_apt.explorer import explorer_figure

PALETTE = ['#1f77b4', '#d62728', '#2ca02c', '#ff7f0e', '#9467bd', '#8c564b', '#e377c2', '#17becf',
           '#bcbd22', '#7f7f7f', '#393b79', '#ad494a', '#637939', '#8c6d31', '#7b4173', '#3182bd']
MAX_SHAPES = 300
MAX_LABELS = 60
MIN_ATOMS = 30  # cells / slices with fewer atoms get no at.% value


def r6(v, digits=6):
    return [None if not np.isfinite(x) else float(f'{x:.{digits}g}') for x in np.asarray(v, float).ravel()]


def colors_of(a):
    out = {}
    for i, ion in enumerate(a['ion_order']):
        out[ion] = a['ion_color'].get(ion) or PALETTE[i % len(PALETTE)]
    return out


def element_colors(a):
    return {e: PALETTE[i % len(PALETTE)] for i, e in enumerate(a['element_order'])}


def atomic_percent(per_element):
    """(slices or cells, elements) atoms -> at.% and 2σ counting error; NaN where too few atoms."""
    per_element = np.asarray(per_element, float)
    tot = per_element.sum(axis=-1, keepdims=True)
    with np.errstate(invalid='ignore', divide='ignore'):
        p = per_element / tot
        err = 2 * np.sqrt(p * (1 - p) / tot)
    bad = np.broadcast_to(tot < MIN_ATOMS, p.shape)
    p, err = np.where(bad, np.nan, p), np.where(bad, np.nan, err)
    return 100 * p, 100 * err


# ---------------------------------------------------------------- individual figures
def mass_spectrum(a, ranges, colors):
    keep = a['counts'] > 0
    shapes = [{'type': 'rect', 'xref': 'x', 'yref': 'paper', 'x0': rg['low'], 'x1': rg['high'], 'y0': 0, 'y1': 1,
               'fillcolor': colors.get(rg['ion'], '#999999'), 'opacity': 0.25, 'line': {'width': 0},
               'layer': 'below'} for rg in ranges[:MAX_SHAPES]]
    data = [{'type': 'scattergl', 'mode': 'lines', 'name': 'counts', 'x': r6(a['mass'][keep]),
             'y': a['counts'][keep].tolist(), 'line': {'color': '#333333', 'width': 1, 'shape': 'hvh'}}]
    # peak labels: ion name at the highest bin of each range (the most intense ranges if many)
    peaks = []
    for i, rg in enumerate(ranges):
        w = (a['mass'] >= rg['low']) & (a['mass'] <= rg['high'])
        if w.any() and a['counts'][w].max() > 0:
            j = np.flatnonzero(w)[np.argmax(a['counts'][w])]
            peaks.append((int(a['counts'][j]), float(a['mass'][j]), rg['ion']))
    peaks = sorted(peaks, reverse=True)[:MAX_LABELS]
    if peaks:
        data.append({'type': 'scatter', 'mode': 'text', 'name': 'ions', 'x': r6([p[1] for p in peaks]),
                     'y': [p[0] for p in peaks], 'text': [p[2] for p in peaks], 'textposition': 'top center',
                     'textfont': {'size': 11, 'color': [colors.get(p[2], '#333333') for p in peaks]},
                     'hoverinfo': 'x+text', 'cliponaxis': False})
    title = f'Mass spectrum ({a["n_ions"]:,} ions, bin {a["bin_width"]} Da' + \
        (', ranges shaded and labelled)' if ranges else ')')
    return {'data': data, 'layout': {
        'title': {'text': title}, 'showlegend': False,
        'xaxis': {'title': {'text': 'Mass-to-charge (Da)'}},
        'yaxis': {'title': {'text': 'Counts'}, 'type': 'log'}, 'shapes': shapes,
        'updatemenus': [{'type': 'buttons', 'direction': 'left', 'x': 1, 'xanchor': 'right', 'y': 1.12,
                         'yanchor': 'top', 'showactive': True, 'active': 0,
                         'buttons': [{'label': 'log', 'method': 'relayout', 'args': [{'yaxis.type': 'log'}]},
                                     {'label': 'linear', 'method': 'relayout',
                                      'args': [{'yaxis.type': 'linear'}]}]}]}}


def composition(a, colors):
    atoms = sum(a['element_counts'].values())
    els = sorted(a['element_counts'], key=lambda e: -a['element_counts'][e])
    ions = sorted(a['ion_counts'], key=lambda i: -a['ion_counts'][i])
    tot = a['n_ranged'] or 1
    p = np.array([a['element_counts'][e] / atoms for e in els])
    err = 200 * np.sqrt(p * (1 - p) / atoms)
    return {
        'data': [{'type': 'bar', 'name': 'elements (at.%)', 'x': els, 'y': r6(100 * p, 5),
                  'error_y': {'type': 'data', 'array': r6(err, 3), 'visible': True}},
                 {'type': 'bar', 'name': 'ranged ions (%)', 'x': ions, 'xaxis': 'x2', 'yaxis': 'y2',
                  'y': [round(100 * a['ion_counts'][i] / tot, 4) for i in ions],
                  'marker': {'color': [colors[i] for i in ions]}}],
        'layout': {'title': {'text': 'Composition: elements with 2σ (left), ranged ions (right)'},
                   'showlegend': False, 'grid': {'rows': 1, 'columns': 2, 'pattern': 'independent'},
                   'xaxis': {'domain': [0, 0.45]}, 'xaxis2': {'domain': [0.55, 1], 'anchor': 'y2'},
                   'yaxis': {'title': {'text': 'at.%'}},
                   'yaxis2': {'title': {'text': '% of ranged ions'}, 'anchor': 'x2'}}}


def profile(a):
    pr = a['profile']
    at, err = atomic_percent(pr['per_element'])
    ec = element_colors(a)
    data = []
    for k, el in enumerate(a['element_order']):
        data.append({'type': 'scatter', 'mode': 'lines+markers', 'name': el, 'x': r6(pr['depth']),
                     'y': r6(at[:, k], 5), 'marker': {'size': 3, 'color': ec[el]}, 'line': {'color': ec[el]},
                     'error_y': {'type': 'data', 'array': r6(err[:, k], 3), 'visible': True, 'thickness': 0.6,
                                 'width': 0, 'color': ec[el]}})
    return {'data': data, 'layout': {
        'title': {'text': f'Composition vs depth ({pr["slice"]:g} nm slices through the whole reconstruction, 2σ)'},
        'showlegend': True, 'xaxis': {'title': {'text': 'Depth from top of the reconstruction (nm)'}},
        'yaxis': {'title': {'text': 'at.%'}}}}


def maps(a, key, label2):
    """x-y or x-depth projection; menu: all ions (counts) or per element (at.%, atoms)."""
    mp = a[key]
    G = len(mp['x'])
    xx = np.tile(mp['x'], G)          # cell (i, j): row i = axis 1, column j = x
    yy = np.repeat(mp['axis1'], G)
    options = [('all ions (counts per cell)', mp['all'].ravel().astype(float), 'ions')]
    if mp['per_element'] is not None:
        pe = mp['per_element']                       # (elements, G, G)
        at, _ = atomic_percent(np.moveaxis(pe, 0, -1))
        both = len(a['element_order']) <= 6
        for k, el in enumerate(a['element_order']):
            options.append((f'{el} (at.%)', at[..., k].ravel(), 'at.%'))
            if both:
                options.append((f'{el} (atoms per cell)', pe[k].ravel().astype(float), 'atoms'))
    first = options[1] if len(options) > 1 else options[0]
    trace = {'type': 'heatmap', 'x': r6(xx), 'y': r6(yy), 'z': r6(first[1], 4), 'colorscale': 'Viridis',
             'colorbar': {'title': {'text': first[2]}}, 'hoverongaps': False}
    buttons = [{'label': lab, 'method': 'restyle', 'args': [{'z': [r6(z, 4)], 'colorbar.title.text': unit}]}
               for lab, z, unit in options]
    depth = key == 'map_xd'
    return {'data': [trace], 'layout': {
        'title': {'text': f'2-D map x-{label2} (projection through the whole reconstruction)'},
        'height': 600, 'xaxis': {'title': {'text': 'x (nm)'}},
        'yaxis': {'title': {'text': 'Depth (nm)' if depth else 'y (nm)'}, 'scaleanchor': 'x',
                  'autorange': 'reversed' if depth else True},
        'updatemenus': [{'buttons': buttons, 'direction': 'down', 'active': options.index(first),
                         'x': 0, 'xanchor': 'left', 'y': 1.12, 'yanchor': 'top'}]}}


def spectrum_vs_depth(a):
    sd = a['spec_depth']
    c = sd['counts']
    top = max((hi for _, w in a['ion_windows'].items() for _, hi in w), default=None)
    mmax = top + 10 if top else sd['mass'][-1]  # up to the last range (+10 Da)
    i, j = np.nonzero((c > 2) & (sd['mass'][None, :] <= mmax))  # 1-2 counts per cell: noise, bloat
    return {'data': [{'type': 'heatmap', 'x': r6(sd['mass'][j]), 'y': r6(sd['depth'][i]),
                      'z': r6(np.log10(c[i, j]), 3), 'colorscale': 'Viridis',
                      'colorbar': {'title': {'text': 'log10 counts'}}, 'hoverongaps': False}],
            'layout': {'title': {'text': 'Mass spectrum vs depth (evaporation stability, background)'},
                       'height': 550, 'xaxis': {'title': {'text': 'Mass-to-charge (Da)'}},
                       'yaxis': {'title': {'text': 'Depth (nm)'}, 'autorange': 'reversed'}}}


def evaporation(a):
    pr = a['profile']
    data = [{'type': 'scatter', 'mode': 'lines', 'name': 'ions per slice', 'x': r6(pr['depth']),
             'y': pr['ions'].tolist(), 'line': {'color': '#1f77b4'}}]
    layout = {'title': {'text': f'Ions per {pr["slice"]:g} nm depth slice'}, 'showlegend': True,
              'xaxis': {'title': {'text': 'Depth (nm)'}}, 'yaxis': {'title': {'text': 'Ions per slice'}}}
    if a['ion_order']:
        with np.errstate(invalid='ignore', divide='ignore'):
            un = 100 * pr['unranged'] / pr['ions']
        data.append({'type': 'scatter', 'mode': 'lines', 'name': 'unranged (%)', 'x': r6(pr['depth']),
                     'y': r6(un, 4), 'yaxis': 'y2', 'line': {'color': '#d62728', 'dash': 'dot'}})
        layout['yaxis2'] = {'title': {'text': 'Unranged ions (%)'}, 'overlaying': 'y', 'side': 'right'}
        layout['title']['text'] += ' and unranged fraction (background)'
    return {'data': data, 'layout': layout}


def explorer(a):
    pr = a['profile']
    cols = {'depth': pr['depth'], 'ions': pr['ions'].astype(float)}
    variables = [('depth', 'Depth (nm)'), ('ions', 'Ions per slice')]
    ys = ['ions']
    if a['ion_order']:
        at, _ = atomic_percent(pr['per_element'])
        with np.errstate(invalid='ignore', divide='ignore'):
            cols['unranged'] = 100 * pr['unranged'] / pr['ions']
        variables.append(('unranged', 'Unranged (%)'))
        for k, el in enumerate(a['element_order']):
            cols[f'at_{el}'] = at[:, k]
            variables.append((f'at_{el}', f'{el} (at.%)'))
        for k, ion in enumerate(a['ion_order']):
            cols[f'n_{ion}'] = pr['per_ion'][:, k].astype(float)
            variables.append((f'n_{ion}', f'{ion} (ions per slice)'))
        ys = [f'at_{el}' for el in a['element_order']]
    return explorer_figure([('profile', cols)], variables, 'depth', ys,
                           title='Explorer: depth profile - x menu, y on/off buttons, y scale menu')


def atom_map(a, colors):
    s = a['sample']
    order = list(sorted(a['ion_counts'], key=lambda i: -a['ion_counts'][i])) + ['unranged']
    data = []
    for ion in order:
        sel = s['ion'] == ion
        if not sel.any():
            continue
        data.append({'type': 'scatter3d', 'mode': 'markers', 'name': f'{ion} ({int(sel.sum())})',
                     'x': r6(s['x'][sel]), 'y': r6(s['y'][sel]), 'z': r6(s['z'][sel]),
                     'marker': {'size': 1.5, 'color': colors.get(ion, '#bbbbbb'),
                                'opacity': 0.4 if ion == 'unranged' else 0.8},
                     'visible': 'legendonly' if ion == 'unranged' and len(order) > 1 else True})
    return {'data': data, 'layout': {
        'title': {'text': f'Atom map: random sample of {len(s["x"]):,} ions (click legend to hide)'},
        'showlegend': True, 'height': 650,
        'scene': {'aspectmode': 'data', 'xaxis': {'title': {'text': 'x (nm)'}},
                  'yaxis': {'title': {'text': 'y (nm)'}}, 'zaxis': {'title': {'text': 'z (nm)'}}}}}


def voltage(a):
    return {'data': [{'type': 'scattergl', 'mode': 'lines', 'name': 'V_dc', 'x': a['vdc_index'].tolist(),
                      'y': r6(a['vdc'])}],
            'layout': {'title': {'text': 'Standing voltage vs ion sequence'}, 'showlegend': False,
                       'xaxis': {'title': {'text': 'Ion number'}}, 'yaxis': {'title': {'text': 'V_dc (V)'}}}}


def detector(a):
    e = a['det_edges']
    c = (e[:-1] + e[1:]) / 2
    h = a['det_hist']
    yy, xx = np.meshgrid(c, c, indexing='ij')
    nz = h > 0
    return {'data': [{'type': 'heatmap', 'x': r6(xx[nz]), 'y': r6(yy[nz]), 'z': h[nz].tolist(),
                      'colorscale': 'Viridis', 'colorbar': {'title': {'text': 'hits'}}}],
            'layout': {'title': {'text': 'Detector hit map'}, 'height': 550,
                       'xaxis': {'title': {'text': 'detector x (mm)'}},
                       'yaxis': {'title': {'text': 'detector y (mm)'}, 'scaleanchor': 'x'}}}


# ---------------------------------------------------------------- all
def build_figures(a, ranges):
    """-> [(label, plotly figure dict)] in display order."""
    colors = colors_of(a)
    figs = [('Mass spectrum', mass_spectrum(a, ranges, colors))]
    if a['element_counts']:
        figs += [('Composition', composition(a, colors)), ('Composition profile (depth)', profile(a))]
    ex = explorer(a)
    if ex:
        figs.append(('Explorer: depth profile (choose x and y)', ex))
    figs += [('2-D maps x-y', maps(a, 'map_xy', 'y')), ('2-D maps x-depth', maps(a, 'map_xd', 'depth')),
             ('Mass spectrum vs depth', spectrum_vs_depth(a)), ('Evaporation vs depth', evaporation(a)),
             ('3-D atom map (sample)', atom_map(a, colors))]
    if 'vdc' in a:
        figs.append(('Voltage history', voltage(a)))
    if a.get('det_hist') is not None:
        figs.append(('Detector hit map', detector(a)))
    return figs
