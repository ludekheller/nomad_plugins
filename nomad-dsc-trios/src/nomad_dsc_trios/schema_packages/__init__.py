from nomad.config.models.plugins import SchemaPackageEntryPoint


class DSCSchemaPackageEntryPoint(SchemaPackageEntryPoint):
    def load(self):
        from nomad_dsc_trios.schema_packages.dsc import m_package

        return m_package


dsc_sma = DSCSchemaPackageEntryPoint(
    name='DSC_SMA',
    description='DSC on shape memory alloys from TA Instruments TRIOS CSV exports.',
)


class DMASchemaPackageEntryPoint(SchemaPackageEntryPoint):
    def load(self):
        from nomad_dsc_trios.schema_packages.dma import m_package

        return m_package


dma_trios = DMASchemaPackageEntryPoint(
    name='DMA_TRIOS',
    description='DMA runs (TA Instruments DMA 850 ...) from TRIOS JSON exports.',
)
