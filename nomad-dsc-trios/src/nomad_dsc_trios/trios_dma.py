"""Reader for TA Instruments TRIOS JSON exports of DMA runs (DMA 850 ...).

`read_trios_dma_json(doc, name)` returns (data, explorer_groups, explorer_variables):
  data      plain dict in the layout of the `DMA_TRIOS` section (schema units)
  explorer  all numeric channels per results step, for the x/y explorer plot
The DMA can run very different tests (stress/strain ramps, iso-stress temperature ramps,
oscillation sweeps ...); every results step becomes a segment with the channels that exist.
"""

import math
from datetime import datetime
from zoneinfo import ZoneInfo

from nomad_dsc_trios.trios import JSON_SCHEMA_MARK, _round, _value, clean

# segment quantity -> (column key in the export, unit); taken if present with this unit
SEGMENT_COLUMNS = {
    'time': ('Time_s', 's'),
    'temperature': ('Temperature_°C', '°C'),
    'temperature_set_point': ('Temperature set point_°C', '°C'),
    'strain': ('Strain_%', '%'),
    'stress': ('Stress_MPa', 'MPa'),
    'force': ('Force_N', 'N'),
    'displacement': ('Displacement_mm', 'mm'),
    'length': ('Length_mm', 'mm'),
    'modulus': ('Modulus_MPa', 'MPa'),
    'storage_modulus': ('Storage modulus_MPa', 'MPa'),
    'loss_modulus': ('Loss modulus_MPa', 'MPa'),
    'tan_delta': ('Tan(delta)', None),
    'frequency': ('Frequency_Hz', 'Hz'),
    'complex_modulus': ('Complex modulus_MPa', 'MPa'),
    'phase_angle': ('Phase angle_°', '°'),
    'oscillation_stress': ('Oscillation stress_MPa', 'MPa'),
    'oscillation_strain': ('Oscillation strain_%', '%'),
}


def _header_unit(h):
    return (h.get('Unit') or {}).get('Name')


def read_trios_dma_json(doc, json_name, tz='Europe/Prague'):
    if JSON_SCHEMA_MARK not in str((doc.get('Schema') or {}).get('Url', '')):
        raise ValueError('not a TRIOS JSON export')
    proc = doc.get('Procedure') or {}
    conf = ((proc.get('Configuration') or {}).get('InstrumentConfigurations') or [{}])[0]
    instrument = conf.get('Type') or ''
    if not instrument.upper().startswith('DMA'):
        raise ValueError(f'not a DMA export (instrument {instrument or "unknown"})')
    results_all = doc.get('Results') or {}
    res = results_all.get('Processed') or results_all.get('Original')
    if not res:
        raise ValueError('no Results in the TRIOS JSON export')
    headers = res.get('ColumnHeaders') or {}

    numeric = [k for k, h in headers.items() if h.get('ValueType') == 'Number']
    seg_cols = {q: key for q, (key, unit) in SEGMENT_COLUMNS.items()
                if key in headers and (unit is None or _header_unit(headers[key]) == unit)}
    by_step = {}
    for row in res.get('Rows') or []:
        cols = by_step.setdefault(row.get('Results Step Id'), {k: [] for k in numeric})
        for k in numeric:
            v = row.get(k)
            cols[k].append(math.nan if v is None else float(v))

    segments, explorer = [], []
    for step in res.get('ResultsSteps') or []:
        cols = by_step.get(step.get('Id'))
        if not cols or not any(len(v) for v in cols.values()):
            continue
        name = (step.get('Name') or '').strip()
        seg = {'name': name}
        for q, key in seg_cols.items():
            vals = cols[key]
            if vals and all(math.isfinite(v) for v in vals):  # incomplete channels stay in the explorer only
                seg[q] = vals
        segments.append(seg)
        explorer.append((f'{len(segments)}: {name}', cols))
    if not segments:
        raise ValueError('no data rows in the TRIOS JSON export')

    variables = []
    for k in numeric:
        h = headers[k]
        unit = _header_unit(h)
        label = h.get('DisplayName') or k
        variables.append((k, f'{label} ({unit})' if unit else label))

    date_iso = None
    if doc.get('StartTime'):
        try:
            dt = datetime.fromisoformat(doc['StartTime'])
            date_iso = (dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo(tz))).isoformat()
        except ValueError:
            pass
    geo = conf.get('Geometry') or {}
    sample = doc.get('Sample') or {}
    operators = ', '.join(o.get('Name', '') for o in doc.get('Operators') or [] if o.get('Name')) or None
    notes = (geo.get('Notes') or '').strip() or None

    data = {
        'data_file': json_name,
        'run_name': sample.get('Name'),
        'operator': operators,
        'date': date_iso,
        'specimen': {
            'specimen_id': sample.get('Name'),
            'clamp': geo.get('Name'),
            'length': _value(geo.get('Length'), 'mm'),
            'diameter': _value(geo.get('Diameter'), 'mm'),
            'width': _value(geo.get('Width'), 'mm'),
            'thickness': _value(geo.get('Thickness'), 'mm'),
            'geometry_notes': notes,
        },
        'instrument_settings': {
            'instrument': f"TA Instruments {instrument}",
            'instrument_serial': conf.get('SerialNumber'),
            'temperature_option': conf.get('TemperatureOption'),
            'procedure_name': proc.get('Name'),
            'procedure_steps': [(s.get('Name') or '').strip() for s in proc.get('Steps') or []] or None,
        },
        'segments': segments,
    }
    for k in ('length', 'diameter', 'width', 'thickness'):
        v = data['specimen'][k]
        data['specimen'][k] = _round(v) if v else None
    return clean(data), explorer, variables
