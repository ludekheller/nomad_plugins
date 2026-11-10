"""Readers for the Walter+Bai (UTTRMO) machine record and its 1D DIC export.

Machine record: text file without extension, tab-separated, one header line
'Time / s<TAB>Position / mm<TAB>Force / N<TAB>...', missing values 'NaN'.
1D DIC export: '<name>_dic.csv', ';'-separated, header 'Fram ID;Absolute Timestamp;...' and
per tracked point 'Tnnn - Displacement [mm]', 'Tnnn - Position in X [mm]', 'Tnnn - Position in Y [mm]'.
"""

import re

import numpy as np

MACHINE_MARK = 'Time / s\tPosition / mm\tForce / N'
DIC_POINT_RE = re.compile(r'^(T\d+) - Displacement \[mm\]$')


def is_machine_header(line):
    return line.lstrip('﻿').startswith(MACHINE_MARK)


MACHINES = ['Walter+Bai (UTTRMO)', 'MITTER', 'other']


def detect_machine(columns):
    """Machine from the column set of the record (both machines use the same software)."""
    if 'Water_Temp_Down / C' in columns:
        return 'MITTER'
    if 'Position_laser_sensor / mm' in columns:
        return 'Walter+Bai (UTTRMO)'
    return None


def is_dic_header(line):
    line = line.lstrip('﻿')
    return bool(re.match(r'Fram(e)? ID;Absolute Timestamp;', line)) and ' - Displacement [mm]' in line


def _split_name_unit(header):
    """'Force / N' -> ('Force', 'N'); 'Cycle number 1' -> ('Cycle number 1', None)."""
    if ' / ' in header:
        name, unit = header.rsplit(' / ', 1)
        return name.strip(), unit.strip()
    return header.strip(), None


def read_machine(lines):
    """-> dict column header -> float array (NaN for missing), plus [(header, label)] in file order.

    Time is shifted to start at zero (the machine counts from an arbitrary offset)."""
    header = lines[0].lstrip('﻿').split('\t')
    rows = [ln.split('\t') for ln in lines[1:] if ln.strip()]
    n = len(header)
    data = np.full((len(rows), n), np.nan)
    for i, r in enumerate(rows):
        for j in range(min(n, len(r))):
            try:
                data[i, j] = float(r[j])
            except ValueError:
                pass
    cols = {h: data[:, j] for j, h in enumerate(header)}
    t = cols[header[0]]
    cols[header[0]] = t - t[np.isfinite(t)][0]
    labels = []
    for h in header:
        name, unit = _split_name_unit(h)
        unit = {'C': '°C', 'Om': 'Ohm'}.get(unit, unit)
        labels.append((h, f'{name.replace("_", " ")} ({unit})' if unit else name.replace('_', ' ')))
    return cols, labels


def read_dic(lines):
    """-> dict with time (zero-based), point names, x0/y0 (mm, first frame), displacement
    (frames x points, mm), start date string, local strains and gauge strain.

    Local strain between neighbouring points a, b at frame i:
        100 * (d_b,i - d_a,i) / sqrt((x_b,0 - x_a,0)^2 + (y_b,0 - y_a,0)^2)
    Gauge strain: the same between the first and the last point."""
    header = lines[0].lstrip('﻿').split(';')
    rows = [ln.split(';') for ln in lines[1:] if ln.strip()]
    idx = {h: j for j, h in enumerate(header)}

    def col(h):
        j = idx[h]
        out = np.full(len(rows), np.nan)
        for i, r in enumerate(rows):
            try:
                out[i] = float(r[j])
            except (ValueError, IndexError):
                pass
        return out

    points = [m.group(1) for h in header if (m := DIC_POINT_RE.match(h))]
    if len(points) < 2:
        raise ValueError('DIC export needs at least two tracked points')
    t_key = 'Frame Relative Time [s]' if 'Frame Relative Time [s]' in idx else 'Computer Clock Time [s]'
    t = col(t_key)
    t = t - t[np.isfinite(t)][0]
    disp = np.column_stack([col(f'{p} - Displacement [mm]') for p in points])
    x0 = np.array([col(f'{p} - Position in X [mm]')[0] for p in points])
    y0 = np.array([col(f'{p} - Position in Y [mm]')[0] for p in points])
    along = np.hypot(x0 - x0[0], y0 - y0[0])  # position along the specimen from the first point
    seg_l0 = np.hypot(np.diff(x0), np.diff(y0))
    local = 100 * np.diff(disp, axis=1) / seg_l0
    gauge_l0 = np.hypot(x0[-1] - x0[0], y0[-1] - y0[0])
    gauge = 100 * (disp[:, -1] - disp[:, 0]) / gauge_l0
    date = None
    if 'Absolute Timestamp' in idx and rows:
        m = re.match(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', rows[0][idx['Absolute Timestamp']].strip())
        if m:
            date = f'{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}'
    return {
        'time': t, 'points': points, 'x0': x0, 'y0': y0, 'displacement': disp,
        'segments': [f'{a}–{b}' for a, b in zip(points[:-1], points[1:])],
        'segment_position': (along[:-1] + along[1:]) / 2, 'segment_length': seg_l0,
        'local_strain': local, 'gauge_strain': gauge, 'gauge_length': gauge_l0,
        'gauge_points': f'{points[0]}–{points[-1]}', 'date': date,
    }
