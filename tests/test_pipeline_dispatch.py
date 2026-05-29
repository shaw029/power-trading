import sys
from unittest.mock import MagicMock

import pytest

from pipeline import run_full_pipeline

_MINIMAL_CONFIG = {
    "data": {
        "periods": [{"start": "2018-01-01", "end": "2019-01-01", "demand_source": "NESO_API"}],
        "wind_source": "ELEXON",
        "generation_source": "ELEXON",
        "day_ahead_price_source": "ENTSOE",
        "market_index_source": "ELEXON",
        "demand_actual_source": "ELEXON",
        "imbalance_source": "ELEXON",
    },
}


class TestRunFullPipelineDispatch:
    def test_virtual_mode_calls_virtual(self, monkeypatch):
        mock = MagicMock(return_value={"mode": "virtual"})
        monkeypatch.setattr("pipeline._run_virtual_pipeline", mock)
        monkeypatch.setattr("pipeline.ensure_directories", lambda: None)

        result = run_full_pipeline(mode="virtual")

        mock.assert_called_once_with(None, skip_features=False)
        assert result["mode"] == "virtual"

    def test_download_mode_calls_download(self, monkeypatch):
        mock = MagicMock(return_value={"mode": "download"})
        monkeypatch.setattr("pipeline._run_download", mock)
        monkeypatch.setattr("pipeline.ensure_directories", lambda: None)

        result = run_full_pipeline(mode="download", config=_MINIMAL_CONFIG)

        mock.assert_called_once_with(_MINIMAL_CONFIG)
        assert result["mode"] == "download"

    def test_features_mode_calls_features(self, monkeypatch):
        mock = MagicMock(return_value={"mode": "features", "features_file": None})
        monkeypatch.setattr("pipeline._run_features", mock)
        monkeypatch.setattr("pipeline.ensure_directories", lambda: None)

        result = run_full_pipeline(mode="features", config=_MINIMAL_CONFIG)

        mock.assert_called_once_with(_MINIMAL_CONFIG)
        assert result["mode"] == "features"

    def test_model_mode_calls_virtual_with_skip_features(self, monkeypatch):
        mock = MagicMock(return_value={"mode": "virtual"})
        monkeypatch.setattr("pipeline._run_virtual_pipeline", mock)
        monkeypatch.setattr("pipeline.ensure_directories", lambda: None)

        run_full_pipeline(mode="model")

        mock.assert_called_once_with(None, skip_features=True)

    def test_bess_mode_calls_bess(self, monkeypatch):
        mock = MagicMock(return_value={"mode": "bess"})
        monkeypatch.setattr("pipeline._run_bess_pipeline", mock)
        monkeypatch.setattr("pipeline.ensure_directories", lambda: None)

        config = {"strategy_type": "bess"}
        result = run_full_pipeline(mode="bess", config=config)

        mock.assert_called_once_with(config)
        assert result["mode"] == "bess"

    def test_all_mode_calls_both(self, monkeypatch):
        mock_v = MagicMock(return_value={"mode": "virtual"})
        mock_b = MagicMock(return_value={"mode": "bess"})
        monkeypatch.setattr("pipeline._run_virtual_pipeline", mock_v)
        monkeypatch.setattr("pipeline._run_bess_pipeline", mock_b)
        monkeypatch.setattr("pipeline.ensure_directories", lambda: None)

        result = run_full_pipeline(mode="all")

        mock_v.assert_called_once()
        mock_b.assert_called_once()
        assert "virtual" in result
        assert "bess" in result

    def test_invalid_mode_raises(self, monkeypatch):
        monkeypatch.setattr("pipeline.ensure_directories", lambda: None)

        with pytest.raises(ValueError, match="Invalid mode"):
            run_full_pipeline(mode="bogus")

    def test_mode_defaults_from_config(self, monkeypatch):
        mock = MagicMock(return_value={"mode": "bess"})
        monkeypatch.setattr("pipeline._run_bess_pipeline", mock)
        monkeypatch.setattr("pipeline.ensure_directories", lambda: None)

        run_full_pipeline(config={"strategy_type": "bess"})

        mock.assert_called_once()

    def test_mode_defaults_to_virtual(self, monkeypatch):
        mock = MagicMock(return_value={"mode": "virtual"})
        monkeypatch.setattr("pipeline._run_virtual_pipeline", mock)
        monkeypatch.setattr("pipeline.ensure_directories", lambda: None)

        run_full_pipeline()

        mock.assert_called_once_with(None, skip_features=False)

    def test_explicit_mode_overrides_config(self, monkeypatch):
        mock_v = MagicMock(return_value={"mode": "virtual"})
        mock_b = MagicMock(return_value={"mode": "bess"})
        monkeypatch.setattr("pipeline._run_virtual_pipeline", mock_v)
        monkeypatch.setattr("pipeline._run_bess_pipeline", mock_b)
        monkeypatch.setattr("pipeline.ensure_directories", lambda: None)

        run_full_pipeline(mode="virtual", config={"strategy_type": "bess"})

        mock_v.assert_called_once()
        mock_b.assert_not_called()

    def test_skip_features_forwarded_to_virtual(self, monkeypatch):
        mock = MagicMock(return_value={"mode": "virtual"})
        monkeypatch.setattr("pipeline._run_virtual_pipeline", mock)
        monkeypatch.setattr("pipeline.ensure_directories", lambda: None)

        run_full_pipeline(mode="virtual", skip_features=True)

        mock.assert_called_once_with(None, skip_features=True)

    def test_skip_features_forwarded_in_all_mode(self, monkeypatch):
        mock_v = MagicMock(return_value={"mode": "virtual"})
        mock_b = MagicMock(return_value={"mode": "bess"})
        monkeypatch.setattr("pipeline._run_virtual_pipeline", mock_v)
        monkeypatch.setattr("pipeline._run_bess_pipeline", mock_b)
        monkeypatch.setattr("pipeline.ensure_directories", lambda: None)

        run_full_pipeline(mode="all", skip_features=True)

        mock_v.assert_called_once_with(None, skip_features=True)


