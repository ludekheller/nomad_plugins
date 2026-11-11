"""Transformation temperatures from DSC ramps by the tangent method.

Plain numpy/scipy, no NOMAD imports, so it can be used and tested on its own.

Construction (as TRIOS "Onset point" / "Endset point" with tangent type Tangent + Inflection):
  * the ramp is resampled on a uniform temperature grid and smoothed with a Savitzky-Golay filter
    (window given in kelvin); the derivative is the SG derivative with respect to temperature;
  * the signal is oriented so that transformation peaks are positive (exothermic on cooling,
    endothermic on heating, whatever the exotherm direction of the instrument);
  * each peak edge: tangent at the steepest point (inflection) of the flank between the peak maximum
    and an outer baseline point (cursor), intersected with the baseline = tangent to the curve at the
    cursor (TRIOS: onset tangent 'Tangent', transition tangent 'Inflection');
      - semi-automatic: the cursors are given by the user (one window = two cursors per peak);
      - automatic: peaks are local maxima of the curve minus its lower convex hull that are higher than
        `min_height_percent` of the largest peak of the ramp and `noise_factor` x the noise; area at
        least `min_area` J/g; overlapping peaks are split at the minimum between them. The cursor of a
        flank is where the curve becomes straight again beyond the 'knee' (nearest maximum of the
        second derivative outside the inflection): the curvature has dropped to `knee_fraction` of
        that maximum.
  * enthalpy: area between the curve and the baseline, divided by the ramp rate (J/g).

Temperatures are in °C, heat flow in W/g, time in s.
"""

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import find_peaks, savgol_filter

DEFAULTS = dict(sg_window=3.0, sg_order=3, min_height_percent=10.0, noise_factor=5.0, min_area=0.5,
                skip_start=1.0, curvature_window=20.0, knee_fraction=0.1)


@dataclass
class Edge:
    temperature: float  # onset / end (°C)
    inflection: float  # °C
    slope: float  # tangent slope at the inflection (W/g/K, oriented signal)
    tangent: tuple  # (T0, y0): tangent passes through it
    baseline: tuple  # (slope, intercept) of the baseline used


@dataclass
class Peak:
    index: int
    start: Edge  # onset in the direction of the ramp
    end: Edge
    peak_temperature: float
    height: float  # W/g above the baseline
    enthalpy: float  # J/g
    window: tuple  # (T_outer_1, T_outer_2) in the direction of the ramp
    flags: list = field(default_factory=list)


@dataclass
class RampResult:
    cooling: bool
    rate: float  # K/min
    T: np.ndarray  # grid, ascending (°C)
    y: np.ndarray  # smoothed, oriented signal (peaks positive)
    raw: np.ndarray  # oriented signal before smoothing
    baseline: tuple | None  # (slope, intercept) for automatic mode
    noise: float
    peaks: list
    messages: list


def prepare(T, q, t, cooling, exo_up=True, skip_start=1.0):
    """Uniform ascending temperature grid and oriented heat flow; drops the start-up transient.

    The transient is the part of the ramp where the heating/cooling rate has not yet reached 90 %
    of its median value, plus `skip_start` minutes.
    """
    T, q, t = (np.asarray(a, dtype=float) for a in (T, q, t))
    ok = np.isfinite(T) & np.isfinite(q) & np.isfinite(t)
    T, q, t = T[ok], q[ok], t[ok]
    rate = np.gradient(T, t)  # K/s
    nominal = np.median(rate)
    steady = np.flatnonzero(np.abs(rate) >= 0.9 * abs(nominal))
    i0 = steady[0] if steady.size else 0
    i0 = np.searchsorted(t, t[i0] + 60.0 * skip_start)
    T, q, t = T[i0:], q[i0:], t[i0:]
    order = np.argsort(T)
    T, q = T[order], q[order]
    step = np.median(np.abs(np.diff(T)))
    grid = np.arange(T[0], T[-1], step)
    y = np.interp(grid, T, q)
    sign = 1.0 if (cooling == exo_up) else -1.0  # exothermic on cooling / endothermic on heating -> up
    return grid, sign * y, abs(nominal) * 60.0  # K/min


def smooth(y, step, window_k, order):
    n = max(order + 2, int(round(window_k / step)) | 1)
    n += (n % 2 == 0)
    ys = savgol_filter(y, n, order)
    dy = savgol_filter(y, n, order, deriv=1, delta=step)
    return ys, dy


