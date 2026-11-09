from nomad.config.models.plugins import ParserEntryPoint


class WalterBaiParserEntryPoint(ParserEntryPoint):
    def load(self):
        from nomad_walterbai.parsers.parser import WalterBaiParser

        return WalterBaiParser(**self.model_dump())


walterbai_parser = WalterBaiParserEntryPoint(
    name='WalterBaiParser',
    description='Walter+Bai (UTTRMO) machine record (no extension): creates the test entry.',
    mainfile_name_re=r'.*',  # no extension: recognised by the header line only
    mainfile_mime_re=r'text/.*',
    mainfile_contents_re=r'^﻿?Time / s\tPosition / mm\tForce / N',
)


class WalterBaiDICParserEntryPoint(ParserEntryPoint):
    def load(self):
        from nomad_walterbai.parsers.parser import WalterBaiDICParser

        return WalterBaiDICParser(**self.model_dump())


walterbai_dic_parser = WalterBaiDICParserEntryPoint(
    name='WalterBaiDICParser',
    description='1D DIC export <name>_dic.csv: added to the Walter+Bai test entry <name>.',
    mainfile_name_re=r'.*_dic\.csv$',
    mainfile_mime_re=r'(text|application)/.*',
    mainfile_contents_re=r'Fram(e)? ID;Absolute Timestamp;.* - Displacement \[mm\]',
)
