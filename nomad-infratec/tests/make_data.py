"""Synthetic InfraTec .tdms with the structure of the LabVIEW acquisition."""
from pathlib import Path

import numpy as np
from nptdms import ChannelObject, GroupObject, RootObject, TdmsWriter


def make(path: Path, frames=40, rows=60, cols=12):
    path.parent.mkdir(parents=True, exist_ok=True)
    t = 9_827_148.0 + np.arange(frames) * 7300.0
    x = np.arange(rows)
    objs = [RootObject(properties={'name': path.stem})]

    def single(name, data):
        return [GroupObject(name), ChannelObject(name, name, np.asarray(data))]

    objs += single('ROI_00', np.array([rows, cols, 10, 20], dtype=np.int16))
    objs += single('ROI_01', np.array([10, cols, 30, 20], dtype=np.int16))
    objs += single('ROI_Field', np.array([rows, cols, 10, 20], dtype=np.int16))
    objs += single('Time stamps', t)
    fields, profiles = [], []
    peak = 400 * np.sin(np.linspace(0, np.pi, frames))  # heating and cooling
    for i in range(frames):
        prof = 25 + peak[i] * np.exp(-((x - rows / 2) / (rows / 4)) ** 2)
        if i < 2:
            prof = np.full(rows, -177.0)  # camera not yet measuring the sample
        profiles.append(prof)
        fields.append(np.repeat(prof[:, None], cols, axis=1) + 273.15)  # field in K
    profiles, fields = np.array(profiles), np.array(fields)
    for roi, sl in (('ROI_00', slice(0, rows)), ('ROI_01', slice(25, 35))):
        p = profiles[:, sl]
        objs += single(f'Mean Temperature_{roi}', p.mean(axis=1))
        objs += single(f'Max. Temperature_{roi}', p.max(axis=1))
        objs += single(f'Min. Temperature_{roi}', p.min(axis=1))
        objs.append(GroupObject(f'Temperature profiles_{roi}'))
        objs += [ChannelObject(f'Temperature profiles_{roi}', f'profile_{i * 1000:08d}', p[i]) for i in range(frames)]
    objs.append(GroupObject('Temperature field_ROI_00'))
    objs += [ChannelObject('Temperature field_ROI_00', f'field_{i * 1000:08d}', fields[i].ravel().astype(np.float32))
             for i in range(frames)]
    with TdmsWriter(str(path)) as w:
        w.write_segment(objs)
    return path, profiles
