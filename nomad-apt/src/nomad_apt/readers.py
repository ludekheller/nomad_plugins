"""Readers for atom probe files (no dependencies beyond numpy).

* .pos   reconstruction: per ion x, y, z (nm), mass-to-charge (Da); big-endian float32
* .epos  as .pos plus TOF (ns), V_dc (V), V_pulse (V), detector x, y (mm) (float32),
         pulses since last event, ions per pulse (int32)
* .apt   AP Suite 6 exchange format: header + named sections (Position, Mass, Voltage,
         XDet_mm ...); layout as documented in ifes_apt_tc_data_modeling (Apache-2.0)
* .rrng  range file (IVAS / AP Suite text, [Ions] / [Ranges])
* .rng   range file (Oak Ridge text format)
* .hits / .rhit / .rraw  CAMECA raw data: closed format, only recorded (name, size, run)

Large files are memory-mapped and processed in chunks; nothing is loaded at once.
"""

import os
import re

import numpy as np

POS_DTYPE = np.dtype([('x', '>f4'), ('y', '>f4'), ('z', '>f4'), ('m', '>f4')])
EPOS_DTYPE = np.dtype([('x', '>f4'), ('y', '>f4'), ('z', '>f4'), ('m', '>f4'), ('tof', '>f4'),
                       ('vdc', '>f4'), ('vpulse', '>f4'), ('det_x', '>f4'), ('det_y', '>f4'),
                       ('pulse_delta', '>i4'), ('multiplicity', '>i4')])
RAW_EXT = ('.hits', '.rhit', '.rraw')
RECON_EXT = ('.epos', '.apt', '.pos')  # order = preference when several exist
RANGE_EXT = ('.rrng', '.rng')
RUN_RE = re.compile(r'R\d+_\d+', re.I)
CHUNK = 4_000_000


def run_key(filename):
    """'R6043_00349-v02.epos' -> 'R6043_00349'; files without a run number -> stem."""
    base = os.path.basename(filename)
    m = RUN_RE.search(base)
    return m.group(0).upper() if m else os.path.splitext(base)[0]


def kind(filename):
    ext = os.path.splitext(filename)[1].lower()
    return 'raw' if ext in RAW_EXT else 'reconstruction' if ext in RECON_EXT else 'range' if ext in RANGE_EXT else None


# ---------------------------------------------------------------- reconstruction
def open_ions(path):
    """Structured array (memory-mapped for .pos/.epos) with at least x, y, z, m."""
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.pos', '.epos'):
        dt = POS_DTYPE if ext == '.pos' else EPOS_DTYPE
        size = os.path.getsize(path)
        if size == 0 or size % dt.itemsize:
            raise ValueError(f'{os.path.basename(path)}: size {size} B is not a multiple of {dt.itemsize} B '
                             f'({ext} record)')
        return np.memmap(path, dtype=dt, mode='r')
    if ext == '.apt':
        return read_apt6(path)
    raise ValueError(f'not a reconstruction file: {path}')


# ---------------------------------------------------------------- AP Suite .apt
APT_HEADER = np.dtype([('sig', 'u1', 4), ('header_size', '<i4'), ('header_version', '<i4'),
                       ('filename', '<u2', 256), ('creation_time', '<u8'), ('ion_count', '<u8')])
APT_SECTION = np.dtype([('sig', 'u1', 4), ('header_size', '<i4'), ('header_version', '<i4'),
                        ('type', '<u2', 32), ('section_version', '<i4'), ('relationship', '<u4'),
                        ('record_type', '<u4'), ('data_type', '<u4'), ('type_size', '<i4'),
                        ('record_size', '<i4'), ('unit', '<u2', 16), ('record_count', '<u8'),
                        ('byte_count', '<u8')])
# section name in the .apt file -> column name(s) used here (same names as .epos)
APT_COLUMNS = {'Position': ('x', 'y', 'z'), 'Mass': ('m',), 'tof': ('tof',), 'Voltage': ('vdc',),
               'Pulse Voltage': ('vpulse',), 'XDet_mm': ('det_x',), 'YDet_mm': ('det_y',),
               'Detector Coordinates': ('det_x', 'det_y'), 'Multiplicity': ('multiplicity',),
               'pulseDelta': ('pulse_delta',)}
