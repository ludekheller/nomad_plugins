"""Synchronisation test with synthetic data (runs everywhere, no research data needed)."""

import numpy as np
import pytest


def test_sync_finds_known_shift():
    """Synthetic check: shift a signal by a known amount and recover it."""
    from nomad_thermomech.sync import find_offset

    t = np.arange(0, 600, 0.05)
    f = 1000 * np.clip(np.sin(2 * np.pi * t / 60), 0, None) + 5 * np.sin(t)
    t_other = np.arange(0, 500, 0.0507)
    f_other = np.interp(t_other + 41.237, t, f)
    s = find_offset(t, f, t_other, f_other)
    assert s['offset'] == pytest.approx(41.237, abs=0.01) and s['r'] > 0.999
