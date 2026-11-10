from nomad.config.models.plugins import ParserEntryPoint


class IRRecordParserEntryPoint(ParserEntryPoint):
    def load(self):
        from nomad_infratec.parsers.parser import IRRecordParser

        return IRRecordParser(**self.model_dump())


ir_record_parser = IRRecordParserEntryPoint(
    name='IRRecordParser',
    description='Creates an IR record entry for every InfraTec / LabVIEW .tdms file.',
    mainfile_name_re=r'.*\.(tdms|TDMS)$',
    mainfile_mime_re=r'.*',
    mainfile_binary_header_re=rb'^TDSm',
)
