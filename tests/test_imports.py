"""Test that all core project modules import successfully."""


def test_imports():
    import config.settings
    import sports_engine
    import sports_engine.backtest
    import sports_engine.collectors
    import sports_engine.collectors.base
    import sports_engine.domain
    import sports_engine.domain.schemas
    import sports_engine.evaluation
    import sports_engine.features
    import sports_engine.models
    import sports_engine.normalization
    import sports_engine.normalization.canonical
    import sports_engine.normalization.resolution
    import sports_engine.storage
    import sports_engine.storage.database
    import sports_engine.storage.parquet_io
    import sports_engine.storage.paths

    assert sports_engine.__version__ == "0.1.0"
    assert config.settings.get_settings() is not None
