"""Import the app without starting collectors or making background requests."""
import importlib
from unittest.mock import patch

with patch('threading.Thread.start'):
    importlib.import_module('app')