def _intersect(t_T, t_y, t_slope, a, b):
    if abs(t_slope - a) < 1e-15:
        return float('nan')
    # t_y + t_slope (T - t_T) = a T + b
    return (b - t_y + t_slope * t_T) / (t_slope - a)


def edge(T, y, dy, T_outer, T_inner, baseline=None):
    """Onset/end on one flank: inflection tangent between T_outer and T_inner x baseline.

    baseline=None: tangent to the curve at T_outer (TRIOS 'Tangent' at the cursor).
    """
    lo, hi = sorted((T_outer, T_inner))
    sel = np.flatnonzero((T >= lo) & (T <= hi))
    if sel.size < 3:
        return None
    rising = T_inner > T_outer  # signal rises towards the peak maximum when moving to higher T
    k = sel[np.argmax(dy[sel])] if rising else sel[np.argmin(dy[sel])]
    if baseline is None:
        j = int(np.argmin(np.abs(T - T_outer)))
        a = dy[j]
        b = y[j] - a * T[j]
    else:
        a, b = baseline
    Tx = _intersect(T[k], y[k], dy[k], a, b)
    return Edge(temperature=float(Tx), inflection=float(T[k]), slope=float(dy[k]),
                tangent=(float(T[k]), float(y[k])), baseline=(float(a), float(b)))


def _area(T, y, line, lo, hi, rate_k_min):
    sel = (T >= lo) & (T <= hi)
    if sel.sum() < 2 or not rate_k_min:
        return float('nan')
    a, b = line
    return float(np.trapezoid(y[sel] - (a * T[sel] + b), T[sel]) / (rate_k_min / 60.0))


def _make_peak(index, T, y, dy, lo, hi, cooling, rate, baseline=None):
    """Peak between outer points lo < hi (°C)."""
    sel = np.flatnonzero((T >= lo) & (T <= hi))
    if sel.size < 5:
        return None
    if baseline is None:  # area: straight line between the curve at the two outer points
        ja, jb = (int(np.argmin(np.abs(T - v))) for v in (lo, hi))
        a = (y[jb] - y[ja]) / (T[jb] - T[ja])
        line = (a, y[ja] - a * T[ja])
    else:
        line = baseline
    m = sel[np.argmax(y[sel] - (line[0] * T[sel] + line[1]))]  # largest distance from the baseline
    left = edge(T, y, dy, lo, T[m], baseline)
    right = edge(T, y, dy, hi, T[m], baseline)
    if left is None or right is None:
        return None
    height = float(y[m] - (line[0] * T[m] + line[1]))
    flags = []
    for e in (left, right):
        if not lo - 1e-9 <= e.temperature <= hi + 1e-9:
            flags.append('tangent intersection outside the window')
    start, end = (right, left) if cooling else (left, right)  # direction of the ramp
    window = (hi, lo) if cooling else (lo, hi)
    return Peak(index=index, start=start, end=end, peak_temperature=float(T[m]), height=height,
                enthalpy=_area(T, y, line, lo, hi, rate), window=window, flags=flags)


def evaluate_ramp(T, q, t, cooling, exo_up=True, windows=None, **params):
    """Peaks of one ramp. windows: list of (T1, T2) per peak (semi-automatic), else automatic."""
    p = {**DEFAULTS, **{k: v for k, v in params.items() if v is not None}}
    grid, raw, rate = prepare(T, q, t, cooling, exo_up, p['skip_start'])
    step = grid[1] - grid[0]
    y, dy = smooth(raw, step, p['sg_window'], int(p['sg_order']))
    noise = float(1.4826 * np.median(np.abs((raw - y) - np.median(raw - y))))
    messages, peaks = [], []

    if windows:
        for i, (a, b) in enumerate(windows, 1):
            lo, hi = sorted((float(a), float(b)))
            if lo < grid[0] or hi > grid[-1]:
                messages.append(f'window {a:g}..{b:g} °C partly outside the evaluated ramp '
                                f'({grid[0]:.1f}..{grid[-1]:.1f} °C)')
            pk = _make_peak(i, grid, y, dy, max(lo, grid[0]), min(hi, grid[-1]), cooling, rate)
            if pk is None:
                messages.append(f'window {a:g}..{b:g} °C: too few points')
            else:
                peaks.append(pk)
        peaks.sort(key=lambda pk: -pk.peak_temperature if cooling else pk.peak_temperature)
        for i, pk in enumerate(peaks, 1):
            pk.index = i
        return RampResult(cooling, rate, grid, y, raw, None, noise, peaks, messages)

    peaks, base = _auto(grid, y, dy, raw, noise, p, cooling, rate, messages)
    return RampResult(cooling, rate, grid, y, raw, base, noise, peaks, messages)


