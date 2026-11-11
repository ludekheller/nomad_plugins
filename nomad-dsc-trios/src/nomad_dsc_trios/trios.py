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
            'showlegend': True,  # NOMAD's default template hides legends
            'legend': {'title': {'text': 'ramp'}},
        },
    }


def add_segment(segments, ramps, cycle, title, t, T, q):
    """Append one procedure step as a segment (ramps also go to `ramps`); returns the cycle count."""
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
    return cycle


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
        cycle = add_segment(segments, ramps, cycle, title, t, T, q)

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


# ------------------------------------------------------------------ TRIOS JSON export
JSON_SCHEMA_MARK = 'TRIOSJSONExportSchema'
JSON_COLUMNS = {'Time': ('Time_s', 's'), 'Temperature': ('Temperature_°C', '°C'),
                'Heat Flow (Normalized)': ('Heat Flow (Normalized)_W/g', 'W/g')}
# channels offered in the x/y explorer plot (if present in the export): key -> axis label
EXPLORER_VARIABLES = [
    ('Time_s', 'Time (s)'),
    ('Step time_s', 'Step time (s)'),
    ('Temperature_°C', 'Temperature (°C)'),
    ('Set Point Temperature_°C', 'Set point temperature (°C)'),
    ('Sample Sensor Temperature_°C', 'Sample sensor temperature (°C)'),
    ('Heat Flow (Normalized)_W/g', 'Heat flow (W/g)'),
    ('Heat Flow_µW', 'Heat flow (µW)'),
    ('Heat Capacity (Normalized)_J/(g.°C)', 'Heat capacity (J/(g·°C))'),
    ('Delta T_µV', 'Delta T (µV)'),
]


def _value(q, unit=None):
    """{'Value': x, 'Unit': {'Name': u}} -> x (checks the unit if given)."""
    if not isinstance(q, dict) or q.get('Value') is None:
        return None
    if unit and (q.get('Unit') or {}).get('Name') not in (None, unit):
        raise ValueError(f"unexpected unit {q['Unit']} (expected {unit})")
    return _round(q['Value'])


def _round(x, digits=7):
    """TRIOS stores settings as float32 (99.2 -> 99.19999694824219): keep 7 significant digits."""
    x = float(x)
    return float(f'{x:.{digits}g}') if x else x


