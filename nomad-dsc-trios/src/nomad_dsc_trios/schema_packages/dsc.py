"""DSC on shape memory alloys - schema with built-in TRIOS CSV reading.

Python version of `dsc_sma.archive.yaml`. Differences:
  * `data_file` (top level): attach a TRIOS CSV export; on save/processing the entry
    reads it and fills settings, segments, TRIOS results and the overlay plot.
  * Values entered by hand (specimen description, corrected Ms/Mf/As/Af, ...) are never
    overwritten; only empty fields are filled from the file. Segments and the plot are
    always rebuilt from the file.
"""

import gzip
import io
import json

import numpy as np
from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.annotations import ELNAnnotation
from nomad.datamodel.metainfo.plot import PlotlyFigure, PlotSection
from nomad.metainfo import Datetime, MEnum, Quantity, SchemaPackage, Section, SubSection

from nomad_dsc_trios import evaluation_nomad as EV
from nomad_dsc_trios.explorer import explorer_figure
from nomad_dsc_trios.trios import (
    EXPLORER_VARIABLES,
    overlay_figure,
    read_trios_csv,
    read_trios_json,
)

m_package = SchemaPackage(name='DSC on shape memory alloys (TA Instruments TRIOS)')

TIME_ZONE = 'Europe/Prague'  # clock of the DSC PC, used for the run date


def _str(label=None, rich=False, **kw):
    comp = 'RichTextEditQuantity' if rich else 'StringEditQuantity'
    return Quantity(type=str, a_eln=ELNAnnotation(component=comp, label=label), **kw)


def _num(unit, display=None, **kw):
    eln = ELNAnnotation(component='NumberEditQuantity')
    if display:
        eln = ELNAnnotation(component='NumberEditQuantity', defaultDisplayUnit=display)
    return Quantity(type=np.float64, unit=unit, a_eln=eln, **kw)


KELVIN_NOTE = ('{} in K, computed from the °C value (read-only). Used by the search filters: the NOMAD 2.0 '
               'GUI cannot draw histogram filters of °C quantities.')


def _kelvin(name):
    return Quantity(type=np.float64, unit='kelvin', description=KELVIN_NOTE.format(name))


def kelvin_copies(section, names):
    """Set <name>_K = <name> converted to kelvin (or unset it if <name> is empty)."""
    for name in names:
        value = getattr(section, name)
        setattr(section, f'{name}_K', None if value is None else float(value.to('kelvin').magnitude))


def _file(description):
    return Quantity(
        type=str,
        description=description,
        a_eln=ELNAnnotation(component='FileEditQuantity'),
        a_browser=dict(adaptor='RawFileAdaptor'),
    )


class DSC_Specimen(ArchiveSection):
    m_def = Section(a_eln=dict(overview=True))
    specimen_id = _str()
    material = _str(description='Alloy designation, e.g. NiTi, NiTiHf, NiTiNb')
    nominal_composition = _str(description='e.g. Ni50.9Ti49.1 (at.%)')
    semi_product = _str(description='Wire, ribbon, sheet, bar, LPBF part ...')
    processing_history = _str(
        rich=True, description='Cold work, heat treatment (temperature, time, quench), training ...'
    )
    mass = _num('kilogram', display='milligram')


class DSC_Settings(ArchiveSection):
    m_def = Section(a_eln=dict(overview=True))
    instrument = _str()
    instrument_serial = _str()
    trios_version = Quantity(type=str)
    exotherm_direction = Quantity(type=str)
    pan_type = _str(description='e.g. Tzero aluminium, hermetic')
    purge_gas = _str()
    purge_flow = _num('milliliter / minute')
    heating_rate = _num('kelvin / minute')
    cooling_rate = _num('kelvin / minute')
    temperature_min = _num('celsius')
    temperature_max = _num('celsius')
    number_of_cycles = Quantity(type=int, a_eln=ELNAnnotation(component='NumberEditQuantity'))
    procedure = _str(rich=True, description='TRIOS procedure (equilibrate, ramp, isothermal ...)')