def lower_hull(x, y):
    """Indices of the lower convex hull of the points (x ascending)."""
    pts = []
    for i in range(len(x)):
        while len(pts) >= 2:
            i1, i2 = pts[-2], pts[-1]
            if (x[i2] - x[i1]) * (y[i] - y[i1]) - (y[i2] - y[i1]) * (x[i] - x[i1]) <= 0:
                pts.pop()
            else:
                break
        pts.append(i)
    return np.array(pts)


def _auto(grid, y, dy, raw, noise, p, cooling, rate, messages):
    """Automatic peaks and cursors.

    Detection on the curve minus its lower convex hull. For each peak the outer cursor of each flank
    is where the curve becomes straight again beyond the 'knee' (largest curvature outside the
    inflection): the second derivative has dropped below `knee_fraction` of its value at the knee.
    The edge is then constructed as in semi-automatic mode (tangent to the curve at the cursor).
    """
    hull = lower_hull(grid, y)
    c = y - np.interp(grid, grid[hull], y[hull])
    top = c.max()
    min_h = max(p['min_height_percent'] / 100.0 * top, p['noise_factor'] * noise)
    idx, _ = find_peaks(c, height=min_h, prominence=min_h / 2)
    if idx.size == 0:
        messages.append('no peak above the thresholds')
        return [], None
    step = grid[1] - grid[0]
    bounds = [0] + [int(a + np.argmin(c[a:b + 1])) for a, b in zip(idx, idx[1:])] + [len(grid) - 1]
    peaks = []
    for n, k in enumerate(idx):
        v0, v1 = bounds[n], bounds[n + 1]
        half = np.flatnonzero(c[v0:v1 + 1] >= c[k] / 2)
        fwhm = (half[-1] - half[0]) * step if half.size else 10.0
        w2 = float(np.clip(0.5 * fwhm, 2 * p['sg_window'], p['curvature_window']))
        m = max(5, int(round(w2 / step)) | 1)
        d2 = savgol_filter(raw, m + (m % 2 == 0), 3, deriv=2, delta=step)
        cursors = []
        for side in (-1, 1):
            if side < 0:
                seg = np.arange(v0, k + 1)
                infl = seg[np.argmax(dy[seg])]
                out = np.arange(v0, infl + 1)
            else:
                seg = np.arange(k, v1 + 1)
                infl = seg[np.argmin(dy[seg])]
                out = np.arange(infl, v1 + 1)
            edge_pts = m // 2  # SG derivatives are unreliable within half a window of the data ends
            out = out[(out >= edge_pts) & (out <= len(grid) - 1 - edge_pts)]
            if out.size < 3:
                cursors.append(int(v0 if side < 0 else v1))
                continue
            walk = out[::-1] if side < 0 else out  # outward from the inflection
            local, _ = find_peaks(d2[walk], height=0)
            knee = walk[local[0]] if local.size else walk[np.argmax(d2[walk])]  # nearest bend
            j = knee
            limit = walk[-1]
            while j != limit and d2[j] > p['knee_fraction'] * d2[knee]:
                j += side
            cursors.append(int(j))
        lo, hi = grid[cursors[0]], grid[cursors[1]]
        pk = _make_peak(0, grid, y, dy, lo, hi, cooling, rate)
        if pk is None:
            continue
        if pk.enthalpy < p['min_area']:
            messages.append(f'peak at {pk.peak_temperature:.1f} °C ignored: area {pk.enthalpy:.2f} J/g '
                            f'< {p["min_area"]:g} J/g')
            continue
        if cursors[0] <= m // 2 or cursors[1] >= len(grid) - 1 - m // 2:
            pk.flags.append('no baseline beyond the peak within the evaluated ramp: cursor at the end of the data')
        peaks.append(pk)
    peaks.sort(key=lambda pk: -pk.peak_temperature if cooling else pk.peak_temperature)
    for i, pk in enumerate(peaks, 1):
        pk.index = i
    return peaks, None


def summary(result):
    """Overall start of the first and end of the last peak in the direction of the ramp."""
    if not result.peaks:
        return None, None
    return result.peaks[0].start.temperature, result.peaks[-1].end.temperature