# acquisition channels kept for the run summary (median over the run)
APT_CHANNELS = {'Temp': 'temperature_K', 'freq': 'frequency_Hz', 'erate': 'detection_rate',
                'laserpower': 'laser_power', 'Pres': 'pressure_torr', 'tElapsed': 'elapsed', 'pulse': 'pulse'}


def _u16(a):
    return ''.join(chr(v) for v in a if v)


class Columns:
    """Column store that behaves like a structured array for the analysis (len, ['m'], [slice])."""

    def __init__(self, cols):
        self.cols = cols

    @property
    def names(self):
        return tuple(self.cols)

    def __len__(self):
        return len(next(iter(self.cols.values())))

    def __getitem__(self, key):
        if isinstance(key, str):
            return self.cols[key]
        return Columns({k: v[key] for k, v in self.cols.items()})


def read_apt6(path):
    """AP Suite .apt: one-to-one sections are memory-mapped; returns Columns (+ .channels, .sections)."""
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        h = np.fromfile(f, APT_HEADER, count=1)
        if len(h) == 0 or bytes(h['sig'][0]) != b'APT\0':
            raise ValueError(f'{os.path.basename(path)} is not an AP Suite .apt file')
        n = int(h['ion_count'][0])
        pos = int(h['header_size'][0])
        sections = {}
        while pos + APT_SECTION.itemsize <= size:
            f.seek(pos)
            sec = np.fromfile(f, APT_SECTION, count=1)[0]
            if bytes(sec['sig'])[:3] != b'SEC':
                break
            name = _u16(sec['type'])
            start = pos + int(sec['header_size'])
            sections[name] = dict(start=start, unit=_u16(sec['unit']), records=int(sec['record_count']),
                                  record_size=int(sec['record_size']), type_size=int(sec['type_size']),
                                  data_type=int(sec['data_type']), relationship=int(sec['relationship']))
            pos = start + int(sec['byte_count'])
    cols, channels = {}, {}
    for name, s in sections.items():
        kind_ = {1: 'i', 2: 'u', 3: 'f'}.get(s['data_type'])
        if kind_ is None or s['relationship'] != 1 or s['records'] != n or s['type_size'] not in (8, 16, 32, 64):
            continue
        dt = np.dtype(f'<{kind_}{s["type_size"] // 8}')
        width = s['record_size'] // dt.itemsize
        if width < 1:
            continue
        a = np.memmap(path, dtype=dt, mode='r', offset=s['start'], shape=(n, width) if width > 1 else (n,))
        targets = APT_COLUMNS.get(name)
        if targets and len(targets) == width:
            for i, t in enumerate(targets):
                cols[t] = a[:, i] if width > 1 else a
        elif name in APT_CHANNELS and width == 1:
            channels[APT_CHANNELS[name]] = (a, s['unit'])
    if not {'x', 'y', 'z', 'm'} <= set(cols):
        raise ValueError(f'.apt file without Position and Mass sections (found: {", ".join(sections)})')
    out = Columns(cols)
    out.channels = channels
    out.sections = list(sections)
    return out


def _names(ions):
    return ions.names if isinstance(ions, Columns) else ions.dtype.names