class DSC_Segment(PlotSection, ArchiveSection):
    m_def = Section(
        label_quantity='name',
        a_plotly_express=dict(
            method='line',
            x='#temperature',
            y='#heat_flow_normalized',
            layout=dict(title=dict(text='Heat flow vs temperature')),
        ),
    )
    name = Quantity(type=str)
    segment_type = Quantity(type=str, description='ramp_cooling, ramp_heating or isothermal')
    rate = Quantity(type=np.float64, unit='kelvin / minute')
    target_temperature = Quantity(type=np.float64, unit='celsius')
    time = Quantity(type=np.float64, unit='second', shape=['*'])
    temperature = Quantity(type=np.float64, unit='celsius', shape=['*'])
    heat_flow_normalized = Quantity(type=np.float64, unit='watt / gram', shape=['*'])


class TRIOS_Analysis(ArchiveSection):
    m_def = Section(label_quantity='model')
    analysed_step = Quantity(type=str)
    model = Quantity(type=str, description='e.g. Onset point, Endset point, Peak integration')
    result_name = Quantity(type=str)
    result_value = Quantity(type=np.float64)
    result_unit = Quantity(type=str)
    details = Quantity(type=str)


class DSC_Measurement(ArchiveSection):
    tri_file = _file('Original TRIOS .tri file in this upload (optional)')
    segments = SubSection(section_def=DSC_Segment, repeats=True)
    trios_analyses = SubSection(section_def=TRIOS_Analysis, repeats=True)


DSC_PEAK_FIELDS = tuple(f'{a}{i}' for i in (1, 2, 3) for a in ('Ms', 'Mf', 'As', 'Af'))
DSC_TEMPERATURES = ('Ms', 'Mf', 'As', 'Af', 'Rs', 'Rf', 'peak_temperature_cooling',
                    'peak_temperature_heating') + DSC_PEAK_FIELDS


class DSC_Results(ArchiveSection):
    m_def = Section(a_eln=dict(overview=True))
    evaluation_method = _str(description='e.g. tangent method (ASTM F2004), software used')
    Ms = _num('celsius')
    Mf = _num('celsius')
    As = _num('celsius')
    Af = _num('celsius')
    Rs = _num('celsius', description='R-phase start on cooling (if present)')
    Rf = _num('celsius', description='R-phase finish on cooling (if present)')
    peak_temperature_cooling = _num('celsius')
    peak_temperature_heating = _num('celsius')
    enthalpy_cooling = _num('joule / gram')
    enthalpy_heating = _num('joule / gram')
    transformation_sequence = _str(description="e.g. B2-B19', B2-R-B19', multistage")
    # single peaks of the tangent-method evaluation, in the order of the ramp
    # (cooling: 1 = highest temperature; heating: 1 = lowest temperature)
    Ms1 = _num('celsius', description='start of cooling peak 1 (tangent method)')
    Mf1 = _num('celsius', description='end of cooling peak 1 (tangent method)')
    As1 = _num('celsius', description='start of heating peak 1 (tangent method)')
    Af1 = _num('celsius', description='end of heating peak 1 (tangent method)')
    Ms2 = _num('celsius', description='start of cooling peak 2 (tangent method)')
    Mf2 = _num('celsius', description='end of cooling peak 2 (tangent method)')
    As2 = _num('celsius', description='start of heating peak 2 (tangent method)')
    Af2 = _num('celsius', description='end of heating peak 2 (tangent method)')
    Ms3 = _num('celsius', description='start of cooling peak 3 (tangent method)')
    Mf3 = _num('celsius', description='end of cooling peak 3 (tangent method)')
    As3 = _num('celsius', description='start of heating peak 3 (tangent method)')
    Af3 = _num('celsius', description='end of heating peak 3 (tangent method)')
    auto_filled = Quantity(type=str, description=(
        'Values filled automatically (TRIOS analyses or the tangent-method evaluation), JSON. A value that '
        'still equals its entry here may be replaced by a new evaluation; edited values are kept.'))

    # kelvin copies for the search page (see kelvin_copies)
    Ms_K = _kelvin('Ms')
    Mf_K = _kelvin('Mf')
    As_K = _kelvin('As')
    Af_K = _kelvin('Af')
    Rs_K = _kelvin('Rs')
    Rf_K = _kelvin('Rf')
    peak_temperature_cooling_K = _kelvin('peak_temperature_cooling')
    peak_temperature_heating_K = _kelvin('peak_temperature_heating')
    Ms1_K = _kelvin('Ms1')
    Mf1_K = _kelvin('Mf1')
    As1_K = _kelvin('As1')
    Af1_K = _kelvin('Af1')
    Ms2_K = _kelvin('Ms2')
    Mf2_K = _kelvin('Mf2')
    As2_K = _kelvin('As2')
    Af2_K = _kelvin('Af2')
    Ms3_K = _kelvin('Ms3')
    Mf3_K = _kelvin('Mf3')
    As3_K = _kelvin('As3')
    Af3_K = _kelvin('Af3')


