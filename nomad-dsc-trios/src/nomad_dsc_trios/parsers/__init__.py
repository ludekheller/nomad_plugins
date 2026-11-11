from nomad.config.models.plugins import ParserEntryPoint


class TriosDSCParserEntryPoint(ParserEntryPoint):
    def load(self):
        from nomad_dsc_trios.parsers.trios_parser import TriosDSCParser

        return TriosDSCParser(**self.model_dump())


trios_dsc_parser = TriosDSCParserEntryPoint(
    name='TriosDSCParser',
    description='Creates a DSC_SMA entry for every TA Instruments TRIOS DSC CSV export.',
    mainfile_name_re=r'.*\.csv$',
    mainfile_mime_re=r'(text|application)/.*',
    mainfile_contents_re=r'Instrument name,DSC',
)


trios_dsc_json_parser = TriosDSCParserEntryPoint(
    name='TriosDSCJsonParser',
    description='Creates a DSC or DMA entry for every TA Instruments TRIOS JSON export.',
    # <run>.json, <run>.json.gz or <run>.gz (any case); not NOMAD's own *.archive.json
    mainfile_name_re=r'(?i)^(?!.*\.archive\.json$).*\.(json|json\.gz|gz)$',
    mainfile_mime_re=r'(text|application)/.*',
    mainfile_contents_re=r'TRIOSJSONExportSchema',
    supported_compressions=['gz'],  # <run>.json.gz: about 10x smaller
)
