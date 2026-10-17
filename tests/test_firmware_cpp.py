import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is needed for native firmware logic test")
def test_portable_cpp_firmware_pipeline(tmp_path):
    binary = tmp_path / "firmware-pipeline-test"
    subprocess.run([
        "g++", "-std=c++17", "-Ifirmware/include",
        "tests/firmware_pipeline_test.cpp", "-o", str(binary),
    ], check=True)
    subprocess.run([str(binary)], check=True)
