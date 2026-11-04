# nomad-thermomech

NOMAD plugin for thermomechanical tests on shape memory alloys recorded with
Instron WaveMatrix (ElectroPuls E10000) and Mercury RT DIC, with IR temperature.

## Use

Upload **one folder per test** containing

* the WaveMatrix files of the test: `TestNNN.log`, `TestNNN.Stop.csv` (or
  `TestNNN.steps.tracking.csv`), `TestNNN.steps.trends.csv`, `TestNNN.specimen.txt`,
  `TestNNN.itr_wma`, `TestNNN.im_gpf`
* the Mercury RT export (`*.csv`, `;`-separated, header `Frame ID;Absolute Timestamp;...`)

The plugin recognises `TestNNN.log` and creates the editable entry
`<folder>/TestNNN__<Mercury export name>.archive.json`. It contains:

* test metadata from the log (method, start/end, status, frame serial, software versions),
  specimen cross-section (`specimen.txt`) and DIC gauge length (Mercury),
* the full WaveMatrix record (time, step, loop, position, load, displacement, stress,
  strain from position, temperature, DIC strain received via the analogue input),
* the Mercury record (extensometer length, strain, stress, temperature, force) on its own
  time axis **and** on the WaveMatrix time axis,
* the synchronisation: the two PCs have independent clocks, so the time offset is found
  by normalised cross-correlation of the force recorded by both systems
  (offset, correlation, force scale/intercept; PC-clock offset kept for information),
* the per-step/loop summary from `steps.trends.csv`,
* plots: stress vs DIC strain (one line per loop), stress and temperature vs time,
  strain vs time (DIC and from position), and a synchronisation check (both forces).

Fill in specimen ID, material, processing history and the test description in the GUI and
save; hand-entered values are never overwritten. Raw files keep their original names.

## Develop / test

```bash
pip install -e '.[dev]'
pytest -q tests/
```

`tests/data/Test170/` is a real example test (NiTi superelastic cycling, 20 loops:
WaveMatrix Test170.* + Mercury export R19_...). `tests/test_sync.py` uses synthetic data.
