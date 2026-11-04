"""Time synchronisation of two records via a signal they share (force).

The two acquisition PCs have independent clocks (they differed by ~65 s for Test170),
so the offset is found from the data: normalised cross-correlation of the force
recorded by both systems, coarse search over all plausible lags, then refinement.
"""

import numpy as np


def _corr_at(t_ref, f_ref, t_oth, f_oth, grid, offset):
    """Pearson r between ref and other(shifted by offset) on a common grid."""
    a = np.interp(grid, t_ref, f_ref, left=np.nan, right=np.nan)
    b = np.interp(grid, t_oth + offset, f_oth, left=np.nan, right=np.nan)
    ok = ~(np.isnan(a) | np.isnan(b))
    n = int(ok.sum())
    if n < 10:
        return np.nan, n
    a, b = a[ok], b[ok]
    sa, sb = a.std(), b.std()
    if sa == 0 or sb == 0:
        return np.nan, n
    return float(((a - a.mean()) * (b - b.mean())).mean() / (sa * sb)), n


def find_offset(t_ref, f_ref, t_oth, f_oth, min_overlap=0.2):
    """Offset (s) such that `t_oth + offset` is on the time axis of `t_ref`.

    Returns dict(offset, r, n_points, scale, intercept). `scale`/`intercept` relate the
    two force signals after alignment: f_ref = scale * f_oth + intercept.
    """
    t_ref, f_ref, t_oth, f_oth = (np.asarray(x, float) for x in (t_ref, f_ref, t_oth, f_oth))
    m1, m2 = ~np.isnan(f_ref), ~np.isnan(f_oth)
    t_ref, f_ref, t_oth, f_oth = t_ref[m1], f_ref[m1], t_oth[m2], f_oth[m2]
    shorter = min(t_ref[-1] - t_ref[0], t_oth[-1] - t_oth[0])
    lo = t_ref[0] - t_oth[-1] + min_overlap * shorter
    hi = t_ref[-1] - t_oth[0] - min_overlap * shorter

    best = (-np.inf, None)
    for dt_grid, step, lags in (
        (1.0, 1.0, np.arange(lo, hi, 1.0)),  # coarse: every lag, 1 s
        (0.1, 0.05, None),  # medium: +-2 s around best
        (0.02, 0.002, None),  # fine: +-0.1 s around best
    ):
        if lags is None:
            c = best[1]
            half = 2.0 if step == 0.05 else 0.1
            lags = np.arange(c - half, c + half + step / 2, step)
        grid = np.arange(t_ref[0], t_ref[-1], dt_grid)
        local = (-np.inf, None)
        for off in lags:
            r, _ = _corr_at(t_ref, f_ref, t_oth, f_oth, grid, off)
            if np.isfinite(r) and r > local[0]:
                local = (r, off)
        if local[1] is None:
            raise ValueError('no overlap found between the two records')
        best = local

    off = best[1]
    grid = np.arange(t_ref[0], t_ref[-1], 0.02)
    r, n = _corr_at(t_ref, f_ref, t_oth, f_oth, grid, off)
    b = np.interp(t_ref, t_oth + off, f_oth, left=np.nan, right=np.nan)
    ok = ~np.isnan(b)
    scale, intercept = np.polyfit(b[ok], f_ref[ok], 1)
    return {'offset': float(off), 'r': float(r), 'n_points': int(ok.sum()),
            'scale': float(scale), 'intercept': float(intercept)}
