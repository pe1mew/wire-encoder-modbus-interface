"""Acceptance-suite fixtures (integrationPlan.md stage F, NFR-TST01 seed).

Wraps the check scripts as pytest runs against a flashed DUT:

    ..\\.venv-m2k\\Scripts\\python.exe -m pytest . -v

There is one release build, so there is nothing to select.

The suite is intentionally a thin orchestrator: each underlying script
remains runnable standalone for debugging, and its PASS/FAIL contract is
what the tests assert.

STATUS: only the NFR-RES01/NFR-BLD01 build gates (test_builds.py) are
implemented. The protocol, register-map and measurement rows arrive with
the driver work — see design/integrationPlan.md stages C–F. Rows that need
a specific bench rig stay behind an explicit --run-* flag so the default
`pytest .` run stays green and honest about what it covered.
"""

import subprocess
import sys
from pathlib import Path

import pytest

HIL = Path(__file__).parent.parent


def pytest_addoption(parser):
    parser.addoption("--mcp-port", type=int, default=10530)
    # Bench-gated rows. Each needs a specific rig, so it is skipped unless
    # explicitly enabled — kept out of the default green run.
    parser.addoption("--run-reset-matrix", action="store_true",
                     help="FR-S21 reset matrix (needs a *_test hang-hook "
                          "build or programmable-supply power control)")
    parser.addoption("--run-raw-master", action="store_true",
                     help="FR-MB20/21 latency histogram (needs the second "
                          "MAX3485 M2K raw master)")
    parser.addoption("--run-m2k", action="store_true",
                     help="M2K-stimulus rows: FR-E03 divider sweep, FR-E07 "
                          "fault/recovery, VDD ratiometric sweep")


@pytest.fixture(scope="session")
def mcp_port(request):
    return request.config.getoption("--mcp-port")


@pytest.fixture(scope="session")
def dut_addr():
    """Jumper-open Modbus address (TDS FR-S03). Bridged is this + 5."""
    return 40


@pytest.fixture(scope="session")
def run_reset_matrix(request):
    return request.config.getoption("--run-reset-matrix")


@pytest.fixture(scope="session")
def run_raw_master(request):
    return request.config.getoption("--run-raw-master")


@pytest.fixture(scope="session")
def run_m2k(request):
    return request.config.getoption("--run-m2k")


def run_check(script, *args):
    """Run a harness script with the m2k venv python; return (rc, output)."""
    proc = subprocess.run([sys.executable, str(HIL / script), *args],
                          capture_output=True, text=True, timeout=900)
    out = proc.stdout + proc.stderr
    print(out)  # keep the detailed per-row log in the pytest report
    return proc.returncode, out
