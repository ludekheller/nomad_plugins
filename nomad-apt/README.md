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
* **3-D atom map** – sample per ion (up to 8 000 each; minor ions such as Ga complete), on/off
  buttons per ion above the plot (filled = shown), *all on* / *all off*
* **3-D map with cross-sections** – x-z section (4 nm slab) with its at.% profile along depth on
  the left, 3-D map with both section planes, x-y slice (2 nm slab) with at.% profiles along x
  (above) and y (right). Two sliders move the x-y slice in depth and the x-z section in y
  (15 positions each); all panels follow. Profiles from all ions in the slab, points sampled
  (up to 1 500 per ion and slab). Same ion buttons on top. Best viewed full screen (⛶).
* **Voltage history**, **detector hit map**, multiple-hit fraction – when the file has these channels

Without a range file: mass spectrum, explorer (ions per slice), maps of all ions, spectrum vs
depth, evaporation and the 3-D map. The depth profile is also stored in
`results.depth_profile` (for notebooks).

Tests: `pytest -q tests/` (synthetic data from `tests/make_data.py`).
