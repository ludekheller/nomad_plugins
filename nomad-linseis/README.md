# nomad-linseis

NOMAD plugin for the **Linseis TMA PT1000LT / PT1600** (thermomechanical analyzer).

## Use

Upload the Linseis text export (`.txt`, header `# Name: …`, `# Measurement date and time: …`,
`# Length: … mm`, then a tab-separated table `Time (s)`, `Delta L (…) (µm)`,
`Delta L Rel. exp (…) (%)`, `Temperature (…) (°C)`). The plugin recognises it by its header
and creates the editable entry `<run>.archive.json` ("TMA (Linseis)") with

* sample name, measurement and export date (Czech or English month names; characters
  damaged by the export such as `z?? 21` are matched tolerantly), initial length,
* applied stress taken from the sample name (`…400MPa`) unless entered,
* the full record and its split into heating / cooling / hold segments (rate, start and end
  temperature per segment; a ramp must change the temperature by at least 5 K),
* plots: relative expansion vs temperature (one line per ramp), temperature and expansion vs
  time, and the explorer (x menu, y on/off buttons, y scale normalisation).

Fill in instrument (PT1000LT / PT1600), specimen, force and the test description in the GUI;
hand-entered values are kept on reprocessing.

## Develop / test

```bash
pip install -e '.[dev]'
pytest -q tests/
```
