"""Reader for Linseis TMA (PT1000LT / PT1600) text exports.

    # Export date and time: ne říj 1 19:42:48 2023
    # Name: <sample>
    #    Measurement date and time: čt zář 21 15:31:24 2023
    #    Length: 30.1 mm
    Time (s)<TAB>Delta L (<sample>) (µm)<TAB>Delta L Rel. exp (<sample>) (%)<TAB>Temperature (<sample>) (°C)
    0.40<TAB>0.00<TAB>0.19<TAB>56.85

The software writes dates with the PC's locale (Czech or English) and the export often loses
non-ASCII characters (µ, °, ř, á ... become '?' or '�'); dates are matched tolerantly.
"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

MONTHS = [
    ['led', 'úno', 'bře', 'dub', 'kvě', 'čvn', 'čvc', 'srp', 'zář', 'říj', 'lis', 'pro'],  # Czech
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'],  # English
]
DATE_RE = re.compile(r'(\S+)\s+(\d{1,2})\s+(\d{1,2}):(\d{2}):(\d{2})\s+(\d{4})\s*$')


def is_linseis_tma(text):
    return '# Name:' in text and 'Measurement date and time' in text and 'Delta L' in text


def _month(token):
    """'zá?' / 'z�?' / 'zář' / 'Sep' -> 9; None if not unique."""
    token = token.lower().rstrip('.')
    pattern = ''.join('.' if (c in '?�' or ord(c) > 127) else re.escape(c) for c in token)
    hits = set()
    for names in MONTHS:
        for i, name in enumerate(names):
            plain = ''.join('.' if ord(c) > 127 else c for c in name)  # compare letter by letter
            if len(name) == len(token) and re.fullmatch(pattern, name) or re.fullmatch(pattern, plain):
                hits.add(i + 1)
    return hits.pop() if len(hits) == 1 else None


def parse_date(text, tz='Europe/Prague'):
    m = DATE_RE.search(text.strip())
    if not m:
        return None
    month = _month(m.group(1))
    if month is None:
        return None
    day, hh, mm, ss, year = (int(m.group(i)) for i in (2, 3, 4, 5, 6))
    try:
        return datetime(year, month, day, hh, mm, ss, tzinfo=ZoneInfo(tz))
    except ValueError:
        return None


def _column_unit(header):
    """'Delta L (name) (µm)' -> 'µm' (non-ASCII-damaged units are normalised)."""
    m = re.search(r'\(([^()]*)\)\s*$', header)
    unit = m.group(1) if m else None
    if unit and ('�' in unit or '?' in unit):
        unit = {'m': 'µm', 'C': '°C'}.get(unit[-1], unit)
    return unit


def read_tma(lines, tz='Europe/Prague'):
    meta, header, rows = {}, None, []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith('#'):
            key, _, value = s.lstrip('#').strip().partition(':')
            meta[key.strip().lower()] = value.strip()
        elif header is None:
            header = s.split('\t')
        else:
            parts = s.split('\t')
            try:
                rows.append([float(p) for p in parts[: len(header)]])
            except ValueError:
                continue
    if header is None or not rows:
        raise ValueError('no data table in the Linseis TMA export')
    data = np.array(rows)
    cols = {}
    for j, h in enumerate(header):
        name = h.lower()
        if name.startswith('time'):
            cols['time'] = data[:, j]
        elif 'rel. exp' in name:
            cols['relative_expansion'] = data[:, j]
        elif name.startswith('delta l'):
            unit = _column_unit(h)
            cols['delta_length'] = data[:, j] * (1000 if unit == 'mm' else 1)  # µm
        elif name.startswith('temperature'):
            cols['temperature'] = data[:, j]
    length = None
    if 'length' in meta:
        m = re.match(r'([-\d.]+)\s*(mm|µm|um)?', meta['length'].replace('�', 'µ'))
        if m:
            length = float(m.group(1)) * (1e-3 if m.group(2) in ('µm', 'um') else 1)
    name = meta.get('name')
    stress = None
    if name:
        m = re.search(r'(\d+(?:[.,]\d+)?)\s*MPa', name, re.IGNORECASE)
        if m:
            stress = float(m.group(1).replace(',', '.'))
    return {
        'name': name,
        'measurement_date': parse_date(meta.get('measurement date and time', ''), tz),
        'export_date': parse_date(meta.get('export date and time', ''), tz),
        'initial_length': length,  # mm
        'stress_from_name': stress,  # MPa
        'columns': header,
        **cols,
    }


def segments(temperature, time, min_rate=0.1, min_points=20, min_span=5.0):
    """Split the record into cooling / heating / isothermal parts (rate in K/min).

    Returns [(kind, start, stop)], stop exclusive. A ramp must change the temperature by at
    least `min_span` K, otherwise it counts as a hold (overshoot, regulation); short parts
    are merged into neighbours."""
    T = np.asarray(temperature, dtype=float)
    t = np.asarray(time, dtype=float)
    n = len(T)
    if n < 3:
        return [('isothermal', 0, n)]
    w = max(1, min(15, n // 50))
    Ts = np.convolve(T, np.ones(2 * w + 1) / (2 * w + 1), mode='same')
    Ts[:w], Ts[-w:] = T[:w], T[-w:]
    rate = np.gradient(Ts, t) * 60  # K/min
    kind = np.where(rate > min_rate, 1, np.where(rate < -min_rate, -1, 0))
    parts = []
    start = 0
    for i in range(1, n + 1):
        if i == n or kind[i] != kind[start]:
            parts.append([int(kind[start]), start, i])
            start = i
    for p in parts:  # small temperature change: hold, not a ramp
        if p[0] != 0 and abs(T[p[2] - 1] - T[p[1]]) < min_span:
            p[0] = 0
    merged = []
    for p in parts:  # absorb short parts into the previous one
        if merged and (p[2] - p[1] < min_points or p[0] == merged[-1][0]):
            merged[-1][2] = p[2]
        else:
            merged.append(p)
    if len(merged) > 1 and merged[0][2] - merged[0][1] < min_points:
        merged[1][1] = 0
        merged.pop(0)
    names = {1: 'heating', -1: 'cooling', 0: 'isothermal'}
    return [(names[k], a, b) for k, a, b in merged]
