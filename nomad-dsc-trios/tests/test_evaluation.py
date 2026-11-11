"""Tangent-method engine on synthetic DSC ramps with known answers."""

import numpy as np
import pytest

from nomad_dsc_trios import evaluation as E

RATE = 10.0  # K/min


def ramp(peaks, cooling, T_from=100.0, T_to=-100.0, base=(0.0004, 0.15), noise=0.0, seed=0):
    """Ramp with Gaussian peaks (T0, sigma, height in W/g) on a sloped baseline; exo up."""
    if not cooling:
        T_from, T_to = T_to, T_from
    n = int(abs(T_to - T_from) / RATE * 60 / 0.1)
    t = np.arange(n) * 0.1
    T = T_from + np.sign(T_to - T_from) * RATE / 60 * t
    q = base[0] * T + base[1]
    for T0, s, h in peaks:
        q += (1 if cooling else -1) * h * np.exp(-0.5 * ((T - T0) / s) ** 2)
    q += noise * np.random.default_rng(seed).standard_normal(n)
    return T, q, t


def gauss_area(s, h):
    return h * s * np.sqrt(2 * np.pi) / (RATE / 60)  # J/g


@pytest.mark.parametrize('cooling', [True, False])
def test_semi_automatic_single_peak(cooling):
    T, q, t = ramp([(-20.0, 8.0, 0.08)], cooling)
    res = E.evaluate_ramp(T, q, t, cooling, windows=[(30.0, -70.0)])
    (pk,) = res.peaks
    # Gaussian on a straight baseline: inflection tangents meet the baseline at T0 -/+ 2 sigma
    onset, end = (-4.0, -36.0) if cooling else (-36.0, -4.0)
    assert pk.start.temperature == pytest.approx(onset, abs=0.3)
    assert pk.end.temperature == pytest.approx(end, abs=0.3)
    assert pk.peak_temperature == pytest.approx(-20.0, abs=0.2)
    assert pk.enthalpy == pytest.approx(gauss_area(8.0, 0.08), rel=0.02)


def test_automatic_two_peaks_and_threshold():
    # R-phase-like first peak, martensite second, and a small bump below the 10 % threshold
    T, q, t = ramp([(30.0, 3.0, 0.05), (-40.0, 5.0, 0.12), (-80.0, 6.0, 0.008)], True, noise=2e-4)
    res = E.evaluate_ramp(T, q, t, True)
    assert [round(pk.peak_temperature) for pk in res.peaks] == [30, -40]  # order of the ramp
    assert res.peaks[0].start.temperature == pytest.approx(36.0, abs=1.0)
    assert res.peaks[1].end.temperature == pytest.approx(-50.0, abs=1.0)
    res5 = E.evaluate_ramp(T, q, t, True, min_height_percent=4)
    assert len(res5.peaks) == 3  # the bump counts with a 4 % threshold


def test_no_peak():
    T, q, t = ramp([], False, noise=1e-4)
    res = E.evaluate_ramp(T, q, t, False)
    assert res.peaks == [] and res.messages
