# nomad-walterbai

NOMAD plugin for thermomechanical tests on the **Walter+Bai (UTTRMO)** and **MITTER**
machines (same control software and record format), optionally with **1D DIC**.

## Use

Upload into one folder of a project

* the machine record `<name>` - a text file **without extension**, tab-separated, header
  `Time / s<TAB>Position / mm<TAB>Force / N<TAB>...` (recognised by this header line), and
* optionally the 1D DIC export `<name>_dic.csv` (`;`-separated, header
  `Fram ID;Absolute Timestamp;...` with `Tnnn - Displacement [mm]`, `Tnnn - Position in X/Y [mm]`).

The plugin creates the editable entry `<name>.archive.json` ("Walter+Bai / MITTER test").
The machine is detected from the record's columns (`Water_Temp_Down` -> MITTER,
`Position_laser_sensor` -> Walter+Bai) and stored in `testing_machine`; it can be changed by
hand. MITTER records come without DIC.
The DIC export can also be added later into the same folder; the entry is then updated.

The entry contains

* the machine record (time shifted to start at zero; position, force, resistance, base and
  water temperature, strain, stress, cycle numbers, Joule-heating voltage/current/power/
  resistance); channels with missing values (NaN, inf) are shown in the explorer only;
* the DIC record (time from zero): tracked points with their first-frame positions, one
  **local strain per pair of neighbouring points**
  `100 * (d_b,i - d_a,i) / sqrt((x_b,0 - x_a,0)^2 + (y_b,0 - y_a,0)^2)`,
  the segment positions along the specimen, and the **gauge strain** between the first and
  the last point; the machine stress interpolated onto the DIC time;
* plots: **DIC strain map** (time on x, position along the specimen on y, colour = local
  strain), stress vs strain (machine strain and DIC gauge strain), local strains vs time,
  and the explorer (x menu, y on/off buttons, y scale normalisation).

Both records are assumed synchronised (same start); only the time offsets are removed.
Fill in specimen, test type and description in the GUI; hand-entered values are kept.

## Develop / test

```bash
pip install -e '.[dev]'
pytest -q tests/
```
