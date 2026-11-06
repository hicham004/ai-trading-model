"""Paper-fleet shortlist rows the OWNER decides on, built from a study's own record (plan row R23).

The studies append their confirmed passers to the fleet shortlist themselves
(plan rows R12, R13, R16, R18b, R19): each row carries a ``source`` tag naming
the study, its results file and, since R18b, the cell the record comes from,
and the fleet loader (``research.paper_fleet.config``) validates the row
against that record before an account exists. A row the owner adds by decision
— a forward control a study could not judge, a sleeve a study recorded but did
not ticket for the fleet — has no study script to apply it. This module builds
such a row from the study's stored record exactly as the study would have
(``research.report_v1c._row`` plus the R18b ``source`` tag read from the
record's cell, brakes and protocol check), so the loader validates it against
the same record, and applies it with ``research.replication.append_to_shortlist``
under the R12 rule: the shortlist file is restored when the fleet cannot load
the amended version.

What it never does: run a study, open a holdout, change a gate, change an
existing row, or touch anything under ``app/``. A spec file
(``docs/research/paper_fleet_additions_r23.json``) records the decision, its
date and the rows; the committed shortlist must reproduce from it (tested).
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from research.paper_fleet.config import _flat_results, _result_for, load_manifest
from research.replication import _shortlist_key, append_to_shortlist
from research.report_v1c import _row

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "docs" / "research" / "paper_fleet_additions_r23.json"
ROLES = ("candidate", "control")
SPEC_KEYS = ("plan_row", "decided", "amendment_note", "rows")
ROW_KEYS = ("results", "study", "candidate", "instrument", "timeframe", "mode", "cell", "role")


class FleetRowError(ValueError):
    """A spec or a record the row cannot be built from."""


@dataclass(frozen=True)
class RowRequest:
    """One row to build: which study record (run and cell) and what the row is for the fleet (a candidate or a control)."""

    results: str  # the study's results file, relative to the repository root
    study: str  # ``source.study`` (the fleet's label and the key of its sources entry)
    candidate: str
    instrument: str
    timeframe: str
    mode: str
    cell: str  # ``results[].cell.key`` (plan row R18b): tier | brakes | variant
    role: str = "candidate"
    report: Optional[str] = None
    control_label: Optional[str] = None  # a control's words in the fleet's account label and the weekly report
    note: Optional[str] = None  # why the owner added it and how to read it (``source.note``)

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise FleetRowError(f"a row's role is one of {ROLES}, not {self.role!r}")
        if self.role == "control" and not self.control_label:
            raise FleetRowError(f"{self.name}: a control row needs its control_label")
        if not self.results or not self.study or not self.cell:
            raise FleetRowError(f"{self.name}: a row needs its study, results file and cell")

    @property
    def name(self) -> str:
        return f"{self.candidate} {self.instrument} {self.timeframe} [{self.mode}] @ {self.cell}" + (" (control)" if self.role == "control" else "")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RowRequest":
        missing = [k for k in ROW_KEYS if not raw.get(k)]
        if missing:
            raise FleetRowError(f"a row in the spec lacks {missing}")
        known = {"results", "study", "candidate", "instrument", "timeframe", "mode", "cell", "role", "report", "control_label", "note"}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise FleetRowError(f"a row in the spec has unknown keys {unknown}")
        return cls(**{k: raw[k] for k in raw})


def load_spec(path: Path = DEFAULT_SPEC) -> Dict[str, Any]:
    """The owner-decision spec: its words, the amendment note and the rows to build (validated, nothing read from the studies yet)."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [k for k in SPEC_KEYS if not doc.get(k)]
    if missing:
        raise FleetRowError(f"{path}: the spec lacks {missing}")
    if not isinstance(doc["rows"], list) or not doc["rows"]:
        raise FleetRowError(f"{path}: the spec names no rows")
    doc["requests"] = [RowRequest.from_dict(r) for r in doc["rows"]]
    return doc


def load_results(rel: str, *, root: Path = ROOT) -> Dict[str, Any]:
    path = Path(rel) if Path(rel).is_absolute() else root / rel
    doc = json.loads(path.read_text(encoding="utf-8"))
    check = (doc.get("meta") or {}).get("protocol_check")
    if check is not None and not check.get("ok"):
        raise FleetRowError(f"{rel}: the study did not run Sprint 2c's protocol ({check.get('mismatches')})")
    return doc


def find_result(doc: Mapping[str, Any], req: RowRequest) -> Mapping[str, Any]:
    """The one stored record of the run at the cell (the fleet loader's own lookup, so the row is validated against the same record)."""
    return _result_for(_flat_results(doc), req.candidate, req.instrument, req.timeframe, req.mode, cell=req.cell)