EVAL_MODES = ('off', 'semi-automatic', 'automatic')


class DSC_Window(ArchiveSection):
    """Semi-automatic: temperature window around one peak (the two TRIOS cursors)."""

    m_def = Section(label_quantity='ramp')
    ramp = Quantity(type=MEnum('cooling', 'heating'), a_eln=ELNAnnotation(component='EnumEditQuantity'))
    T1 = _num('celsius', description='Baseline point on one side of the peak')
    T2 = _num('celsius', description='Baseline point on the other side of the peak')


def _par(label, description, unit=None, type_=np.float64, component='NumberEditQuantity'):
    return Quantity(type=type_, unit=unit, description=description,
                    a_eln=ELNAnnotation(component=component, label=label))


class DSC_EvaluationParameters(ArchiveSection):
    """Parameters of the tangent-method evaluation.

    In a DSC entry, empty fields are taken from the folder settings (dsc_evaluation.archive.json),
    then from the defaults. The folder settings show all values, defaults filled in.
    """

    mode = _par('Mode', 'off: nothing is computed (values from TRIOS or entered by hand); semi-automatic: one '
                'peak per window below; automatic: peaks and windows are found by the plugin. Default off',
                type_=MEnum(*EVAL_MODES), component='EnumEditQuantity')
    cycle = _par('Cycle', 'Cycle to evaluate: its cooling ramp and the following heating ramp. Default 1', type_=int)
    sg_window = _par('Smoothing window (Savitzky-Golay)', 'Width of the Savitzky-Golay window used for '
                     'smoothing and for the derivative (slope). Default 3 K', 'kelvin')
    sg_order = _par('Smoothing polynomial order', 'Polynomial order of the Savitzky-Golay filter. Default 3',
                    type_=int)
    min_height_percent = _par('Min. peak height (% of the largest peak)', 'Automatic: a peak counts if it is at '
                              'least this high, in % of the largest peak of the same ramp. Default 10 %')
    noise_factor = _par('Min. peak height (x noise)', 'Automatic: a peak must also be this many times higher '
                        'than the noise of the curve. Default 5')
    min_area = _par('Min. peak area', 'Automatic: smaller peaks (spikes) are ignored. Default 0.5 J/g',
                    'joule / gram')
    skip_start = _par('Skipped at the ramp start', 'Time ignored at the start of each ramp after the rate is '
                      'reached (start-up transient). Default 1 min', 'minute')
    curvature_window = _par('Curvature window (max.)', 'Automatic: largest smoothing window for the curvature '
                            'used to find the baseline points; narrower for narrow peaks. Default 20 K', 'kelvin')
    knee_fraction = _par('Baseline point: curvature fraction', 'Automatic: the baseline point beyond a peak is '
                         'where the curvature has dropped to this fraction of its maximum at the knee. Smaller = '
                         'baseline point further from the peak (Ms higher, Mf lower ...). Default 0.1')
    windows = SubSection(section_def=DSC_Window, repeats=True)


class DSC_Peak(ArchiveSection):
    m_def = Section(label_quantity='label')
    label = Quantity(type=str)
    ramp = Quantity(type=str)
    number = Quantity(type=int)
    start = Quantity(type=np.float64, unit='celsius', description='Onset in the direction of the ramp')
    end = Quantity(type=np.float64, unit='celsius', description='End in the direction of the ramp')
    peak_temperature = Quantity(type=np.float64, unit='celsius')
    enthalpy = Quantity(type=np.float64, unit='joule / gram')
    height = Quantity(type=np.float64, unit='watt / gram')
    inflection_start = Quantity(type=np.float64, unit='celsius')
    inflection_end = Quantity(type=np.float64, unit='celsius')
    T1 = Quantity(type=np.float64, unit='celsius', description='Baseline point (cursor) at the start')
    T2 = Quantity(type=np.float64, unit='celsius', description='Baseline point (cursor) at the end')
    flags = Quantity(type=str)


