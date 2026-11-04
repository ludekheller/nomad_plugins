"""Reader for TA Instruments TRIOS DSC CSV exports.

`read_trios_csv` turns the text of a TRIOS CSV export into a plain dict in the layout of
the `DSC_SMA` section (values in the schema units: °C, K/min, mL/min, s, W/g, kg).
No NOMAD imports here, so the reader can be tested and reused on its own.

What is read:
  header / [File Parameters] / [Procedure] / [Configuration] -> specimen + settings
  [analysis] blocks -> TRIOS onset/endset results; exactly one onset/endset on cooling
                       and on heating are copied to Ms/Mf and As/Af
  [step] blocks     -> one segment per procedure step (time, temperature, heat flow)
"""

import math
import re
from datetime import datetime
from zoneinfo import ZoneInfo

USED_COLUMNS = ('Time', 'Temperature', 'Heat Flow (Normalized)')
EXPECTED_UNITS = {'Time': 's', 'Temperature': '°C', 'Heat Flow (Normalized)': 'W/g'}


def split_blocks(lines):
    """Return (header key/values, list of (block_name, lines))."""
    header, blocks, cur_name, cur = {}, [], None, []
    for ln in lines:
        s = ln.strip()
        if s.startswith('[') and s.endswith(']'):
            if cur_name is not None:
                blocks.append((cur_name, cur))
            cur_name, cur = s[1:-1], []
        elif cur_name is None:
            k, _, v = ln.partition(',')
            header[k.strip()] = v.strip()
        else:
            cur.append(ln)
    if cur_name is not None:
        blocks.append((cur_name, cur))
    return header, blocks


def kv(block_lines):
    d = {}
    for ln in block_lines:
        k, _, v = ln.partition(',')
        if k.strip():
            d.setdefault(k.strip(), v.strip())
    return d


