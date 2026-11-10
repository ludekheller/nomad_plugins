from nomad.config.models.plugins import ParserEntryPoint


class APTParserEntryPoint(ParserEntryPoint):
    def load(self):
        from nomad_apt.parsers.parser import APTParser

        return APTParser(**self.model_dump())


apt_parser = APTParserEntryPoint(
    name='APTParser',
    description='APT files (.hits .rhit .rraw .pos .epos .apt .rrng .rng): grouped by run number '
                '(e.g. R6043_00349) into one APT measurement entry per run (AP Suite exports: see the .xml parser).',
    mainfile_name_re=r'.*\.(hits|HITS|rhit|RHIT|rraw|RRAW|pos|POS|epos|EPOS|apt|APT|rrng|RRNG|rng|RNG)$',
    mainfile_mime_re=r'.*',
)


class APTExportParserEntryPoint(ParserEntryPoint):
    def load(self):
        from nomad_apt.parsers.parser import APTParser

        return APTParser(**self.model_dump())


apt_export_parser = APTExportParserEntryPoint(
    name='APTExportParser',
    description='AP Suite experiment export (.xml): one APT measurement entry per exported reconstruction.',
    mainfile_name_re=r'.*\.(xml|XML)$',
    mainfile_mime_re=r'(text|application)/.*',
    mainfile_contents_re=r'<ExportExperiment',
)
