"""Import the app without starting collectors or making background requests."""
import importlib
from unittest.mock import patch
import pytest

with patch('threading.Thread.start'):
    importlib.import_module('app')


@pytest.fixture(autouse=True)
def isolated_component_health(monkeypatch):
    # Legacy collector tests exercise their own inputs, never the user's live proxy/config.
    import app
    monkeypatch.setattr(app, 'collect_components', lambda observations=None: {'components': [], 'overall_health': None})