class DSC_Evaluation(DSC_EvaluationParameters):
    """Tangent-method evaluation of this run (see the plot 'Evaluation (tangent method)')."""

    m_def = Section(a_eln=dict(overview=True))
    use_folder_settings = Quantity(type=bool, description=(
        'Empty all parameters and windows of this entry, so that the folder settings '
        '(dsc_evaluation.archive.json) apply, and evaluate again'),
        a_eln=ELNAnnotation(component='ActionEditQuantity', label='Use the folder settings'))
    apply_to_folder = Quantity(type=bool, description=(
        'Evaluate all DSC curves that share the folder settings of this curve again (the folder of '
        'dsc_evaluation.archive.json and its sub-folders); this curve is evaluated when you save'),
        a_eln=ELNAnnotation(component='ActionEditQuantity', label='Apply to all DSC curves in this folder'))
    edit_automatic_windows = Quantity(type=bool, description=(
        'Switch to semi-automatic with the windows found automatically, to correct one of them'),
        a_eln=ELNAnnotation(component='ActionEditQuantity', label='Edit the automatic windows'))
    settings_file = Quantity(type=str, description='Folder settings used (dsc_evaluation.archive.json)',
                             a_browser=dict(adaptor='RawFileAdaptor'))
    parameters_used = Quantity(type=str, description='Effective parameters of the last evaluation (JSON)')
    windows_from_automatic = Quantity(type=bool, description='The windows were proposed by the automatic mode')
    messages = Quantity(type=str)
    peaks = SubSection(section_def=DSC_Peak, repeats=True)


class DSC_EvaluationSettings(DSC_EvaluationParameters, PlotSection, EntryData):
    """Evaluation settings for all DSC entries in this folder and its sub-folders.

    Every parameter is shown with the value used (defaults filled in); fields set in a single DSC
    entry override these. After changing the settings, click 'Apply to all DSC curves in this folder'
    (or reprocess the project) so that the DSC entries are evaluated again.
    """

    m_def = Section(label='DSC evaluation settings (folder)')
    apply_to_folder = Quantity(type=bool, description=(
        'Save these settings and evaluate all DSC curves in this folder and its sub-folders again'),
        a_eln=ELNAnnotation(component='ActionEditQuantity', label='Apply to all DSC curves in this folder'))

    def normalize(self, archive, logger):
        EV.fill_defaults(self)  # show every parameter with the value that is used
        if self.apply_to_folder:
            try:
                n = EV.reprocess_folder(archive, logger)
                logger.info('DSC entries of the folder sent to processing', n=n)
            finally:
                self.apply_to_folder = False
        try:
            fig = EV.schematic_figure({k: EV._plain(getattr(self, k)) for k in EV.PARAMS})
            self.figures = [PlotlyFigure(label='What the parameters do', figure=fig)]
        except Exception as e:
            logger.warning('could not draw the parameter schematic', exc_info=e)
        super().normalize(archive, logger)


