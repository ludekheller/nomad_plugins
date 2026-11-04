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

### Mercury export added later

The Mercury export is often collected on another PC. Upload the WaveMatrix files first
(e.g. a zip of the test folder); the entry `TestNNN.archive.json` is created with the
WaveMatrix data. Later put the Mercury export **into the same folder** of the upload
(a zip containing the same folder name, or the upload's file browser inside that folder).
The plugin recognises the export, adds it to the existing entry and reprocesses it
(synchronisation, DIC plots). The entry file keeps its name; the displayed name becomes
`TestNNN__<Mercury export name>` unless you changed it. Hand-entered values are kept.
If the export arrives before the WaveMatrix files, it is picked up when they arrive.

Fill in specimen ID, material, processing history and the test description in the GUI and
save; hand-entered values are never overwritten. Raw files keep their original names.

## Develop / test

```bash
pip install -e '.[dev]'
pytest -q tests/
```

`tests/test_plugin.py` needs a real test folder in `tests/data/Test170/` (not in the
repository - research data); without it those tests are skipped. `tests/test_sync.py`
uses synthetic data and always runs.
