"""Reader for InfraTec IR records written by the LabVIEW acquisition (.tdms, read with nptdms).

Groups in the file (xx = ROI number, 00, 01 ...):
  ROI_xx                          ROI geometry: [rows, columns, offset, offset] (px)
  ROI_Field                       geometry of the stored temperature field
  Time stamps                     ms (time base of the acquisition PC, not clock time)
  Mean / Max. / Min. Temperature_ROI_xx    one value per frame (°C)
  Temperature profiles_ROI_xx     one channel per frame: mean over the ROI width, per pixel
                                  row along the sample axis (°C)
  Temperature field_ROI_xx        one channel per frame: the full field, flattened (K)
Other groups are listed but not used. Frames whose maximum is below INVALID_BELOW (camera not
yet measuring the sample, e.g. -177 °C) are marked invalid.

`read_ir(path)` returns a plain dict; fields are read only for selected frames, so large
records are fine.
"""

import re

import numpy as np

INVALID_BELOW = -100.0  # °C
STAT_GROUPS = {'mean': 'Mean Temperature_{}', 'max': 'Max. Temperature_{}', 'min': 'Min. Temperature_{}'}


def _channel(group):
    return np.asarray(group.channels()[0][:])


def _stacked(group, frames=None):
    chans = group.channels()
    idx = range(len(chans)) if frames is None else frames
    return np.array([np.asarray(chans[i][:], dtype=float) for i in idx])


def select_frames(n, valid, k, must=()):
    """Up to k frame indices, equally spaced over the valid frames, always including `must`."""
    ok = np.flatnonzero(valid) if valid is not None and valid.any() else np.arange(n)
    pick = set(ok[np.unique(np.linspace(0, len(ok) - 1, min(k, len(ok))).round().astype(int))])
    pick.update(m for m in must if m is not None and 0 <= m < n)
    return sorted(int(i) for i in pick)


def read_ir(path, field_frames=30):
    from nptdms import TdmsFile

    with TdmsFile.open(path) as f:
        groups = {g.name: g for g in f.groups()}
        out = {'groups': list(groups), 'rois': {}}
        if 'Time stamps' in groups:
            ts = _channel(groups['Time stamps']).astype(float)
            out['time_stamp_start_ms'] = float(ts[0]) if ts.size else None
            out['time'] = (ts - ts[0]) / 1000.0 if ts.size else ts
        names = sorted(g for g in groups if re.fullmatch(r'ROI_\d+', g))
        for roi in names:
            geom = _channel(groups[roi]).astype(int).tolist()
            r = {'geometry': geom}
            for k, pattern in STAT_GROUPS.items():
                g = groups.get(pattern.format(roi))
                if g is not None:
                    r[k] = _channel(g).astype(float)
            g = groups.get(f'Temperature profiles_{roi}')
            if g is not None and g.channels():
                r['profiles'] = _stacked(g)
            out['rois'][roi] = r
        n = len(out.get('time', [])) or max((len(r.get('max', [])) for r in out['rois'].values()), default=0)
        if 'time' not in out:
            out['time'] = np.arange(n, dtype=float)
        out['n_frames'] = n

        # valid frames: the camera measures the sample (maximum of any ROI above INVALID_BELOW)
        maxima = [r['max'] for r in out['rois'].values() if 'max' in r and len(r['max']) == n]
        valid = np.max(maxima, axis=0) > INVALID_BELOW if maxima else np.ones(n, bool)
        out['valid'] = valid
        hot = int(np.nanargmax(np.where(valid, np.max(maxima, axis=0), -np.inf))) if maxima else None
        out['hottest_frame'] = hot

        # temperature fields (selected frames only)
        out['fields'] = {}
        for gname, g in groups.items():
            m = re.fullmatch(r'Temperature field_(ROI_\d+)', gname)
            if not m or not g.channels():
                continue
            roi = m.group(1)
            geom = (_channel(groups['ROI_Field']).astype(int).tolist() if 'ROI_Field' in groups
                    else out['rois'].get(roi, {}).get('geometry'))
            frames = select_frames(len(g.channels()), valid[:len(g.channels())], field_frames, must=[hot])
            data = _stacked(g, frames)
            rows, cols = (geom[0], geom[1]) if geom and geom[0] * geom[1] == data.shape[1] else (data.shape[1], 1)
            data = data.reshape(len(frames), rows, cols)
            # Kelvin or °C: compare with the ROI mean of the same frames
            offset = 0.0
            mean = out['rois'].get(roi, {}).get('mean')
            if mean is not None and len(mean) > max(frames):
                ref = mean[frames]
                if np.nanmedian(np.abs(data.mean(axis=(1, 2)) - 273.15 - ref)) < np.nanmedian(
                        np.abs(data.mean(axis=(1, 2)) - ref)):
                    offset = 273.15
            elif np.nanmedian(data) > 150:  # no reference: assume Kelvin as written by the camera
                offset = 273.15
            out['fields'][roi] = {'frames': frames, 'data': data - offset, 'geometry': geom,
                                  'unit_in_file': 'K' if offset else '°C'}
    return out
