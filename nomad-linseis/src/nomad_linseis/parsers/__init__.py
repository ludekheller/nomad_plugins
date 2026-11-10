from nomad.config.models.plugins import ParserEntryPoint


class LinseisTMAParserEntryPoint(ParserEntryPoint):
    def load(self):
        from nomad_linseis.parsers.parser import LinseisTMAParser

        return LinseisTMAParser(**self.model_dump())


linseis_tma_parser = LinseisTMAParserEntryPoint(
    name='LinseisTMAParser',
    description='Creates a TMA entry for every Linseis TMA text export.',
    mainfile_name_re=r'.*\.txt$',
    mainfile_mime_re=r'text/.*',
    mainfile_contents_re=r'# Name:[\s\S]*Measurement date and time[\s\S]*Delta L',
)
