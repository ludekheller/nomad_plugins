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
