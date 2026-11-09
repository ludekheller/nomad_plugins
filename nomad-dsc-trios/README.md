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
  configuration and procedure. TRIOS analyses inside the JSON are not read yet (a warning
  says so); enter Ms/Mf/As/Af by hand or use the CSV export for TRIOS onsets.
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
