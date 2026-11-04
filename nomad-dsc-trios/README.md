# nomad-dsc-trios

NOMAD plugin for DSC measurements on shape memory alloys exported from
TA Instruments TRIOS (DSC 2500, CSV export).

## What it does

* **Upload a TRIOS DSC `.csv`** (optionally with the `.tri`) to a NOMAD project.
  The plugin recognises it and creates the editable DSC entry `<run>.archive.json`.
* The DSC entry (`DSC (SMA, TRIOS)`) reads the CSV: instrument settings, procedure,
  sample mass, every procedure step as a segment with its own plot, the TRIOS
  onset/endset analyses, Ms/Mf/As/Af (when unambiguous), and an overlay plot of all
  ramps on the entry page.
* Fill in the specimen description (material, composition, processing history ...)
  in the GUI and save. Values typed in by hand are never overwritten; only empty
  fields are filled from the file. Segments and plots are always rebuilt from the file.
* A DSC entry can also be created by hand (NEW ENTRY -> DSC (SMA, TRIOS)) and a CSV
  attached to `data_file`.

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
