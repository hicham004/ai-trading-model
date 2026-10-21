"""Paper-fleet journals: a line torn by a crash never swallows the next record; sequence numbers stay readable."""

from __future__ import annotations

from research.paper_fleet.store import Journal


def test_a_torn_last_line_is_closed_before_the_next_append(tmp_path):
    j = Journal(tmp_path / "a.jsonl")
    assert j.append([{"seq": 1, "type": "start"}, {"seq": 2, "type": "bar"}]) == 2
    with open(j.path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write('{"seq": 3, "type": "bar", "equi')  # the process died in the middle of this line
    assert j.last_seq() == 2  # the torn line is not counted
    assert j.append([{"seq": 3, "type": "bar"}, {"seq": 4, "type": "bar"}]) == 2
    assert [r["seq"] for r in j.read()] == [1, 2, 3, 4]
    assert j.path.read_text(encoding="utf-8").count("\n") == 5  # the torn line stayed alone on its line
    assert j.append([{"seq": 4, "type": "bar"}]) == 0  # already written: never twice


def test_appending_nothing_creates_nothing(tmp_path):
    j = Journal(tmp_path / "b.jsonl")
    assert j.append([]) == 0 and not j.path.exists() and j.last_seq() == 0 and list(j.read()) == []
