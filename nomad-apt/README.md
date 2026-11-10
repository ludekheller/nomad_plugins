# nomad-apt

NOMAD plugin for atom probe tomography (CAMECA LEAP ...) at FZU Dept. 18. Needs only numpy.

## Files

One **APT measurement** entry per reconstruction file, `<file stem>.archive.json`. The
reconstruction file is the **only file needed**; everything else is optional and is added to the
entry whenever it is (or later gets) uploaded into the same folder:

| file | role |
|---|---|
| `.apt` `.epos` `.pos` | reconstruction (**required**); same stem in several formats: `.epos` > `.apt` > `.pos` |
| `.xml` (AP Suite experiment export) | entry title = reconstruction name (e.g. `R6043_00450_konec microfrac`), reconstruction comments / author / time, run header: specimen, date, instrument, laser energy and wavelength, temperature, detection rate, start voltage, run comments, outcome, instrument configuration (best effort, text read from the CAMECA ROOT blob) |
| `.hits` `.rhit` `.rraw` | raw data (closed format): linked, size recorded; the one named in the `.xml`, or with the run number |
| `.rrng` `.rng` | ranges: the file whose name starts with the reconstruction name (longest match), otherwise one of the same run, otherwise the only one in the folder (if not named for another run) |

AP Suite exports name the `.apt` files by reconstruction id; the entry file keeps that name,
the title shown in NOMAD comes from the `.xml`. Values typed in by hand are never overwritten.

## Plots (all ions; the 3-D map uses a random sample)

* **Mass spectrum** – log/linear switch, ranges shaded, ion labels at the ranged peaks
* **Composition** – elements in at.% with 2σ counting error, ranged ions
* **Composition profile (depth)** – at.% per depth slice through the whole reconstruction, 2σ
* **Explorer** – depth profile: choose x, switch elements / ions / ions per slice / unranged % on
  and off, optional normalisation
* **2-D maps x-y and x-depth** – projections; menu: all ions, or per element at.% / atoms per cell
* **Mass spectrum vs depth** – log counts (evaporation stability, background)
* **Evaporation vs depth** – ions per slice and unranged fraction
* **3-D atom map** – random 20 000 ions, coloured by ion
* **Voltage history**, **detector hit map**, multiple-hit fraction – when the file has these channels

Without a range file: mass spectrum, explorer (ions per slice), maps of all ions, spectrum vs
depth, evaporation and the 3-D map. The depth profile is also stored in
`results.depth_profile` (for notebooks).

Tests: `pytest -q tests/` (synthetic data from `tests/make_data.py`).