def read_trios_json(doc, json_name, tz='Europe/Prague'):
    """Parse a TRIOS JSON export (TRIOS >= 5.8, schema TRIOSJSONExportSchema).

    Same output as `read_trios_csv` plus the number of TRIOS analyses and the channels for the
    explorer plot: (data, ramps, n_analyses, explorer_groups).
    Uses the 'Processed' results (TRIOS
    'Latest') if present, else 'Original'. Each results step becomes one segment.
    """
    if JSON_SCHEMA_MARK not in str((doc.get('Schema') or {}).get('Url', '')):
        raise ValueError('not a TRIOS JSON export')
    results_all = doc.get('Results') or {}
    res = results_all.get('Processed') or results_all.get('Original')
    if not res:
        raise ValueError('no Results in the TRIOS JSON export')
    headers = res.get('ColumnHeaders') or {}
    for name, (key, unit) in JSON_COLUMNS.items():
        if key not in headers:
            raise ValueError(f'column {key!r} missing in the TRIOS JSON export')
        got = (headers[key].get('Unit') or {}).get('Name')
        if got != unit:
            raise ValueError(f'unexpected unit for {name}: {got} (expected {unit})')

    kt, kT, kq = (JSON_COLUMNS[c][0] for c in ('Time', 'Temperature', 'Heat Flow (Normalized)'))
    ex_keys = [k for k, _ in EXPLORER_VARIABLES if k in headers]
    rows_by_step, extra_by_step = {}, {}
    for row in res.get('Rows') or []:
        t, T, q = row.get(kt), row.get(kT), row.get(kq)
        if t is None or T is None or q is None:
            continue
        sid = row.get('Results Step Id')
        cols = rows_by_step.setdefault(sid, ([], [], []))
        cols[0].append(float(t)), cols[1].append(float(T)), cols[2].append(float(q))
        ex = extra_by_step.setdefault(sid, {k: [] for k in ex_keys})
        for k in ex_keys:
            v = row.get(k)
            ex[k].append(math.nan if v is None else float(v))

    segments, ramps, cycle, explorer = [], [], 0, []
    for step in res.get('ResultsSteps') or []:
        t, T, q = rows_by_step.get(step.get('Id'), ([], [], []))
        if not T:
            continue
        name = (step.get('Name') or '').strip()
        cycle = add_segment(segments, ramps, cycle, name, t, T, q)
        explorer.append((f'{len(segments)}: {name}', extra_by_step.get(step.get('Id'), {})))
    if not segments:
        raise ValueError('no data rows in the TRIOS JSON export')

    # TRIOS analyses (Onset point, Endset point ...): kept as records; onset/endset of a single
    # analysis per ramp direction is copied to Ms/Mf/As/Af like for CSV exports
    seg_type = {s['name']: s.get('segment_type') for s in segments}
    trios_analyses, pick = [], {}
    for a in doc.get('Analyses') or []:
        inputs = a.get('Inputs') or {}
        step = (((inputs.get('X1') or {}).get('ResultsStep') or {}).get('Name') or '').strip()
        details = []
        for k, v in inputs.items():
            if k in ('X1', 'Y1') or not isinstance(v, dict):
                continue
            val = v.get('Value')
            if isinstance(val, dict):
                num = val.get('Value')
                num = _round(num, 6) if isinstance(num, (int, float)) else num
                val = f"{num} {(val.get('Unit') or {}).get('Name', '')}".strip()
            details.append(f'{k}: {val}')
        for oname, out in (a.get('Outputs') or {}).items():
            val = out.get('Value') if isinstance(out, dict) else None
            if isinstance(val, dict):
                value, unit = val.get('Value'), (val.get('Unit') or {}).get('Name')
            else:
                value, unit = val, None
            if not isinstance(value, (int, float)):
                continue
            trios_analyses.append({'analysed_step': step, 'model': (a.get('Type') or {}).get('Name'),
                                   'result_name': oname, 'result_value': _round(float(value), 6),
                                   'result_unit': unit, 'details': '; '.join(details)})
            if unit == '°C':
                pick.setdefault((seg_type.get(step), oname.lower()), []).append(_round(float(value), 6))
    results = {}
    for key, qname in {('ramp_cooling', 'onset x'): 'Ms', ('ramp_cooling', 'endset x'): 'Mf',
                       ('ramp_heating', 'onset x'): 'As', ('ramp_heating', 'endset x'): 'Af'}.items():
        vals = pick.get(key, [])
        if len(vals) == 1:
            results[qname] = vals[0]
    if results:
        results['evaluation_method'] = 'TRIOS tangent onset/endset (copied automatically, verify)'

    sample = doc.get('Sample') or {}
    proc = doc.get('Procedure') or {}
    conf = ((proc.get('Configuration') or {}).get('InstrumentConfigurations') or [{}])[0]
    analyses = doc.get('Analyses') or []

    date_iso = None
    if doc.get('StartTime'):
        try:
            dt = datetime.fromisoformat(doc['StartTime'])
            date_iso = (dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo(tz))).isoformat()
        except ValueError:
            pass
    mass_mg = _value(sample.get('Mass'), 'mg')
    gas = next((v for k, v in conf.items() if k.startswith('Gas') and k.endswith('Type') and v), None)
    flow = conf.get('FlowRate') or {}
    flow_ml_min = None
    if flow.get('Value') is not None:
        u = (flow.get('Unit') or {}).get('Name')
        flow_ml_min = _round(float(flow['Value']) * (60 if u == 'mL/s' else 1))
    T_all = [v for s in segments for v in s['temperature']]
    heat = {s['rate'] for s in segments if s.get('segment_type') == 'ramp_heating'}
    cool = {s['rate'] for s in segments if s.get('segment_type') == 'ramp_cooling'}
    operators = ', '.join(o.get('Name', '') for o in doc.get('Operators') or [] if o.get('Name')) or None
    instrument = conf.get('Type') or conf.get('Name') or 'DSC'
    if not instrument.startswith('DSC'):
        raise ValueError(f'not a DSC export (instrument {instrument})')

    data = {
        'data_file': json_name,
        'run_name': sample.get('Name'),
        'operator': operators,
        'date': date_iso,
        'specimen': {
            'specimen_id': sample.get('Name'),
            'mass': mass_mg * 1e-6 if mass_mg else None,  # kg
        },
        'instrument_settings': {
            'instrument': f"TA Instruments {conf.get('Name') or instrument}",
            'instrument_serial': conf.get('SerialNumber'),
            'exotherm_direction': conf.get('ExothermDirection'),
            'pan_type': sample.get('PanType'),
            'purge_gas': gas,
            'purge_flow': flow_ml_min,  # mL/min
            'heating_rate': max(heat) if heat else None,
            'cooling_rate': max(cool) if cool else None,
            'temperature_min': min(T_all),
            'temperature_max': max(T_all),
            'number_of_cycles': len([s for s in segments if s.get('segment_type') == 'ramp_cooling']),
            'procedure': ' | '.join(s.get('Name', '').strip() for s in proc.get('Steps') or []),
        },
        'measurement': {
            'tri_file': re.sub(r'\.(json\.gz|json|gz)$', '.tri', json_name, flags=re.IGNORECASE),
            'segments': segments,
            'trios_analyses': trios_analyses,
        },
        'transformation_results': results,
    }
    return clean(data), ramps, len(analyses), explorer
