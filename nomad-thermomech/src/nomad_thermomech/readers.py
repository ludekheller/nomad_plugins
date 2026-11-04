"""Readers for the files of one thermomechanical test (no NOMAD imports).

Instron WaveMatrix writes a set of files per test, all named TestNNN.*:
    TestNNN.log                 event log (start/end, method, versions, frame serial)
    TestNNN.specimen.txt        specimen type and cross-sectional area
    TestNNN.Stop.csv            full data record (preferred)
    TestNNN.steps.tracking.csv  same data from the first tracked step (fallback)
    TestNNN.steps.trends.csv    per step/loop summary (max/min values)
    TestNNN.itr_wma / .im_gpf   method / results (Instron XML; kept as raw files)
Mercury RT writes one ';'-separated export per test (header 'Frame ID;Absolute Timestamp;...').
"""

import csv
import io
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

EXCEL_EPOCH = datetime(1899, 12, 30)
TIME_ZONE = ZoneInfo('Europe/Prague')  # clocks of the Instron and Mercury PCs
MERCURY_HEADER = 'Frame ID;Absolute Timestamp'


def _rows(text, delimiter=','):
    return list(csv.reader(io.StringIO(text.lstrip('﻿')), delimiter=delimiter))


def _float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return np.nan


def _unit(header):
    """'Axial Load (N)' -> ('Axial Load', 'N'); 'A1 - Length [mm]' -> ('A1 - Length', 'mm')."""
    m = re.match(r'^(.*?)\s*[\(\[]([^\)\]]*)[\)\]]\s*(\(expr\.\))?\s*$', header.strip())
    return (m.group(1).strip(), m.group(2).strip()) if m else (header.strip(), '')


# ---------------------------------------------------------------- WaveMatrix
def read_log(text):
    """Metadata from TestNNN.log."""
    meta, events = {}, []
    for row in _rows(text):
        if len(row) < 6:
            continue
        date, time, method, test, code, what = row[:6]
        value = row[6] if len(row) > 6 else ''
        stamp = datetime.strptime(f'{date} {time}', '%d/%m/%Y %H:%M:%S').replace(tzinfo=TIME_ZONE)
        meta.setdefault('method', method)
        meta.setdefault('test_name', test)
        key = what.strip()
        if key == 'Test Started':
            meta['start_time'] = stamp
        elif key == 'Test Finished':
            meta['end_time'] = stamp
        elif key in ('Software Version', 'Console Version', 'Controller Version',
                     'User Name', 'Computer Name', 'Test Status', 'Total Time'):
            meta[key] = value
        elif key.startswith('Frame Serial Number'):
            meta['Frame Serial Number'] = value
        events.append(f'{date} {time}  {what} {value}'.rstrip())
    meta['events'] = events
    return meta


def read_specimen(text):
    out = {}
    for line in text.splitlines():
        k, _, v = line.partition(':')
        if k.strip() == 'Specimen Type':
            out['specimen_type'] = v.strip()
        elif k.strip() == 'Cross Sectional Area':
            out['cross_section_area_mm2'] = _float(v.split()[0]) if v.split() else np.nan
    return out


def read_wavematrix_data(text):
    """Stop.csv / steps.tracking.csv -> dict of arrays keyed by column header."""
    rows = _rows(text)
    header = [h for h in rows[0] if h.strip()]
    data = np.array([[_float(v) for v in r[: len(header)]] for r in rows[1:] if len(r) >= len(header)])
    return {h: data[:, i] for i, h in enumerate(header)}


def read_trends(text):
    rows = _rows(text)
    header = [h for h in rows[0] if h.strip()]
    return [dict(zip(header, (_float(v) for v in r))) for r in rows[1:] if len(r) >= len(header)]


def excel_to_datetime(x):
    return (EXCEL_EPOCH + timedelta(days=float(x))).replace(tzinfo=TIME_ZONE)


# ---------------------------------------------------------------- Mercury RT
def is_mercury_export(first_line):
    return first_line.lstrip('﻿').startswith(MERCURY_HEADER)


def read_mercury(text):
    """Mercury RT export -> (columns dict of arrays, metadata)."""
    rows = _rows(text, delimiter=';')
    header = rows[0]
    body = [r for r in rows[1:] if len(r) >= len(header)]
    cols = {}
    for i, h in enumerate(header):
        if h == 'Absolute Timestamp':
            continue
        cols[h] = np.array([_float(r[i]) for r in body])
    meta = {
        'start_time': datetime.strptime(body[0][header.index('Absolute Timestamp')], '%m/%d/%Y %H:%M:%S').replace(tzinfo=TIME_ZONE),
        'n_frames': len(body),
    }
    # extensometer columns: '<name> - Length [mm]' etc.
    ext = sorted({h.split(' - ')[0] for h in header if ' - Length' in h})
    meta['extensometers'] = ext
    if ext:
        L = cols.get(f'{ext[0]} - Length [mm]')
        if L is not None and len(L):
            meta['gauge_length_mm'] = float(L[0])
    return cols, meta


def find_column(cols, *candidates):
    """First column whose header starts with one of the candidates (case-insensitive)."""
    for c in candidates:
        for h in cols:
            if h.lower().startswith(c.lower()):
                return h
    return None
