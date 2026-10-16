"""Use private Windows runtime DLLs without changing the machine or PATH."""
import os
from pathlib import Path
import sys

_handles = []


def prepare_private_runtime(*, required=False):
    if sys.platform != 'win32':
        return
    prefix = Path(sys.prefix)
    if not (prefix / 'msvcp140.dll').is_file():
        if required:
            raise RuntimeError('Private Visual C++ runtime missing; rerun this release installer.')
        return  # Older installations may already have the system runtime.
    if not _handles:
        # Python's Windows venv launcher can run the base interpreter. Its DLL
        # search does not automatically include the venv's data/Scripts folders.
        # Keep directory handles alive for later lazy imports, including ONNX.
        _handles.extend(os.add_dll_directory(str(path)) for path in (prefix, prefix / 'Scripts'))