def number(text):
    m = re.search(r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?', text or '')
    return float(m.group()) if m else None


def parse_step(block_lines):
    title = block_lines[0].strip()
    cols = [c.strip() for c in block_lines[1].split(',')]
    units = [u.strip() for u in block_lines[2].split(',')]
    data = {c: [] for c in cols}
    for ln in block_lines[3:]:
        parts = ln.split(',')
        if len(parts) < len(cols):
            continue
        row = dict(zip(cols, parts))
        if any(not row.get(c, '').strip() for c in USED_COLUMNS):
            continue  # incomplete row (e.g. trailing '5519.20,,,,,'); JSON has no NaN
        for c, p in row.items():
            data[c].append(float(p) if p.strip() else math.nan)
    return title, dict(zip(cols, units)), data


def parse_analysis(block_lines):
    rec = {'details': [], 'results': []}
    for ln in block_lines:
        if not ln.strip():
            continue
        k, _, v = ln.partition(',')
        k, v = k.strip(), v.strip()
        if k == 'Analysed step':
            rec['analysed_step'] = v
        elif k == 'Model':
            rec['model'] = v
        elif ('cursor' not in k.lower() and re.search(r'\s(x|y)$', k)) or any(
            w in k.lower() for w in ('enthalpy', 'integral', 'area')
        ):
            rec['results'].append((k, number(v), v.split()[-1] if ' ' in v else ''))
        else:
            rec['details'].append(f'{k}: {v}' if v else k)
    return rec


def overlay_figure(ramps):
    """Plotly figure with one line per ramp (heat flow vs temperature, exotherm up)."""
    return {
        'data': [
            {'type': 'scattergl', 'mode': 'lines', 'name': label, 'x': T, 'y': q}
            for label, T, q in ramps
        ],
        'layout': {
            'title': {'text': 'All ramps - heat flow vs temperature (exotherm up)'},
            'xaxis': {'title': {'text': 'Temperature (°C)'}},
            'yaxis': {'title': {'text': 'Heat flow (W/g), exotherm up'}},
            'legend': {'title': {'text': 'ramp'}},
        },
    }


def is_trios_dsc(lines):
    head = '\n'.join(lines[:10])
    return 'Instrument name,DSC' in head and any(ln.strip() == '[step]' for ln in lines)


def read_trios_csv(lines, csv_name, tz='Europe/Prague'):
    """Parse the lines of a TRIOS DSC CSV export into a DSC_SMA-shaped dict.

    `csv_name` is the CSV path relative to the upload (stored as data_file).
    Returns (data, ramps); ramps = [(label, T, q)] for the overlay figure.
    """
    header, blocks = split_blocks(lines)
    named = {}
    for name, bl in blocks:
        named.setdefault(name, bl)
    proc = kv(named.get('Procedure', []))
    fpar = kv(named.get('File Parameters', []))
    conf = kv(named.get('Configuration', []))

    # ---------------- segments ----------------
    segments, ramps, cycle = [], [], 0
    for name, bl in blocks:
        if name != 'step' or len(bl) < 4:
            continue
        title, units, data = parse_step(bl)
        bad = {c: units.get(c) for c, u in EXPECTED_UNITS.items() if units.get(c) != u}
        if bad:
            raise ValueError(f"unexpected units in step '{title}': {bad}")
        T, q, t = data['Temperature'], data['Heat Flow (Normalized)'], data['Time']
        seg = {'name': title, 'time': t, 'temperature': T, 'heat_flow_normalized': q}
        m = re.match(r'Ramp\s+([\d.]+)\s*°C/min to\s+([-\d.]+)\s*°C', title)
        if m and T:
            seg['rate'] = float(m.group(1))  # K/min
            seg['target_temperature'] = float(m.group(2))  # °C
            cooling = float(m.group(2)) < T[0]
            seg['segment_type'] = 'ramp_cooling' if cooling else 'ramp_heating'
            if cooling:
                cycle += 1  # a new cycle starts with each cooling ramp
            n_ramp = sum(1 for s in segments if 'rate' in s) + 1
            label = (
                f'{n_ramp}: cycle {max(cycle, 1)} '
                f"{'cooling' if cooling else 'heating'} to {seg['target_temperature']:g} °C"
            )
            ramps.append((label, T, q))
        elif title.startswith('Isothermal'):
            seg['segment_type'] = 'isothermal'
        segments.append(seg)

    if not segments:
        raise ValueError('no [step] data blocks found - not a TRIOS DSC CSV export?')

    # ---------------- TRIOS analyses ----------------
    analyses, pick = [], {}
    ramp_dir = {s['name']: s.get('segment_type') for s in segments}
    for name, bl in blocks:
        if name != 'analysis':
            continue
        rec = parse_analysis(bl)
        step = rec.get('analysed_step', '')
        direction = ramp_dir.get(step.split(' - ', 1)[-1].strip())
        for rname, val, unit in rec['results']:
            analyses.append(
                {
                    'analysed_step': step,
                    'model': rec.get('model'),
                    'result_name': rname,
                    'result_value': val,
                    'result_unit': unit,
                    'details': '; '.join(rec['details']),
                }
            )
            pick.setdefault((direction, rname.lower()), []).append(val)

    results = {}
    mapping = {
        ('ramp_cooling', 'onset x'): 'Ms',
        ('ramp_cooling', 'endset x'): 'Mf',
        ('ramp_heating', 'onset x'): 'As',
        ('ramp_heating', 'endset x'): 'Af',
    }
    for key, qname in mapping.items():
        vals = pick.get(key, [])
        if len(vals) == 1 and vals[0] is not None:
            results[qname] = vals[0]  # °C
    if results:
        results['evaluation_method'] = 'TRIOS tangent onset/endset (copied automatically, verify)'

    # ---------------- metadata ----------------
    date_iso = None
    if fpar.get('Run date'):
        try:
            date_iso = (
                datetime.strptime(fpar['Run date'], '%m/%d/%Y %I:%M:%S %p')
                .replace(tzinfo=ZoneInfo(tz))
                .isoformat()
            )
        except ValueError:
            pass
    mass_mg = number(proc.get('Sample Mass'))
    T_all = [v for s in segments for v in s['temperature'] if not math.isnan(v)]
    heat = {s['rate'] for s in segments if s.get('segment_type') == 'ramp_heating'}
    cool = {s['rate'] for s in segments if s.get('segment_type') == 'ramp_cooling'}
    sample = header.get('Sample name') or proc.get('Sample Name')
    tri_name = re.sub(r'\.csv$', '.tri', csv_name, flags=re.IGNORECASE)

    data = {
        'data_file': csv_name,
        'run_name': sample,
        'operator': header.get('Operator') or proc.get('Operator'),
        'date': date_iso,
        'notes': proc.get('Comments') or None,
        'specimen': {
            'specimen_id': sample,
            'mass': mass_mg * 1e-6 if mass_mg else None,  # kg
        },
        'instrument_settings': {
            'instrument': f"TA Instruments {conf.get('Instrument Name', 'DSC')}",
            'instrument_serial': conf.get('Serial Number'),
            'trios_version': fpar.get('Trios version'),
            'exotherm_direction': conf.get('Exotherm Direction'),
            'pan_type': proc.get('Pan Type'),
            'purge_gas': (conf.get('Gas Selected') or '').split(':')[-1].strip() or None,
            'purge_flow': number(conf.get('Flow Rate')),  # mL/min
            'heating_rate': max(heat) if heat else None,
            'cooling_rate': max(cool) if cool else None,
            'temperature_min': min(T_all) if T_all else None,
            'temperature_max': max(T_all) if T_all else None,
            'number_of_cycles': len([s for s in segments if s.get('segment_type') == 'ramp_cooling']),
            'procedure': header.get('proceduresegments'),
        },
        'measurement': {
            'tri_file': tri_name,
            'segments': segments,
            'trios_analyses': analyses,
        },
        'transformation_results': results,
    }
    return clean(data), ramps


def clean(o):
    """Drop None and empty dicts (NOMAD rejects None for typed quantities)."""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items() if v is not None and v != {}}
    if isinstance(o, list):
        return [clean(v) for v in o]
    return o
