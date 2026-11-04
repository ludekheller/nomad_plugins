from nomad.config.models.plugins import ParserEntryPoint


class WaveMatrixParserEntryPoint(ParserEntryPoint):
    def load(self):
        from nomad_thermomech.parsers.wavematrix_parser import WaveMatrixTestParser

        return WaveMatrixTestParser(**self.model_dump())


wavematrix_parser = WaveMatrixParserEntryPoint(
    name='WaveMatrixTestParser',
    description='Creates one thermomechanical-test entry per folder with an Instron WaveMatrix test log.',
    mainfile_name_re=r'.*\.log$',
    mainfile_mime_re=r'(text|application)/.*',
    mainfile_contents_re=r'60101,Log File Created',
)


class MercuryParserEntryPoint(ParserEntryPoint):
    def load(self):
        from nomad_thermomech.parsers.mercury_parser import MercuryExportParser

        return MercuryExportParser(**self.model_dump())


mercury_parser = MercuryParserEntryPoint(
    name='MercuryExportParser',
    description='Adds a Mercury RT DIC export to the thermomechanical-test entry of its folder.',
    mainfile_name_re=r'.*\.csv$',
    mainfile_mime_re=r'(text|application)/.*',
    mainfile_contents_re=r'Frame ID;Absolute Timestamp',
)
