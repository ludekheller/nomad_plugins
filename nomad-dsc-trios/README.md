# nomad-dsc-trios

(TA Instruments TRIOS: DSC and DMA.)

NOMAD plugin for DSC measurements on shape memory alloys exported from
TA Instruments TRIOS (DSC 2500): CSV export or TRIOS JSON export (TRIOS >= 5.8).

## What it does

* **Upload a TRIOS DSC `.csv` or TRIOS JSON `.json`** (optionally with the `.tri`) to a
  NOMAD project. The plugin recognises it and creates the editable DSC entry
  `<run>.archive.json`.
* TRIOS JSON (File -> Export, or automatic export at the end of each run, or batch export of
  old files) follows TA's public schema (TRIOSJSONExportSchema). The plugin reads the
  'Processed' results (else 'Original'), sample, operator, start time, instrument
  configuration and procedure. TRIOS onset/endset analyses inside the JSON are read like in
  the CSV export and copied to Ms/Mf/As/Af (one analysis per ramp direction).
* TRIOS JSON files are large (~56 MB per run). Upload them gzip-compressed as
  `<run>.json.gz` (~6 MB; 7-Zip -> Add to archive -> format gzip, or `gzip -k <run>.json`).
  The plugin reads `.json.gz` directly; a `.zip` does not help because NOMAD unpacks it.
  In Jupyter: `json.load(gzip.open(path, 'rt', encoding='utf-8-sig'))`.
* If both `<run>.csv` and `<run>.json` are uploaded, they share one entry
  (`<run>.archive.json`, data from the file that arrived first).
* The DSC entry (`DSC (SMA, TRIOS)`) reads the CSV: instrument settings, procedure,
  sample mass, every procedure step as a segment with its own plot, the TRIOS
  onset/endset analyses, Ms/Mf/As/Af (when unambiguous), and an overlay plot of all
  ramps on the entry page.
* Fill in the specimen description (material, composition, processing history ...)
  in the GUI and save. Values typed in by hand are never overwritten; only empty
  fields are filled from the file. Segments and plots are always rebuilt from the file.
* A DSC entry can also be created by hand (NEW ENTRY -> DSC (SMA, TRIOS)) and a CSV
  attached to `data_file`.
* The entry list shows the run (sample) name instead of the file name.
* **Explorer plot** ("Explorer (choose x and y)"): menu "x" picks the x variable; click
  legend entries to show/hide y variables (several at once); menu "y scale" switches between
  raw values, normalised by max |value| (0…1, or −1…1 with negative values) and min–max
  (0…1). From a TRIOS JSON export: time, step time, temperature, set point, sample sensor
  temperature, heat flow (W/g and µW), heat capacity, delta T; from a CSV: time, temperature,
  heat flow.

## Transformation temperatures: tangent method

Section **evaluation** of a DSC entry, field **mode**:

* **off** (default): nothing is computed. Ms/Mf/As/Af come from the TRIOS analyses or are typed in.
* **semi-automatic**: add one **window** per peak (ramp cooling/heating, T1, T2 = baseline points on
  both sides of the peak, like the two TRIOS cursors) and save.
* **automatic**: the plugin finds the peaks and the baseline points itself. The windows it used are
  written into **windows**; switch to semi-automatic to correct one of them.

Buttons in the evaluation section: **Apply to all DSC curves in this folder** (evaluates all curves
that share this curve's folder settings again), **Edit the automatic windows** (switches to semi-automatic with the
windows found automatically) and **Use the folder settings** (empties this entry's parameters and
windows so that the folder settings apply). In the folder settings entry: **Apply to all DSC curves in
this folder** (saves and evaluates all DSC entries of the folder and its sub-folders again).

Construction (as TRIOS onset/endset with tangent types Tangent + Inflection): Savitzky-Golay smoothing
and derivative on a uniform temperature grid; per flank the tangent at the steepest point
(inflection) is intersected with the tangent to the curve at the baseline point. Automatic peaks:
height >= `min_height_percent` (default 10 %) of the largest peak and >= `noise_factor` x noise,
area >= `min_area` (0.5 J/g); the baseline point is where the curve becomes straight again beyond
the peak. All parameters are fields of the section; the values used are stored in
`parameters_used`. **cycle** (default 1) selects the cooling ramp and the following heating ramp.