class DSC_SMA(PlotSection, EntryData):
    """One DSC run on one specimen (TA Instruments TRIOS export)."""

    m_def = Section(label='DSC (SMA, TRIOS)')

    data_file = _file('TRIOS DSC export (.csv, or TRIOS JSON .json / .json.gz) in this upload; read on save')
    run_name = _str()
    operator = _str()
    date = Quantity(type=Datetime, a_eln=ELNAnnotation(component='DateTimeEditQuantity'))
    notes = _str(rich=True)

    specimen = SubSection(section_def=DSC_Specimen)
    instrument_settings = SubSection(section_def=DSC_Settings)
    measurement = SubSection(section_def=DSC_Measurement)
    transformation_results = SubSection(section_def=DSC_Results)
    evaluation = SubSection(section_def=DSC_Evaluation)

    def normalize(self, archive, logger):
        if self.data_file:
            try:
                self._read_data_file(archive, logger)
            except Exception as e:  # keep the entry usable if the file is not readable
                logger.error('could not read the TRIOS DSC file', data_file=self.data_file, exc_info=e)
        if self.run_name and archive.metadata is not None:
            archive.metadata.entry_name = self.run_name  # entry list shows the run, not the file name
        try:
            EV.evaluate_entry(self, archive, logger)
        except Exception as e:
            logger.error('tangent-method evaluation failed', exc_info=e)
        if self.transformation_results is not None:  # also after hand edits of the °C values
            kelvin_copies(self.transformation_results, DSC_TEMPERATURES)
        super().normalize(archive, logger)

    def _read_data_file(self, archive, logger):
        explorer = None
        name = self.data_file.lower()
        if name.endswith('.json.gz'):
            with archive.m_context.raw_file(self.data_file, 'rb') as f:
                with gzip.open(f) as g:
                    doc = json.load(io.TextIOWrapper(g, encoding='utf-8-sig'))
            data, ramps, _, explorer = read_trios_json(doc, self.data_file, tz=TIME_ZONE)
        else:
            with archive.m_context.raw_file(self.data_file, 'r', encoding='utf-8-sig') as f:
                if name.endswith('.json'):
                    data, ramps, _, explorer = read_trios_json(json.load(f), self.data_file,
                                                                             tz=TIME_ZONE)
                else:
                    data, ramps = read_trios_csv(f.read().splitlines(), self.data_file, tz=TIME_ZONE)

        # top-level quantities: fill only if empty
        for q in ('run_name', 'operator', 'date', 'notes'):
            if q in data and getattr(self, q) is None:
                self.m_update_from_dict({q: data[q]})

        # TRIOS onset/endset -> Ms/Mf/As/Af: empty fields, or fields still holding an automatic value
        results = data.get('transformation_results') or {}
        if results:
            if self.transformation_results is None:
                self.transformation_results = DSC_Results()
            EV.fill(self.transformation_results, results, 'TRIOS')

        # specimen, settings: create if missing, fill only empty quantities
        for name, section_def in (
            ('specimen', DSC_Specimen),
            ('instrument_settings', DSC_Settings),
        ):
            values = data.get(name, {})
            if getattr(self, name) is None:
                if not values:
                    continue
                setattr(self, name, section_def())
            target = getattr(self, name)
            missing = {k: v for k, v in values.items() if getattr(target, k) is None}
            if missing:
                target.m_update_from_dict(missing)

        # measurement data and plot: always rebuilt from the file
        tri_file = self.measurement.tri_file if self.measurement else None
        measurement = DSC_Measurement.m_from_dict(data['measurement'])
        if tri_file:  # keep a .tri link the user set by hand
            measurement.tri_file = tri_file
        elif not archive.m_context.raw_path_exists(measurement.tri_file or ''):
            measurement.tri_file = None
        self.measurement = measurement
        # sub-sections are normalized before their parent, so these new segments
        # would otherwise miss their plots
        for segment in measurement.segments:
            segment.normalize(archive, logger)
        self.figures = [PlotlyFigure(label='All ramps', figure=overlay_figure(ramps))]
        if explorer is None:  # CSV: the three channels stored in the segments
            explorer = [(f'{i + 1}: {s["name"]}', {'Time_s': s['time'], 'Temperature_°C': s['temperature'],
                                                  'Heat Flow (Normalized)_W/g': s['heat_flow_normalized']})
                        for i, s in enumerate(data['measurement']['segments'])]
        fig = explorer_figure(explorer, EXPLORER_VARIABLES, 'Temperature_°C', ['Heat Flow (Normalized)_W/g'],
                              title='Explorer: x menu, y on/off buttons (below), y scale menu')
        if fig:
            self.figures.append(PlotlyFigure(label='Explorer (choose x and y)', figure=fig))

        logger.info(
            'TRIOS DSC file read',
            data_file=self.data_file,
            segments=len(measurement.segments),
            trios_results=len(measurement.trios_analyses),
        )


class TRIOS_DSC_Export(EntryData):
    """Raw TRIOS DSC export; the measurement itself is in the linked DSC entry."""

    m_def = Section(label='TRIOS export (raw file)')
    dsc_entry = Quantity(type=str, description='DSC or DMA entry (.archive.json) created for this file')


m_package.__init_metainfo__()
