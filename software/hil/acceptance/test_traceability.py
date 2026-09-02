"""Traceability gates — every requirement has a row, every row names a real one.

Distinct from `test_protocol.py`'s NFR-TST01 gate, and the difference matters:

- **NFR-TST01's gate** asks *which automated script covers which FR-MB*, because
  that requirement demands a run report listing every non-excepted FR-MB ID with
  a result. It is narrow on purpose.
- **These gates** ask the broader question the project kept getting wrong: does
  every requirement in the TDS have a **test row** anywhere in the plan, and
  does every row cite a requirement that actually exists?

Both run with **no hardware**. A coverage claim that only holds when the bench is
plugged in is not a coverage claim.

Why these exist. On 2026-09-01 a sweep of the plan found **twelve** requirements
cited by no row and **four** rows citing the wrong requirement — TP-B12 pointing
at FR-MB09 (which is FC03 support) for a bad-CRC test, TP-B15 at FR-MB23 (which
is discarding RX while transmitting) for the inter-frame gap, TP-B03 at FR-S02
(a statement about PCB support) for boot timing. Later the same day FR-E23 and
FR-E24 were added to the TDS and the existing gate did **not** notice, because it
only enumerated FR-MB.

What these gates cannot do, and it is the more dangerous half: **a row that cites
a real requirement while testing something else still passes.** FR-S02 looked
covered for as long as TP-B03 existed. Only reading the row against the
requirement catches that. These gates check that a mapping exists, not that it is
truthful.
"""

import re
from pathlib import Path

DESIGN = Path(__file__).parent.parent.parent.parent / "design"
TDS = DESIGN / "TDS.md"
PLAN = DESIGN / "testPlan.md"
COMPLIANCE = DESIGN / "requirementsCompliance.md"

#: A requirement is DEFINED by a table row that begins with its id.
DEFINED_RE = re.compile(r"^\|\s*((?:N?FR)-[A-Z]+\d+)\s*\|", re.M)
#: A requirement is CITED anywhere its id appears in prose or a table cell.
CITED_RE = re.compile(r"(?:N?FR)-[A-Z]+\d+")


def defined_in(path):
    return set(DEFINED_RE.findall(path.read_text(encoding="utf-8")))


def cited_in(path):
    return set(CITED_RE.findall(path.read_text(encoding="utf-8")))


def _sorted(ids):
    return sorted(ids, key=lambda s: (re.match(r"[A-Z-]+", s).group(), int(re.search(r"\d+", s).group())))


def test_every_tds_requirement_has_a_test_row():
    """Every FR-MB, FR-S, FR-E and NFR in the TDS is cited by the plan.

    This is the gate that would have caught FR-E23 and FR-E24 arriving with no
    rows. It covers **all** requirement families, not just FR-MB.
    """
    missing = _sorted(defined_in(TDS) - cited_in(PLAN))
    assert not missing, (
        f"{len(missing)} requirement(s) in the TDS are cited by no row in "
        f"testPlan.md: {missing}.\n"
        f"Adding a requirement without a verification row leaves it untested "
        f"and untestable — nobody knows it is missing. Write the row, or record "
        f"it in the plan's known-gaps section with what blocks it.")


def test_plan_cites_no_requirement_that_does_not_exist():
    """Every id the plan names is defined somewhere.

    Catches the reverse failure: a row still claiming a requirement that has
    been withdrawn or renumbered, which overstates coverage exactly as a missing
    row understates it.

    `requirementsCompliance.md` is allowed as a second source: FR-WP ids are the
    customer's requirements and live there, not in the TDS.
    """
    known = defined_in(TDS) | defined_in(COMPLIANCE)
    ghosts = _sorted(cited_in(PLAN) - known)
    assert not ghosts, (
        f"testPlan.md cites {ghosts}, which neither TDS.md nor "
        f"requirementsCompliance.md defines.\n"
        f"A row claiming to verify a requirement that does not exist is a "
        f"coverage claim for nothing.")


def test_requirement_ids_are_written_out_in_full():
    """No abbreviated ranges in the plan's traceability columns.

    `FR-E01, E02, E03` and `NFR-ENV01…05` both read fine to a person and are
    invisible to every check above — the ids after the first are not ids at all.
    Both forms were present on 2026-09-01 and made eleven FR-E and four NFR-ENV
    requirements look uncovered when they were merely unspellable.
    """
    text = PLAN.read_text(encoding="utf-8")
    bad = []
    # ", E02" / ", S17" / ", MB04" — a bare family suffix following a real id
    for m in re.finditer(r"(?:N?FR)-[A-Z]+\d+((?:\s*,\s*[A-Z]{1,3}\d+)+)", text):
        bad.append(m.group(0)[:60])
    # an ellipsis between two ids: "FR-MB01…FR-MB30", "NFR-ENV01…05"
    for m in re.finditer(r"(?:N?FR)-[A-Z]+\d+\s*(?:…|\.\.\.)\s*[A-Z]*\d+", text):
        frag = m.group(0)
        if "§" not in frag:
            bad.append(frag[:60])
    assert not bad, (
        f"{len(bad)} abbreviated requirement reference(s) in testPlan.md: "
        f"{bad}.\nWrite every id in full. An abbreviation in a traceability "
        f"column is not traceable, and a coverage check that reads it as a gap "
        f"is right to.")