Results: overall **Ms** = start of the first cooling peak, **Mf** = end of the last cooling peak,
**As/Af** the same on heating; **Ms1/Mf1 ... Ms3/Mf3, As1/Af1 ... As3/Af3** for the single peaks in
the order of the ramp; peak temperature of the largest peak and the total enthalpy per ramp; the
peak list with flags; the plot *Evaluation (tangent method)* with baselines, tangents and points.
Values are stored rounded to 0.01 °C / 0.01 J/g. Values typed in by hand are never overwritten
(bookkeeping in `auto_filled`); Rs/Rf are left to you.

**Whole folders**: the first DSC curve uploaded into a folder creates `dsc_evaluation.archive.json`
there (mode off, all parameters with their defaults) unless a settings file exists in that folder or
above; exactly one per folder, an existing file is never overwritten. It can also be uploaded by hand
(see `examples/`). The settings entry always shows every parameter with the value used. Its settings (mode, cycle, parameters, windows) apply to all DSC entries in this folder
and its sub-folders; fields set in a single entry win. After changing it, reprocess the project
(`nomad admin uploads process <project id>` on the server).

The settings entry shows a plot *What the parameters do*: a synthetic cooling curve evaluated with
the current settings, annotated with the effect of each parameter.

**With the mouse (NORTH / Jupyter)**: on the project page click OPEN IN JUPYTER, open
`examples/DSC_evaluation.ipynb` (or a new notebook) and run

    %matplotlib widget
    from nomad_dsc_trios.north import DSCEvaluator
    DSCEvaluator()

Choose folder and curve, drag across a peak to set its window (tangents are recomputed at once),
"Save to NOMAD" writes mode, cycle and windows into the entry and NOMAD processes it. "Results of
this folder" saves `dsc_results.csv` into the folder. Needs `ipympl` in the Jupyter image.

**Table of a project or folder**: `python scripts/dsc_results_csv.py <project id> [--folder F]`
writes one CSV row per DSC entry (temperatures, enthalpies, mode, flags) via the NOMAD API.

The engine (`nomad_dsc_trios.evaluation`) is plain numpy/scipy and can be used on its own.

## DMA (TRIOS JSON)

A TRIOS JSON export of a **DMA** run (DMA 850 ...; `.json` or `.json.gz`) creates a
`DMA (TRIOS)` entry instead (the instrument type is read from the export):

* sample, operator, start time, clamp geometry (clamp, length, dimensions, notes),
  instrument, procedure name and steps;
* one segment per results step with time, temperature, set point, strain, stress, force,
  displacement, length, modulus (and storage/loss modulus, tan δ, frequency if present);
* oscillation steps: storage / loss / complex modulus, tan δ, phase angle, frequency,
  oscillation stress and strain amplitude;
* plots: stress vs strain, strain vs temperature (one line per step); length vs temperature
  if a step has no static strain (TRIOS records none in oscillation steps); storage/loss
  modulus and tan δ vs temperature for oscillation data; and the explorer with all numeric
  channels of the export.

Fill in material, composition, processing history and the test description in the GUI.

## Install in a NOMAD Oasis (nomad-distro-template)

Add to `pyproject.toml` of the distribution:

```toml
[project.optional-dependencies]
plugins = [
  "nomad-dsc-trios @ git+https://github.com/<user>/nomad-dsc-trios.git@v0.1.0",
]
```

Push; the GitHub workflow updates `uv.lock` and builds the image. On the server:
`docker compose pull && docker compose up -d`.

## Develop / test

```bash
pip install -e '.[dev]'
pytest -q tests/
```

Run date is interpreted in `TIME_ZONE = 'Europe/Prague'` (`schema_packages/dsc.py`).
