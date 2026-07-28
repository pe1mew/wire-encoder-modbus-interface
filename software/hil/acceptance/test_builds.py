"""NFR-RES01/NFR-BLD01 build checks (stage F).

- Every environment builds and stays inside the resource ceilings (the
  ceilings are ALSO hard build gates via board_upload.maximum_size; this
  test records the numbers in the report).
- The full NFR-BLD01 double-clean-build hash comparison is available as a
  slow opt-in: pytest -m reproducible (two clean builds per environment).

These are the only acceptance rows that need no hardware, which is why they
are the only ones implemented yet.
"""

import hashlib
import os
import re
import subprocess
from pathlib import Path

import pytest

FIRMWARE = Path(__file__).parent.parent.parent / "firmware"
PIO = Path(os.environ["USERPROFILE"]) / ".platformio/penv/Scripts/pio.exe"
CEIL_FLASH = 14336
CEIL_RAM = 1792
ENVS = ["encoder", "encoder_endswitch", "encoder_test"]
RELEASE_ENV = "encoder"


def build(env, clean=False):
    if clean:
        subprocess.run([str(PIO), "run", "-e", env, "-t", "clean"],
                       cwd=FIRMWARE, capture_output=True, text=True, timeout=300)
    p = subprocess.run([str(PIO), "run", "-e", env], cwd=FIRMWARE,
                       capture_output=True, text=True, timeout=600)
    out = p.stdout + p.stderr
    flash = re.search(r"Flash:.*?\(used (\d+)", out)
    ram = re.search(r"RAM:.*?\(used (\d+)", out)
    assert p.returncode == 0 and "SUCCESS" in out, out[-2000:]
    return int(flash.group(1)), int(ram.group(1))


@pytest.mark.parametrize("env", ENVS)
def test_build_within_ceilings(env):
    flash, ram = build(env)
    print(f"{env}: flash {flash} B / {CEIL_FLASH}, ram {ram} B / {CEIL_RAM}")
    assert flash <= CEIL_FLASH and ram <= CEIL_RAM


@pytest.mark.reproducible
def test_reproducible_build():
    """NFR-BLD01: two clean builds of the release tree are bit-identical."""
    hashes = []
    for _ in range(2):
        build(RELEASE_ENV, clean=True)
        binary = FIRMWARE / ".pio" / "build" / RELEASE_ENV / "firmware.bin"
        hashes.append(hashlib.sha256(binary.read_bytes()).hexdigest())
    assert hashes[0] == hashes[1], f"builds differ: {hashes}"
