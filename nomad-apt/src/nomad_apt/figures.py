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


def _on_text(color):
    """Text colour on a filled button: dark on light colours (e.g. yellow), white otherwise."""
    try:
        r, g, b = (int(color.lstrip('#')[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return '#ffffff'
    return '#222222' if 0.299 * r + 0.587 * g + 0.114 * b > 0.6 else '#ffffff'


def _off_text(color):
    """Text colour on an empty (white) button: the colour itself unless too light to read."""
    return '#8a7a00' if _on_text(color) == '#222222' else color


def toggle_buttons(items, y_of_row, columns=6, menu0=0):
    """On/off buttons in rows above a plot. items: [(label, colour, trace indices, on)].
    Filled button = shown. The first slot holds 'all on' / 'all off'. Returns updatemenus."""
    def style(i, on):
        m = menu0 + 1 + i
        c = items[i][1]
        return {f'updatemenus[{m}].bgcolor': c if on else '#ffffff',
                f'updatemenus[{m}].font.color': _on_text(c) if on else _off_text(c)}

    every = sorted({t for it in items for t in it[2]})

    def all_(on):
        lay = {}
        for i in range(len(items)):
            lay.update(style(i, on))
        return [{'visible': on}, lay, every]

    pad = {'t': 0, 'b': 0, 'l': 0, 'r': 0}
    menus = [{'type': 'buttons', 'direction': 'left', 'showactive': False, 'x': 0, 'xanchor': 'left',
              'y': y_of_row(0), 'yanchor': 'top', 'pad': pad, 'font': {'size': 11},
              'buttons': [{'label': 'all on', 'method': 'update', 'args': all_(True)},
                          {'label': 'all off', 'method': 'update', 'args': all_(False)}]}]
    for i, (label, color, traces, on) in enumerate(items):
        r, c = divmod(i + 1, columns)
        menus.append({'type': 'buttons', 'showactive': False, 'active': 0 if on else -1,
                      'buttons': [{'label': label, 'method': 'update',
                                   'args': [{'visible': True}, style(i, True), traces],
                                   'args2': [{'visible': False}, style(i, False), traces]}],
                      'bgcolor': color if on else '#ffffff', 'bordercolor': color,
                      'font': {'color': _on_text(color) if on else _off_text(color), 'size': 11},
                      'x': c / columns, 'xanchor': 'left', 'y': y_of_row(r), 'yanchor': 'top', 'pad': pad})
    return menus


def _sample_traces(a, colors):
    """3-D traces of the per-ion sample: [(ion, label, trace dict, on)]."""
    s = a['sample']
    order = list(sorted(a['ion_counts'], key=lambda i: -a['ion_counts'][i])) + ['unranged']
    out = []
    for ion in order:
        sel = s['ion'] == ion
        if not sel.any():
            continue
        k, tot = int(sel.sum()), s.get('total', {}).get(ion, int(sel.sum()))
        label = f'{ion} (all {k:,})' if k >= tot else f'{ion} ({k:,} of {tot:,})'
        on = ion != 'unranged' or len(order) == 1
        out.append((ion, label, {'type': 'scatter3d', 'mode': 'markers', 'name': label,
                                 'x': r6(s['x'][sel], 5), 'y': r6(s['y'][sel], 5), 'z': r6(s['z'][sel], 5),
                                 'marker': {'size': 1.5, 'color': colors.get(ion, '#999999'),
                                            'opacity': 0.4 if ion == 'unranged' else 0.8},
                                 'visible': on, 'hoverinfo': 'name'}, on))
    return out


def atom_map(a, colors, columns=6, row=28):
    """3-D map of a sample per ion (minor ions complete); on/off buttons above the plot."""
    tr = _sample_traces(a, colors)
    rows = int(np.ceil((len(tr) + 1) / columns))
    plot_h, top = 640, 30 + rows * row
    items = [(lab, colors.get(ion, '#999999'), [i], on) for i, (ion, lab, _, on) in enumerate(tr)]
    menus = toggle_buttons(items, lambda r: 1 + (top - 6 - r * row) / plot_h, columns)
    return {'data': [t for _, _, t, _ in tr], 'layout': {
        'height': plot_h + top + 10, 'margin': {'t': top, 'b': 10, 'l': 10, 'r': 10}, 'showlegend': False,
        'updatemenus': menus,
        'scene': {'aspectmode': 'data', 'xaxis': {'title': {'text': 'x (nm)'}},
                  'yaxis': {'title': {'text': 'y (nm)'}}, 'zaxis': {'title': {'text': 'z (nm)'}}}}}


def cross_sections(a, colors, columns=6, row=28):
    """3-D map with two section planes; x-z section with z profile (left), x-y slice with x and
    y profiles (below the 3-D map). Two sliders move the planes; ion buttons switch species."""
    cs = a['sections']
    ranged = bool(a['ion_order'])
    tr = [t for t in _sample_traces(a, colors)]
    ions = [ion for ion, *_ in tr if ion != 'unranged'] if ranged else ['unranged']
    els = a['element_order'] if ranged else []
    R2E, steps = a['R2E'], cs['steps']
    rng_ion = np.array([r for r in a.get('range_ions', [])] + ['unranged'], dtype=object)
    (x0, x1), (y0, y1), (z0, z1) = a['extent']['x'], a['extent']['y'], a['extent']['z']

    data = []
    T3D = list(range(len(tr)))
    data += [t for _, _, t, _ in tr]

    def pts(key, s, ion):
        p = cs[key]
        sel = (p[:, 0] == s) & (rng_ion[p[:, 1].astype(int)] == ion) if ranged else (p[:, 0] == s)
        return r6(p[sel, 2], 4), r6(p[sel, 3], 4)

    s0 = steps // 2
    Txz, Txy = [], []
    for ion in ions:
        x, d = pts('points_xz', s0, ion)
        Txz.append(len(data))
        data.append({'type': 'scattergl', 'mode': 'markers', 'name': ion, 'x': x, 'y': d, 'xaxis': 'x', 'yaxis': 'y',
                     'marker': {'size': 3, 'color': colors.get(ion, '#999999'), 'opacity': 0.7}, 'hoverinfo': 'name'})
    for ion in ions:
        x, y = pts('points_xy', s0, ion)
        Txy.append(len(data))
        data.append({'type': 'scattergl', 'mode': 'markers', 'name': ion, 'x': x, 'y': y, 'xaxis': 'x4',
                     'yaxis': 'y4', 'marker': {'size': 3, 'color': colors.get(ion, '#999999'), 'opacity': 0.7},
                     'hoverinfo': 'name'})

    # profiles: at.% per element (with ranges) or ions per bin (without)
    def prof(P, s):  # P: (steps, labels, bins) -> (series, bins)
        if not ranged:
            return P[s].sum(axis=0, keepdims=True).astype(float)
        at, _ = atomic_percent((R2E.T @ P[s]).T)  # (bins, elements)
        return at.T

    series = els if ranged else ['ions']
    ecol = element_colors(a) if ranged else {'ions': '#333333'}
    unit = 'at.%' if ranged else 'ions per nm'
    Pz, Px, Py = [], [], []
    for k, e in enumerate(series):
        col = colors.get(e, ecol[e])
        Pz.append(len(data))
        data.append({'type': 'scatter', 'mode': 'lines', 'name': e, 'x': r6(prof(cs['P_d'], s0)[k], 4),
                     'y': r6(cs['bd'], 4), 'xaxis': 'x2', 'yaxis': 'y2', 'line': {'color': col, 'width': 1.5}})
        Px.append(len(data))
        data.append({'type': 'scatter', 'mode': 'lines', 'name': e, 'x': r6(cs['bx'], 4),
                     'y': r6(prof(cs['P_x'], s0)[k], 4), 'xaxis': 'x3', 'yaxis': 'y3',
                     'line': {'color': col, 'width': 1.5}})
        Py.append(len(data))
        data.append({'type': 'scatter', 'mode': 'lines', 'name': e, 'x': r6(prof(cs['P_y'], s0)[k], 4),
                     'y': r6(cs['by'], 4), 'xaxis': 'x5', 'yaxis': 'y5', 'line': {'color': col, 'width': 1.5}})

    # section planes in 3-D and position markers in the 2-D panels
    def zplane(s):
        zc = float(z1 - cs['depths'][s])
        return {'x': [x0, x1, x1, x0], 'y': [y0, y0, y1, y1], 'z': [zc] * 4}

    def yplane(s):
        yc = float(cs['ys'][s])
        return {'x': [x0, x1, x1, x0], 'y': [yc] * 4, 'z': [z0, z0, z1, z1]}

    mesh = {'type': 'mesh3d', 'i': [0, 0], 'j': [1, 2], 'k': [2, 3], 'opacity': 0.25, 'hoverinfo': 'skip',
            'showscale': False}
    PZ = len(data)
    data.append({**mesh, **zplane(s0), 'color': '#e377c2', 'name': 'x-y slice'})
    PY = len(data)
    data.append({**mesh, **yplane(s0), 'color': '#17becf', 'name': 'x-z section'})
    line = {'type': 'scatter', 'mode': 'lines', 'hoverinfo': 'skip', 'showlegend': False}
    LXZ = len(data)  # depth of the x-y slice, drawn in the x-z section
    data.append({**line, 'x': [x0, x1], 'y': [float(cs['depths'][s0])] * 2, 'xaxis': 'x', 'yaxis': 'y',
                 'line': {'color': '#e377c2', 'dash': 'dash'}})
    LZP = len(data)  # same, in the z profile
    data.append({**line, 'x': [0, 100 if ranged else None], 'y': [float(cs['depths'][s0])] * 2, 'xaxis': 'x2',
                 'yaxis': 'y2', 'line': {'color': '#e377c2', 'dash': 'dash'}})
    LXY = len(data)  # y of the x-z section, drawn in the x-y slice
    data.append({**line, 'x': [x0, x1], 'y': [float(cs['ys'][s0])] * 2, 'xaxis': 'x4', 'yaxis': 'y4',
                 'line': {'color': '#17becf', 'dash': 'dash'}})
    if not ranged:
        data[LZP]['x'] = [0, float(prof(cs['P_d'], s0).max() or 1)]

    def step_xy(s):  # slider 1: depth of the x-y slice
        upd = {'x': [], 'y': [], 'z': []}
        idx = []
        for i, ion in zip(Txy, ions):
            x, y = pts('points_xy', s, ion)
            upd['x'].append(x), upd['y'].append(y), upd['z'].append(None), idx.append(i)
        p_x, p_y = prof(cs['P_x'], s), prof(cs['P_y'], s)
        for k in range(len(series)):
            upd['x'].append(r6(cs['bx'], 4)), upd['y'].append(r6(p_x[k], 4)), upd['z'].append(None)
            upd['x'].append(r6(p_y[k], 4)), upd['y'].append(r6(cs['by'], 4)), upd['z'].append(None)
            idx += [Px[k], Py[k]]
        zp = zplane(s)
        upd['x'].append(zp['x']), upd['y'].append(zp['y']), upd['z'].append(zp['z'])
        d = float(cs['depths'][s])
        upd['x'] += [[x0, x1], data[LZP]['x']]
        upd['y'] += [[d, d], [d, d]]
        upd['z'] += [None, None]
        idx += [PZ, LXZ, LZP]
        return [upd, idx]

    def step_xz(s):  # slider 2: y of the x-z section
        upd = {'x': [], 'y': [], 'z': []}
        idx = []
        for i, ion in zip(Txz, ions):
            x, d = pts('points_xz', s, ion)
            upd['x'].append(x), upd['y'].append(d), upd['z'].append(None), idx.append(i)
        p_d = prof(cs['P_d'], s)
        for k in range(len(series)):
            upd['x'].append(r6(p_d[k], 4)), upd['y'].append(r6(cs['bd'], 4)), upd['z'].append(None)
            idx.append(Pz[k])
        yp = yplane(s)
        upd['x'].append(yp['x']), upd['y'].append(yp['y']), upd['z'].append(yp['z'])
        yc = float(cs['ys'][s])
        upd['x'].append([x0, x1]), upd['y'].append([yc, yc]), upd['z'].append(None)
        idx += [PY, LXY]
        return [upd, idx]

    # layout (px): buttons, sliders on top; panels below
    items = []
    for i, (ion, lab, _, on) in enumerate(tr):
        traces = [T3D[i]]
        if ion in ions:
            j = ions.index(ion)
            traces += [Txz[j], Txy[j]]
        if ranged and ion in series:
            k = series.index(ion)
            traces += [Pz[k], Px[k], Py[k]]
        items.append((lab, colors.get(ion, '#999999'), traces, on))
    rows = int(np.ceil((len(items) + 1) / columns))
    top = 20 + rows * row + 95
    H = 1150
    ph = H - top - 45
    y_row = lambda r: 1 + (top - 8 - r * row) / ph  # noqa: E731
    y_slider = 1 + (top - 14 - rows * row) / ph
    menus = toggle_buttons(items, y_row, columns)

    def slider(label, values, fmt, step_fn, x, color):
        return {'active': s0, 'x': x, 'len': 0.47, 'y': y_slider, 'yanchor': 'top', 'pad': {'t': 0, 'b': 0},
                'currentvalue': {'prefix': label, 'font': {'size': 12, 'color': color}},
                'steps': [{'label': fmt(v), 'method': 'restyle', 'args': step_fn(s)} for s, v in enumerate(values)]}

    sliders = [slider(f'x-y slice ({cs["thickness_xy"]:g} nm thick) at depth ', cs['depths'], lambda v: f'{v:.1f} nm',
                      step_xy, 0.0, '#e377c2'),
               slider(f'x-z section ({cs["thickness_xz"]:g} nm thick) at y = ', cs['ys'], lambda v: f'{v:.1f} nm',
                      step_xz, 0.53, '#17becf')]
    ax = lambda **kw: {'showgrid': True, 'zeroline': False, **kw}  # noqa: E731
    layout = {
        'height': H, 'margin': {'t': top, 'b': 45, 'l': 55, 'r': 15}, 'showlegend': False,
        'updatemenus': menus, 'sliders': sliders,
        'xaxis': ax(domain=[0, 0.25], title={'text': 'x (nm)'}),
        'yaxis': ax(domain=[0, 1], title={'text': 'Depth (nm)'}, autorange='reversed'),
        'xaxis2': ax(domain=[0.27, 0.37], title={'text': unit}, anchor='y2'),
        'yaxis2': ax(domain=[0, 1], matches='y', showticklabels=False, anchor='x2'),
        'xaxis3': ax(domain=[0.43, 0.82], matches='x4', showticklabels=False, anchor='y3'),
        'yaxis3': ax(domain=[0.36, 0.46], title={'text': unit}, anchor='x3'),
        'xaxis4': ax(domain=[0.43, 0.82], title={'text': 'x (nm)'}, anchor='y4'),
        'yaxis4': ax(domain=[0, 0.33], title={'text': 'y (nm)'}, anchor='x4'),
        'xaxis5': ax(domain=[0.84, 1], title={'text': unit}, anchor='y5'),
        'yaxis5': ax(domain=[0, 0.33], matches='y4', showticklabels=False, anchor='x5'),
        'scene': {'domain': {'x': [0.40, 1], 'y': [0.49, 1]}, 'aspectmode': 'data',
                  'xaxis': {'title': {'text': 'x (nm)'}}, 'yaxis': {'title': {'text': 'y (nm)'}},
                  'zaxis': {'title': {'text': 'z (nm)'}}},
        'annotations': [
            {'text': 'x-z section', 'x': 0, 'y': 1, 'xref': 'paper', 'yref': 'paper', 'xanchor': 'left',
             'yanchor': 'bottom', 'showarrow': False, 'font': {'color': '#17becf'}},
            {'text': 'profile along depth', 'x': 0.27, 'y': 1, 'xref': 'paper', 'yref': 'paper', 'xanchor': 'left',
             'yanchor': 'bottom', 'showarrow': False, 'font': {'size': 10}},
            {'text': 'x-y slice', 'x': 0.43, 'y': 0.33, 'xref': 'paper', 'yref': 'paper', 'xanchor': 'left',
             'yanchor': 'bottom', 'showarrow': False, 'font': {'color': '#e377c2'}}],
    }
    return {'data': data, 'layout': layout}


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
             ('3-D atom map', atom_map(a, colors))]
    if a.get('sections') is not None:
        figs.append(('3-D map with cross-sections', cross_sections(a, colors)))
    if 'vdc' in a:
        figs.append(('Voltage history', voltage(a)))
    if a.get('det_hist') is not None:
        figs.append(('Detector hit map', detector(a)))
    return figs
