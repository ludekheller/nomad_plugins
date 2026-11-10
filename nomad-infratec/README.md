# nomad-infratec

NOMAD plugin for InfraTec infrared camera records saved by the LabVIEW acquisition (`.tdms`).

Every `.tdms` becomes an **IR record** entry `<name>.archive.json` (the `.tdms_index` is not
needed). An IR record is independent of the tests: it may belong to a thermomechanical test
(Instron / Mercury, Walter+Bai ...), to a heat treatment before a test, or to neither.
`related_entries` links it to any entries (test, heat treatment, sample); `purpose` says what
was recorded.

Read from the file: time (s from the first frame), per ROI the mean / max / min temperature, the
profiles along the sample axis (mean over the ROI width) and the temperature field (stored in K,
shown in °C). Frames in which the camera does not yet measure the sample (maximum below
-100 °C) are counted as invalid and shown as gaps.

Plots: temperature vs time (all ROIs), explorer (x / y on-off / normalisation), profiles vs time
(map, menu per ROI), profile at a chosen time (slider), temperature field at a chosen time
(slider, fixed colour scale, starts at the hottest frame).

Entered by hand (never overwritten): purpose, related entries, date, operator, camera, lens,
emissivity, specimen, description and notes, and a description per ROI.

The time stamps in the file use the acquisition PC's time base (not clock time), so the record
is not synchronised automatically with the testing machine.

Dependency: `nptdms`. Tests: `pytest -q tests/` (synthetic .tdms from `tests/make_data.py`).