class TestMainCLIParsing:
    def test_mode_virtual(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "virtual"])
        mock_run = MagicMock()
        monkeypatch.setattr("main.run_full_pipeline", mock_run)
        monkeypatch.setattr("main._load_config", lambda _: {"strategy_type": "virtual"})

        from main import main
        main()

        _, kwargs = mock_run.call_args
        assert kwargs["mode"] == "virtual"

    def test_mode_bess_short_flag(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["main.py", "-m", "bess"])
        mock_run = MagicMock()
        monkeypatch.setattr("main.run_full_pipeline", mock_run)
        monkeypatch.setattr("main._load_config", lambda _: {"strategy_type": "virtual"})

        from main import main
        main()

        _, kwargs = mock_run.call_args
        assert kwargs["mode"] == "bess"

    def test_mode_defaults_from_config(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["main.py"])
        mock_run = MagicMock()
        monkeypatch.setattr("main.run_full_pipeline", mock_run)
        monkeypatch.setattr("main._load_config", lambda _: {"strategy_type": "bess"})

        from main import main
        main()

        _, kwargs = mock_run.call_args
        assert kwargs["mode"] == "bess"

    def test_mode_download(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "download"])
        mock_run = MagicMock()
        monkeypatch.setattr("main.run_full_pipeline", mock_run)
        monkeypatch.setattr("main._load_config", lambda _: {})

        from main import main
        main()

        _, kwargs = mock_run.call_args
        assert kwargs["mode"] == "download"

    def test_mode_features(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "features"])
        mock_run = MagicMock()
        monkeypatch.setattr("main.run_full_pipeline", mock_run)
        monkeypatch.setattr("main._load_config", lambda _: {})

        from main import main
        main()

        _, kwargs = mock_run.call_args
        assert kwargs["mode"] == "features"

    def test_mode_model(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "model"])
        mock_run = MagicMock()
        monkeypatch.setattr("main.run_full_pipeline", mock_run)
        monkeypatch.setattr("main._load_config", lambda _: {})

        from main import main
        main()

        _, kwargs = mock_run.call_args
        assert kwargs["mode"] == "model"
