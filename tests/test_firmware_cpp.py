import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is needed for native firmware logic test")
def test_portable_cpp_firmware_pipeline(tmp_path):
    binary = tmp_path / ("firmware-pipeline-test.exe" if os.name == "nt" else "firmware-pipeline-test")
    root = Path.cwd()
    subprocess.run([
        "g++", "-std=c++17", "-I" + os.path.relpath(root / "firmware/include", tmp_path),
        os.path.relpath(root / "tests/firmware_pipeline_test.cpp", tmp_path), "-o", binary.name,
    ], check=True, cwd=tmp_path)
    subprocess.run([str(binary)], check=True)