def channel_medians(ions, max_points=200_000):
    """Median of acquisition channels in an .apt file (temperature, frequency, detection rate ...)."""
    out = {}
    for k, (a, unit) in getattr(ions, 'channels', {}).items():
        step = max(1, len(a) // max_points)
        v = np.asarray(a[::step], float)
        v = v[np.isfinite(v)]
        if v.size:
            out[k] = float(np.median(v)) if k != 'elapsed' else float(np.max(v))
    return out


# ---------------------------------------------------------------- ranges
def _formula(comp):
    return ''.join(f'{el}{n if n != 1 else ""}' for el, n in comp.items())


def read_rrng(text):
    """-> list of ranges {low, high, ion, composition {element: n}, color '#rrggbb', volume}."""
    section, ranges = None, []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('['):
            section = line.strip('[]').lower()
            continue
        if section != 'ranges' or not line.lower().startswith('range') or '=' not in line:
            continue
        parts = line.split('=', 1)[1].split()
        low, high = float(parts[0].replace(',', '.')), float(parts[1].replace(',', '.'))
        comp, color, volume, name = {}, None, None, None
        for p in parts[2:]:
            if ':' not in p:
                continue
            k, v = p.split(':', 1)
            if k.lower() == 'vol':
                volume = float(v.replace(',', '.'))
            elif k.lower() == 'color':
                color = '#' + v.lower()
            elif k.lower() == 'name':
                name = v
            else:
                try:
                    n = int(float(v))
                except ValueError:
                    continue
                if n > 0:
                    comp[k] = n
        ranges.append({'low': low, 'high': high, 'composition': comp, 'color': color, 'volume': volume,
                       'ion': name or _formula(comp) or 'unknown'})
    return ranges


def read_rng(text):
    """Oak Ridge .rng: 'n_ions n_ranges', ion name + colour lines, '----- names', '. low high n1 n2 ...'."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    n_ions, n_ranges = (int(v) for v in lines[0].split()[:2])
    colors = {}
    names = []
    i = 1
    for _ in range(n_ions):
        name = lines[i].split()[0]
        rgb = [float(v) for v in lines[i + 1].split()[:3]]
        colors[name] = '#' + ''.join(f'{int(round(255 * c)):02x}' for c in rgb)
        i += 2
    while i < len(lines) and not lines[i].startswith('-'):
        i += 1
    names = lines[i].lstrip('-').split()
    ranges = []
    for line in lines[i + 1:i + 1 + n_ranges]:
        parts = line.split()
        if parts[0] == '.':
            parts = parts[1:]
        low, high = float(parts[0]), float(parts[1])
        counts = [int(float(v)) for v in parts[2:2 + len(names)]]
        comp = {el: n for el, n in zip(names, counts) if n > 0}
        ion = _formula(comp) or 'unknown'
        ranges.append({'low': low, 'high': high, 'composition': comp, 'volume': None, 'ion': ion,
                       'color': colors.get(ion) or (colors.get(next(iter(comp))) if len(comp) == 1 else None)})
    return ranges


def read_ranges(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        text = f.read()
    ranges = read_rrng(text) if path.lower().endswith('.rrng') else read_rng(text)
    return sorted(ranges, key=lambda r: r['low'])


# ---------------------------------------------------------------- analysis
def _label(m, lows, highs):
    """Range index per ion; len(lows) for unranged ions."""
    nr = len(lows)
    if nr == 0:
        return np.zeros(len(m), dtype=np.int64)
    idx = np.searchsorted(lows, m, side='right') - 1
    ok = (idx >= 0) & (m <= highs[np.clip(idx, 0, None)])
    return np.where(ok, idx, nr)


def _bin(v, lo, hi, nb):
    return np.clip(((v - lo) / (hi - lo) * nb).astype(np.int64), 0, nb - 1) if hi > lo else np.zeros(len(v), np.int64)


def analyse(ions, ranges=None, bin_width=0.05, max_mass=None, n_sample=20000, det_bins=80, seed=0,
            map_bins=60, depth_slice=None, depth_mass_bin=0.25, depth_mass_max=150.0, depth_mass_slices=60):
    """Chunked passes over all ions. Returns a plain dict with:
    n_ions; mass spectrum (bin centres, counts); counts per range / ranged ion / element;
    depth (nm from the top of the reconstruction) profile: counts per depth slice and range;
    2-D maps (x-y and x-depth) of counts per range; mass spectrum vs depth (2-D histogram);
    a random sample of ions for the 3-D view; V_dc history, detector hit map, multiple-hit
    fraction (when the file has these channels); medians of .apt acquisition channels."""
    n = len(ions)
    if n == 0:
        raise ValueError('no ions in the reconstruction file')
    names = _names(ions)

    # pass 1: extents
    lim = {k: [np.inf, -np.inf] for k in ('m', 'x', 'y', 'z')}
    for a in range(0, n, CHUNK):
        for k in lim:
            v = np.asarray(ions[k][a:a + CHUNK], dtype=np.float64)
            v = v[np.isfinite(v)]
            if v.size:
                lim[k] = [min(lim[k][0], v.min()), max(lim[k][1], v.max())]
    top = min(max_mass or 1e9, max(10.0, np.ceil(lim['m'][1] + 1)), 300.0)
    edges = np.arange(0.0, top + bin_width, bin_width)
    hist = np.zeros(len(edges) - 1, dtype=np.int64)
    (x0, x1), (y0, y1), (z0, z1) = lim['x'], lim['y'], lim['z']
    depth_total = float(z1 - z0)
    # depth = distance from the top (largest z) of the reconstruction
    dslice = depth_slice or max(0.5, round(depth_total / 150, 1))
    nd = max(1, int(np.ceil(depth_total / dslice)))

    ranges = ranges or []
    lows = np.array([r['low'] for r in ranges])
    highs = np.array([r['high'] for r in ranges])
    nl = len(ranges) + 1  # last label = unranged
    G = map_bins
    prof = np.zeros(nd * nl, dtype=np.int64)
    map_xy = np.zeros(nl * G * G, dtype=np.int64)
    map_xd = np.zeros(nl * G * G, dtype=np.int64)
    mtop = min(top, depth_mass_max)
    nm = int(np.ceil(mtop / depth_mass_bin))
    nds = depth_mass_slices
    spec_depth = np.zeros(nds * nm, dtype=np.int64)

    has_v = 'vdc' in names
    det = 'det_x' in names and 'det_y' in names
    multi = 'multiplicity' in names
    det_edges = det_hist = None
    mult = np.zeros(2, dtype=np.int64)  # [single-hit ions, ions in multiple-hit events]

    # pass 2: everything else
    for a in range(0, n, CHUNK):
        c = ions[a:a + CHUNK]
        m = np.asarray(c['m'], dtype=np.float64)
        x, y = np.asarray(c['x'], np.float64), np.asarray(c['y'], np.float64)
        d = z1 - np.asarray(c['z'], np.float64)
        good = np.isfinite(m) & np.isfinite(x) & np.isfinite(y) & np.isfinite(d)
        if not good.all():
            m, x, y, d = m[good], x[good], y[good], d[good]
        hist += np.histogram(m, bins=edges)[0]
        lab = _label(m, lows, highs)
        ib = _bin(d, 0, depth_total, nd)
        prof += np.bincount(ib * nl + lab, minlength=nd * nl)
        ix, iy, idd = _bin(x, x0, x1, G), _bin(y, y0, y1, G), _bin(d, 0, depth_total, G)
        map_xy += np.bincount((lab * G + iy) * G + ix, minlength=nl * G * G)
        map_xd += np.bincount((lab * G + idd) * G + ix, minlength=nl * G * G)
        inm = m < mtop
        im = np.clip((m[inm] / depth_mass_bin).astype(np.int64), 0, nm - 1)
        spec_depth += np.bincount(_bin(d[inm], 0, depth_total, nds) * nm + im, minlength=nds * nm)
        if det:
            dx, dy = np.asarray(c['det_x'], float), np.asarray(c['det_y'], float)
            if det_edges is None:
                lim_d = float(np.nanmax(np.abs(np.concatenate([dx, dy])))) or 1.0
                lim_d = lim_d if np.isfinite(lim_d) else 1.0
                det_edges = np.linspace(-lim_d, lim_d, det_bins + 1)
                det_hist = np.zeros((det_bins, det_bins), dtype=np.int64)
            det_hist += np.histogram2d(dy, dx, bins=[det_edges, det_edges])[0].astype(np.int64)
        if multi:
            mu = np.asarray(c['multiplicity'])
            mult[0] += int(np.sum(mu == 1))
            mult[1] += int(np.sum(mu[mu > 1]))  # first ion of a multiple event carries the count, the others 0

    prof = prof.reshape(nd, nl)
    range_counts = prof[:, :-1].sum(axis=0)
    out = {'n_ions': n, 'mass': (edges[:-1] + bin_width / 2), 'counts': hist, 'bin_width': bin_width}

    # ranged ions and elements; matrices range -> ion, range -> element (atoms per ion)
    ion_counts, ion_color, ion_comp, ion_windows = {}, {}, {}, {}
    for r, cnt in zip(ranges, range_counts):
        ion = r['ion']
        ion_counts[ion] = ion_counts.get(ion, 0) + int(cnt)
        ion_color.setdefault(ion, r['color'])
        ion_comp.setdefault(ion, r['composition'])
        ion_windows.setdefault(ion, []).append((r['low'], r['high']))
    ions_list = list(ion_counts)
    els = []
    for ion in ions_list:
        els += [e for e in ion_comp[ion] if e not in els]
    R2I = np.zeros((nl, len(ions_list)))
    R2E = np.zeros((nl, len(els)))
    for i, r in enumerate(ranges):
        R2I[i, ions_list.index(r['ion'])] = 1
        for e, k in r['composition'].items():
            R2E[i, els.index(e)] += k
    elements = dict(zip(els, (range_counts @ R2E[:-1]).astype(np.int64).tolist())) if els else {}
    out.update(range_counts=range_counts, ion_counts=ion_counts, ion_color=ion_color, ion_comp=ion_comp,
               ion_windows=ion_windows, element_counts=elements, n_ranged=int(range_counts.sum()),
               ion_order=ions_list, element_order=els)

    # depth profile (per slice): all ions, unranged, per ion, per element (atoms)
    out['profile'] = {'depth': (np.arange(nd) + 0.5) * dslice, 'slice': dslice, 'ions': prof.sum(axis=1),
                      'unranged': prof[:, -1], 'per_ion': prof @ R2I, 'per_element': prof @ R2E}

    # 2-D maps: counts per cell, all ions / per element (atoms)
    def maps(flat, ax1):
        cube = flat.reshape(nl, G, G)
        return {'axis1': ax1, 'x': x0 + (np.arange(G) + 0.5) * (x1 - x0) / G, 'all': cube.sum(axis=0),
                'per_element': np.einsum('lij,le->eij', cube, R2E) if els else None}
    out['map_xy'] = maps(map_xy, y0 + (np.arange(G) + 0.5) * (y1 - y0) / G)
    out['map_xd'] = maps(map_xd, (np.arange(G) + 0.5) * depth_total / G)
    out['spec_depth'] = {'mass': (np.arange(nm) + 0.5) * depth_mass_bin,
                         'depth': (np.arange(nds) + 0.5) * depth_total / nds,
                         'counts': spec_depth.reshape(nds, nm)}
    out['extent'] = {'x': (x0, x1), 'y': (y0, y1), 'z': (z0, z1), 'depth': depth_total}

    # random sample for the 3-D view
    rng = np.random.default_rng(seed)
    pick = np.sort(rng.choice(n, size=min(n, n_sample), replace=False))
    s = ions[pick]
    lab = _label(np.asarray(s['m'], float), lows, highs)
    label = np.array([ranges[i]['ion'] if i < len(ranges) else 'unranged' for i in lab], dtype=object)
    out['sample'] = {'x': np.asarray(s['x'], float), 'y': np.asarray(s['y'], float),
                     'z': np.asarray(s['z'], float), 'ion': label}
    if has_v:
        out['vdc_index'] = np.arange(0, n, max(1, n // 2000))
        out['vdc'] = np.asarray(ions['vdc'][out['vdc_index']], float)
    if det:
        out['det_edges'], out['det_hist'] = det_edges, det_hist
    if multi:
        out['multiple_fraction'] = float(mult[1] / n)  # fraction of ions detected in multiple-hit events
    out['channels'] = channel_medians(ions)
    return out


# ---------------------------------------------------------------- AP Suite experiment export (.xml)
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
ROOT_CLASSES = re.compile(r'^(T[A-Z]\w+|C[A-Z]\w+|\d[\w.]*|\d?\w{3} +\d+ \d{4}|\d+\.\d+/\d+)$')


def is_uuid_name(filename):
    return bool(UUID_RE.match(os.path.splitext(os.path.basename(filename))[0]))


def _root_strings(blob_b64, stop=b'CRefSpatMap'):
    """Readable strings of the run header in the CAMECA ROOT blob (<Parameters>, base64).

    The blob itself is a closed format; only the zlib-compressed ROOT records are unpacked and
    the text strings (length-prefixed) of the run header are returned, in order. Best effort."""
    import base64
    import zlib

    b = base64.b64decode(blob_b64)
    out, i = b'', 0
    while (j := b.find(b'ZL\x08', i)) >= 0:
        try:
            out += zlib.decompressobj().decompress(b[j + 9:])
        except zlib.error:
            pass
        i = j + 3
    head = out[:out.find(stop)] if stop in out else out[:200_000]
    res = []
    for m in re.finditer(rb'[\x20-\x7e\t\n\r]{4,}', head):
        a, b_ = m.span()
        text = None
        for o in range(0, 6):  # skip a printable length prefix (1 byte, or 4 bytes big-endian)
            st = a + o
            if st >= b_ - 2:
                break
            n = b_ - st
            short = head[st - 1] in (n, n + 1)
            long_ = st >= 4 and head[st - 4] == 0 and 0 <= int.from_bytes(head[st - 4:st], 'big') - n <= 8
            if short or long_:
                text = head[st:b_]
                break
        text = (text if text is not None else head[a:b_]).decode().replace('\r', '').strip()
        if len(text) >= 3:
            res.append(text)
    return res, out


def _num(pattern, text, flags=re.I):
    m = re.search(pattern, text, flags)
    return float(m.group(1)) if m else None


def run_info(blob_b64):
    """Run header from the reconstruction parameters: title, specimen, date, comments, values."""
    strings, raw = _root_strings(blob_b64)
    info = {'header': [s for s in strings if not ROOT_CLASSES.match(s)]}
    titles = [s for s in strings if RUN_RE.match(s) and ' ' in s]
    if titles:
        parts = titles[0].split()
        info['run'] = parts[0]
        if len(parts) >= 2:
            info['specimen'] = ' '.join(p for p in parts[1:] if not re.fullmatch(r'\d{2}-\d{2}-\d{4}', p))
        d = re.search(r'(\d{2})-(\d{2})-(\d{4})', titles[0])  # MM-DD-YYYY
        if d:
            info['date'] = f'{d.group(3)}-{d.group(1)}-{d.group(2)}T12:00:00'  # date only: noon, no day shift
        # the run comments follow the title in the laser header
        k = strings.index(titles[0], strings.index(titles[0]) + 1) if titles[0] in strings[1:] else None
        if k is not None and k + 1 < len(strings):
            info['comments'] = strings[k + 1]
    text = '\n'.join(info['header'])
    c = info.get('comments', '')
    info['values'] = {k: v for k, v in {
        'detection_rate': _num(r'\bD(?:et\.?\s*)?R(?:ate)?\s*[:=]?\s*([\d.]+)\s*%', c),
        'base_temperature': _num(r'Temp(?:erature)?\s*[:=]?\s*([\d.]+)\s*K\b', c),
        'laser_energy': _num(r'([\d.]+)\s*pJ', c),
        'start_voltage': _num(r'start(?:ing)?(?: voltage)?\s*[:=]?\s*([\d.]+)\s*V\b', c),
        'laser_wavelength': _num(r'\b(\d{3})\s*nm\b', text),
    }.items() if v is not None}
    for code, name in ((rb'5000R\b', 'CAMECA LEAP 5000 XR'), (rb'5000S\b', 'CAMECA LEAP 5000 XS'),
                       (rb'6000R\b', 'CAMECA LEAP 6000 XR'), (rb'4000X? ?HR\b', 'CAMECA LEAP 4000X HR'),
                       (rb'4000X? ?Si\b', 'CAMECA LEAP 4000X Si')):
        if re.search(code, raw):
            info['instrument'] = name
            break
    config = sorted({m.decode() for m in re.findall(rb'\bc[A-Z][A-Za-z0-9]+=[\x20-\x7e]{1,40}', raw)})
    if config:
        info['configuration'] = '\n'.join(config)
    if any(s.lower() == 'fractured' for s in strings):
        info['outcome'] = 'fractured'
    return info


def read_experiment_xml(path):
    """AP Suite 'export experiment' .xml: raw file name and the exported reconstructions
    (id = name of the .apt file, name, comments, creation time, user)."""
    import xml.etree.ElementTree as ET

    with open(path, 'rb') as f:
        data = f.read()
    for enc in ('utf-8-sig', 'utf-16'):  # declared utf-16, often written as utf-8
        try:
            text = data.decode(enc)
            if '<ExportExperiment' in text:
                break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f'{os.path.basename(path)} is not an AP Suite experiment export')
    root = ET.fromstring(re.sub(r'^\s*<\?xml[^>]*\?>', '', text))
    out = {'raw_file': (root.findtext('Filename') or '').strip() or None, 'reconstructions': []}
    for r in root.iter('ExportReconstruction'):
        out['reconstructions'].append({k: (r.findtext(tag) or '').strip() or None for k, tag in (
            ('id', 'ReconstructionId'), ('name', 'Name'), ('comments', 'Comments'),
            ('created', 'TimeOfCreation'), ('user', 'UserName'), ('method', 'CreationMethod'),
            ('parameters', 'Parameters'))})
    return out