def row_from_result(result: Mapping[str, Any], req: RowRequest, *, generated_at: Optional[str] = None, decided: Optional[str] = None) -> Dict[str, Any]:
    """A shortlist row from a study record, in the form the studies write (``_row`` plus the R18b source tag)."""
    cell = result.get("cell") or {}
    if cell.get("key") != req.cell:
        raise FleetRowError(f"{req.name}: the record's cell is {cell.get('key')!r}")
    check = result.get("protocol_check") or {}
    if check.get("unexplained_mismatches") or not check.get("ok_for_cell", False):
        raise FleetRowError(f"{req.name}: the study's protocol check of that cell is not clean ({check.get('unexplained_mismatches')!r})")
    row = _row(result)
    tier = str(cell.get("tier") or "reference")
    if tier != "reference":
        acc = result.get("acceptance_r18") or {}
        row["passed"] = bool(acc.get("passed"))  # the section 4.6 verdict at the tier (the v1c thresholds differ), as plan row R19's rows record it
        row["failed_gates"] = list(acc.get("failed") or [])
        row["sizing"] = str(cell.get("label") or row["sizing"]).split(", brakes")[0]
    r18 = result.get("r18") or {}
    source: Dict[str, Any] = {"study": req.study, "report": req.report, "results": req.results, "generated_at": generated_at, "tier": tier,
                              "brakes": r18.get("brakes"), "variant": str(cell.get("variant") or "none"), "cell": cell["key"],
                              "protocol_variant": check.get("protocol_variant"), "role": req.role}
    for key in ("hypothesis", "fixed_bracket"):
        if result.get(key) is not None:
            source[key] = result[key]
    if decided:
        source["decided"] = decided
    if req.note:
        source["note"] = req.note
    row["source"] = source
    if req.role == "control":
        row["control_label"] = req.control_label
        row["holdout"] = None  # a control is never judged: no holdout, no verdict
        row["holdout_confirmed"] = None
    return row


def build_rows(spec: Mapping[str, Any], *, root: Path = ROOT) -> List[Dict[str, Any]]:
    """Every row of a loaded spec, each from its study's record."""
    docs: Dict[str, Dict[str, Any]] = {}
    rows = []
    for req in spec["requests"]:
        if req.results not in docs:
            docs[req.results] = load_results(req.results, root=root)
        doc = docs[req.results]
        rows.append(row_from_result(find_result(doc, req), req, generated_at=(doc.get("meta") or {}).get("generated_at"), decided=spec.get("decided")))
    return rows


def rows_present(shortlist: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> List[str]:
    """Which of the rows the shortlist already holds (same rule, market, mode and tier: ``append_to_shortlist`` would add nothing)."""
    keys = {_shortlist_key(c) for c in list(shortlist.get("configurations", [])) + list(shortlist.get("controls", []))}
    return [_label(r) for r in rows if _shortlist_key(r) in keys]


def _label(row: Mapping[str, Any]) -> str:
    key = _shortlist_key(row)
    tier = "" if key[4] == "reference" else f" @ {key[4]}"
    return f"{row['candidate']} {row['instrument']} {row['timeframe']} [{key[3]}]{tier}" + (" (control)" if (row.get("source") or {}).get("role") == "control" else "")


def apply_rows(shortlist_path: Path, rows: Sequence[Mapping[str, Any]], *, note: str, check_only: bool = False) -> Tuple[bool, str, List[str]]:
    """Append the rows and prove the fleet can load the amended shortlist; otherwise restore the file untouched (the R12 rule).

    Returns ``(ok, message, added_account_ids)``. With ``check_only`` the append is done on a copy and the file is never written.
    """
    path = Path(shortlist_path)
    before = {a.account_id for a in load_manifest(path).accounts}
    if check_only:
        with tempfile.TemporaryDirectory(prefix="fleet-rows-check-") as tmp:
            copy = Path(tmp) / path.name
            shutil.copyfile(path, copy)
            append_to_shortlist(copy, rows, note=note)
            try:
                manifest = load_manifest(copy)
            except Exception as exc:  # the fleet could not read the amended file: report it, the real file was never touched
                return False, f"the paper fleet cannot load the amended shortlist ({type(exc).__name__}: {exc}); nothing was written", []
        added = sorted(a.account_id for a in manifest.accounts if a.account_id not in before)
        return True, f"check only: the fleet would load {len(manifest.accounts)} accounts, adding {', '.join(added) or 'none'}; nothing was written", added
    original = path.read_text(encoding="utf-8")
    data = append_to_shortlist(path, rows, note=note)
    try:
        manifest = load_manifest(path)
    except Exception as exc:  # the fleet cannot read the amended file: put the original back, report, never break the fleet
        path.write_text(original, encoding="utf-8")
        return False, f"NOT applied — the paper fleet cannot load the amended shortlist ({type(exc).__name__}: {exc}); the file was restored", []
    added = sorted(a.account_id for a in manifest.accounts if a.account_id not in before)
    return True, (f"applied: {path.as_posix()} now lists {len(data.get('configurations', []))} configurations and {len(data.get('controls', []))} controls "
                  f"({len(manifest.accounts)} fleet accounts; added {', '.join(added) or 'none'}); a running fleet takes the new accounts at its next "
                  "restart from an updated checkout"), added


__all__ = ["DEFAULT_SPEC", "FleetRowError", "RowRequest", "apply_rows", "build_rows", "find_result", "load_results", "load_spec", "row_from_result",
           "rows_present"]
