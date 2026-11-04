"""Replication study (plan row R12): market pre-selection, bounded public collectors, the frozen study lake, the Sprint 2c runner
loaded as a module, the pre-registered verdict rules, the holdout ledger, the shortlist additions and the report."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.datalake.layout import LakeLayout
from app.datalake.okx_public_rest import OKXPublicRest
from app.datalake.parquet_store import CANDLE_SCHEMA, TS_TYPE, read_candles, write_partitioned
from research import replication as rep
from research import replication_data as rdata
from research.data import load_or_resample_candles, positioning_context
from research.markets import REPLICATION_CANDIDATES, RESEARCH_SYMBOL_FOR_INSTRUMENT, research_symbol_for
from research.report_replication import executive_summary, render_report

ROOT = Path(__file__).resolve().parents[1]
HOUR = 3_600_000


# -- fakes -----------------------------------------------------------------------------------------

class _Response:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _OkxSession:
    """Answers OKX's public candle endpoints per bar from a synthetic history; records every request (GET only)."""

    def __init__(self, n_hours: int, start: str = "2020-01-01"):
        self.t0 = int(pd.Timestamp(start, tz="UTC").value // 1_000_000)
        self.rows = {"1H": [self._row(self.t0 + i * HOUR) for i in range(n_hours)],
                     "4H": [self._row(self.t0 + i * 4 * HOUR) for i in range(n_hours // 4)] + [self._row(self.t0 + 5 * HOUR)]}  # one off-grid 4H row
        self.calls = []

    @staticmethod
    def _row(ts: int):
        return [str(ts), "100", "101", "99", "100.5", "5", "0", "0", "1"]

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        rows = sorted(self.rows[params["bar"]], key=lambda r: -int(r[0]))
        if url.endswith("/api/v5/market/candles"):
            data = rows[: int(params["limit"])]
        elif url.endswith("/api/v5/market/history-candles"):
            after = int(params["after"])
            data = [r for r in rows if int(r[0]) < after][: int(params["limit"])]
        else:
            raise AssertionError(f"unexpected endpoint {url}")
        return _Response({"code": "0", "msg": "", "data": data})


class _BinanceClient:
    """A GET-only stand-in for ``BinancePublicClient``: ascending funding rows from ``startTime``, ``limit`` per page."""

    def __init__(self, n: int, start: str = "2020-01-06 08:00"):
        t0 = int(pd.Timestamp(start, tz="UTC").value // 1_000_000)
        self.rows = [{"symbol": "XRPUSDT", "fundingTime": t0 + i * 8 * HOUR, "fundingRate": f"{0.0001 * ((i % 5) - 2):.8f}", "markPrice": ""} for i in range(n)]
        self.calls = []

    def get_json(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        assert path == "/fapi/v1/fundingRate"
        assert params["symbol"] == "XRPUSDT"
        start = int(params["startTime"])
        return [r for r in self.rows if r["fundingTime"] >= start][: int(params["limit"])]


class _PreregRest:
    """Tickers and one-candle history probes for the pre-registration step."""

    def __init__(self, volumes, no_history=("SOL-USDT",)):
        self.volumes = volumes
        self.no_history = set(no_history)
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        if path == rdata.TICKERS_PATH:
            return [{"instId": k, "volCcy24h": str(v)} for k, v in self.volumes.items()] + [{"instId": "BTC-USDT", "volCcy24h": "900000000"}]
        if path == rdata.HISTORY_CANDLES_PATH:
            if params["instId"] in self.no_history:
                return []
            ts = int(pd.Timestamp("2019-12-31 23:00", tz="UTC").value // 1_000_000)
            return [[str(ts), "1", "1", "1", "1", "1", "0", "0", "1"]]
        raise AssertionError(path)


VOLUMES = {"XRP-USDT": 47e6, "DOGE-USDT": 40e6, "LINK-USDT": 8.6e6, "TRX-USDT": 7.9e6, "ADA-USDT": 7.7e6, "LTC-USDT": 6.2e6, "XLM-USDT": 5.9e6,
           "BCH-USDT": 4.7e6, "ETC-USDT": 1.5e6, "ATOM-USDT": 1.0e6, "ALGO-USDT": 0.8e6, "SOL-USDT": 99e6}


# -- market tables and the pre-registered selection -------------------------------------------------

def test_market_tables_are_consistent_and_bounded():
    assert set(RESEARCH_SYMBOL_FOR_INSTRUMENT) == set(REPLICATION_CANDIDATES)
    assert research_symbol_for("XRP-USDT") == "XRPUSDT"
    for inst in ("BTC-USDT", "ETH-USDT", "XYZ-USDT"):
        with pytest.raises(ValueError):
            research_symbol_for(inst)


def test_rank_candidates_applies_the_preregistered_rule():
    tickers = [{"instId": k, "volCcy24h": str(v)} for k, v in VOLUMES.items()]
    history = {k: ("2019-12-31 23:00" if k != "SOL-USDT" else None) for k in REPLICATION_CANDIDATES}
    history["ALGO-USDT"] = None  # a candidate whose history turns out to start later is not eligible
    picks = rep.rank_candidates(tickers, history)
    chosen = rep.chosen_markets(picks)
    assert chosen == ["XRP-USDT", "DOGE-USDT", "LINK-USDT", "TRX-USDT", "ADA-USDT", "LTC-USDT", "SOL-USDT"]
    by = {p.instrument: p for p in picks}
    assert by["XLM-USDT"].rank == 7 and not by["XLM-USDT"].chosen
    assert by["SOL-USDT"].chosen and by["SOL-USDT"].rank is None and by["SOL-USDT"].history_before_cutoff is None
    assert not by["ALGO-USDT"].chosen and by["ALGO-USDT"].rank is None and "no public 1H candle" in by["ALGO-USDT"].reason
    # Ties are broken by name, so the same snapshot always gives the same list.
    tied = [{"instId": k, "volCcy24h": "1"} for k in VOLUMES]
    picks_tied = rep.rank_candidates(tied, {k: "x" for k in REPLICATION_CANDIDATES})
    assert rep.chosen_markets(picks_tied)[:6] == sorted(k for k in REPLICATION_CANDIDATES if k != "SOL-USDT")[:6]


def test_preregister_writes_once_and_the_loader_checks_the_hash(tmp_path):
    path = tmp_path / "prereg.json"
    rest = _PreregRest(VOLUMES)
    payload = rep.preregister(rest, path, now=datetime(2026, 11, 4, 16, 0, tzinfo=timezone.utc))
    assert payload["chosen"] == ["XRP-USDT", "DOGE-USDT", "LINK-USDT", "TRX-USDT", "ADA-USDT", "LTC-USDT", "SOL-USDT"]
    assert {p for p, _ in rest.calls} == {rdata.TICKERS_PATH, rdata.HISTORY_CANDLES_PATH}
    assert all(params.get("limit") == 1 for p, params in rest.calls if p == rdata.HISTORY_CANDLES_PATH)
    loaded = rep.load_preregistration(path)
    assert loaded["sha256"] == payload["sha256"] and loaded["data_end"] == rep.DATA_END
    with pytest.raises(rep.ReplicationError):
        rep.preregister(rest, path)  # the markets are fixed once
    data = json.loads(path.read_text(encoding="utf-8"))
    data["chosen"].append("BCH-USDT")
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(rep.ReplicationError):
        rep.load_preregistration(path)


def test_the_committed_preregistration_is_intact_and_matches_the_fixed_text():
    data = rep.load_preregistration(rep.PREREGISTRATION_PATH)
    assert data["preregistration"] == rep.PREREGISTRATION
    assert len(data["chosen"]) == 7 and "SOL-USDT" in data["chosen"]
    assert all(m in REPLICATION_CANDIDATES for m in data["chosen"])


# -- collectors ------------------------------------------------------------------------------------------

def test_spot_candle_collector_is_bounded_resumable_and_uses_only_public_candle_paths(tmp_path):
    layout = LakeLayout(tmp_path / "lake")
    session = _OkxSession(1000)
    rest = OKXPublicRest(session=session, sleep=lambda s: None)
    one = rdata.collect_spot_candles(layout, "XRP-USDT", "1H", rest=rest, start=datetime(2019, 12, 1, tzinfo=timezone.utc), sleep_seconds=0.0)
    four = rdata.collect_spot_candles(layout, "XRP-USDT", "4H", rest=rest, start=datetime(2019, 12, 1, tzinfo=timezone.utc), sleep_seconds=0.0)
    assert one.added == 1000 and one.walk.complete and one.stored_rows == 1000
    assert four.added == 250 and four.stored_rows == 250  # the off-grid 4H row was dropped
    assert {url.rsplit("/api/v5/", 1)[1] for url, _ in session.calls} <= {"market/candles", "market/history-candles"}
    assert all(p["instId"] == "XRP-USDT" for _, p in session.calls)
    assert layout.state_file("candles", "XRP-USDT", "1H").exists()
    again = rdata.collect_spot_candles(layout, "XRP-USDT", "1H", rest=rest, start=datetime(2019, 12, 1, tzinfo=timezone.utc), sleep_seconds=0.0)
    assert again.added == 0
    df4 = load_or_resample_candles(layout, "XRP-USDT", "4H")
    assert len(df4) == 250 and df4.index.is_monotonic_increasing
    df6 = load_or_resample_candles(layout, "XRP-USDT", "6H")
    assert len(df6) == 1000 // 6
    for inst, bar in (("BTC-USDT", "1H"), ("XYZ-USDT", "1H"), ("XRP-USDT", "6H"), ("XRP-USDT", "1m")):
        with pytest.raises(rdata.ReplicationDataError):
            rdata.collect_spot_candles(layout, inst, bar, rest=rest, sleep_seconds=0.0)


def test_funding_collector_is_forward_resumable_bounded_and_found_by_the_research_context(tmp_path):
    layout = LakeLayout(tmp_path / "lake")
    client = _BinanceClient(2500)
    r1 = rdata.collect_research_funding(layout, "XRP-USDT", client=client, sleep_seconds=0.0)
    assert r1.symbol == "XRPUSDT" and r1.pages == 3 and r1.added == 2500 and r1.complete and r1.stored_rows == 2500
    assert all(p == "/fapi/v1/fundingRate" for p, _ in client.calls)
    r2 = rdata.collect_research_funding(layout, "XRP-USDT", client=client, sleep_seconds=0.0)
    assert r2.added == 0 and r2.reason == "up_to_date" and r2.pages == 1
    budget = rdata.collect_research_funding(LakeLayout(tmp_path / "lake2"), "XRP-USDT", client=_BinanceClient(2500), max_pages=1, sleep_seconds=0.0)
    assert budget.reason == "max_pages" and budget.added == 1000
    ctx = positioning_context(layout, "XRP-USDT", "4H", source="binance")
    assert ctx.funding is not None and len(ctx.funding) == 2500 and ctx.open_interest is None
    assert positioning_context(layout, "BTC-USDT", "4H", source="binance").funding is None  # the app's table, nothing stored here
    frame = rdata.research_funding_frame(layout, "XRP-USDT")
    idx = pd.date_range("2020-01-01", periods=1000, freq="4h", tz="UTC")
    cov = rdata.funding_bar_coverage(idx, frame)
    assert 0.9 < cov < 1.0  # funding starts 2020-01-06, a few days into the index
    assert rdata.funding_bar_coverage(idx, None) == 0.0
    with pytest.raises(rdata.ReplicationDataError):
        rdata.collect_research_funding(layout, "BTC-USDT", client=client)
    with pytest.raises(rdata.ReplicationDataError):
        rdata.parse_research_funding_rows([{"symbol": "XRPUSDT", "fundingTime": "x", "fundingRate": "0.1"}], "XRPUSDT")
    assert rdata.parse_research_funding_rows([{"symbol": "ETHUSDT", "fundingTime": 1, "fundingRate": "0.1"}], "XRPUSDT") == []


def _write_candles(layout: LakeLayout, inst: str, bar: str, index: pd.DatetimeIndex) -> None:
    n = len(index)
    table = pa.table({
        "open_time": pa.array([t.to_pydatetime() for t in index], type=TS_TYPE), "instrument": pa.array([inst] * n), "timeframe": pa.array([bar] * n),
        "open": pa.array(np.full(n, 100.0)), "high": pa.array(np.full(n, 101.0)), "low": pa.array(np.full(n, 99.0)), "close": pa.array(np.full(n, 100.5)),
        "volume": pa.array(np.full(n, 5.0)), "confirmed": pa.array([True] * n),
    }, schema=CANDLE_SCHEMA)
    write_partitioned(table, key="open_time", schema=CANDLE_SCHEMA, file_for_year=lambda y: layout.candles_file(inst, bar, y))


def test_freeze_lake_cuts_candles_at_the_data_end_and_copies_the_external_series(tmp_path):
    src = LakeLayout(tmp_path / "lake")
    dst = LakeLayout(tmp_path / "study")
    end = pd.Timestamp("2026-10-20 10:00", tz="UTC")
    one = pd.date_range("2026-10-19 00:00", periods=60, freq="h", tz="UTC")  # runs past the end
    four = pd.date_range("2026-10-19 00:00", periods=15, freq="4h", tz="UTC")
    _write_candles(src, "XRP-USDT", "1H", one)
    _write_candles(src, "XRP-USDT", "4H", four)
    fdir = src.external_series_dir("binance", "funding_rate", "XRPUSDT", "8H")
    fdir.mkdir(parents=True)
    pq.write_table(pa.table({"ts": pa.array([end.to_pydatetime()], type=TS_TYPE), "funding_rate": pa.array([0.0001])}), fdir / "2026.parquet")
    report = rep.freeze_lake(src, dst, ["XRP-USDT"], end=str(end), log=lambda m: None)
    kept_1h = read_candles(dst, "XRP-USDT", "1H").to_pandas()
    kept_4h = read_candles(dst, "XRP-USDT", "4H").to_pandas()
    assert report["candles"]["XRP-USDT 1H"] == len(kept_1h) == 34  # 2026-10-19 00:00 .. 2026-10-20 09:00 (bar close <= 10:00)
    assert pd.Timestamp(kept_1h["open_time"].max()).tz_convert("UTC") == pd.Timestamp("2026-10-20 09:00", tz="UTC")
    assert report["candles"]["XRP-USDT 4H"] == len(kept_4h) == 8  # the 04:00 bar (closing 08:00) is the last one kept
    assert pd.Timestamp(kept_4h["open_time"].max()).tz_convert("UTC") == pd.Timestamp("2026-10-20 04:00", tz="UTC")
    assert (dst.external_series_dir("binance", "funding_rate", "XRPUSDT", "8H") / "2026.parquet").exists()
    # Re-freezing replaces, never merges; the source is untouched; source == target is refused.
    rep.freeze_lake(src, dst, ["XRP-USDT"], end=str(end - pd.Timedelta(hours=24)), log=lambda m: None)
    assert len(read_candles(dst, "XRP-USDT", "1H").to_pandas()) == 10
    assert len(read_candles(src, "XRP-USDT", "1H").to_pandas()) == 60
    with pytest.raises(rep.ReplicationError):
        rep.freeze_lake(src, src, ["XRP-USDT"], end=str(end))


# -- the Sprint 2c runner as a module ----------------------------------------------------------------------

def test_the_sprint_2c_runner_loads_once_and_its_defaults_match_the_stored_protocol():
    v1c = rep.load_v1c_runner()
    assert v1c is rep.load_v1c_runner() and hasattr(v1c, "run_series") and hasattr(v1c, "run_candidate")
    meta = json.loads(rep.V1C_RESULTS.read_text(encoding="utf-8"))["meta"]
    cfg = rep.ReplicationConfig(lake_dir="x")
    args = rep.v1c_args(cfg, evaluate_holdout=True)
    assert args["evaluate_holdout"] is True and args["lake_dir"] == "x" and sorted(args["strategies"]) == sorted(rep.STUDY_STRATEGIES)
    check = rep.protocol_check(args, meta)
    assert check["ok"], check["mismatches"]
    wrong = dict(meta, train_days=500)
    assert "train_days" in rep.protocol_check(args, wrong)["mismatches"]
    wrong_policy = dict(meta, policy_sizing=dict(meta["policy_sizing"], target_vol=0.2))
    assert "policy_sizing" in rep.protocol_check(args, wrong_policy)["mismatches"]
    quick = rep.protocol_check(rep.v1c_args(rep.ReplicationConfig(quick=True), evaluate_holdout=False), meta)
    assert not quick["ok"] and "quick" in quick["mismatches"]
    assert rep.full_study_requested(rep.ReplicationConfig(), ["A", "B"], ["B", "A"])
    assert not rep.full_study_requested(rep.ReplicationConfig(quick=True), ["A"], ["A"])
    assert not rep.full_study_requested(rep.ReplicationConfig(strategies=("hold", "S1")), ["A"], ["A"])
    assert not rep.full_study_requested(rep.ReplicationConfig(), ["A"], ["A", "B"])


def test_btc_passers_of_sprint_2c_are_read_from_the_stored_results():
    stored = json.loads(rep.V1C_RESULTS.read_text(encoding="utf-8"))["results"]
    passers = rep.btc_passers_2c(stored, rep.ReplicationConfig())
    assert sorted(p["configuration"] for p in passers) == ["S1+S5 6H [none]", "S2 4H [gate]", "S2+S5 4H [gate]"]
    assert all(p["btc"]["passed"] for p in passers)


def _synthetic(n: int, *, freq: str = "4h", seed: int = 3, start: str = "2021-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    regime = np.sign(np.sin(np.arange(n) / 60.0))  # a trend flip about every 9 days, so a trend rule qualifies in every train window
    close = 100 * np.exp(np.cumsum(0.004 * regime + rng.normal(0, 0.012, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": rng.lognormal(3, 0.5, n)}, index=idx)


@pytest.fixture(scope="module")
def synthetic_market_lake(tmp_path_factory):
    layout = LakeLayout(tmp_path_factory.mktemp("r12_lake") / "lake")
    df = _synthetic(7600)
    table = pa.table({
        "open_time": pa.array([t.to_pydatetime() for t in df.index], type=TS_TYPE), "instrument": pa.array(["XRP-USDT"] * len(df)),
        "timeframe": pa.array(["4H"] * len(df)), "open": pa.array(df["open"].to_numpy()), "high": pa.array(df["high"].to_numpy()),
        "low": pa.array(df["low"].to_numpy()), "close": pa.array(df["close"].to_numpy()), "volume": pa.array(df["volume"].to_numpy()),
        "confirmed": pa.array([True] * len(df)),
    }, schema=CANDLE_SCHEMA)
    write_partitioned(table, key="open_time", schema=CANDLE_SCHEMA, file_for_year=lambda y: layout.candles_file("XRP-USDT", "4H", y))
    # Funding only from the middle of the history (about 30 % of the in-sample bars): below the 90 % coverage threshold, so S5 is reported as inactive.
    settle = pd.date_range(df.index[int(len(df) * 0.5)], df.index[-1], freq="8h", tz="UTC")
    fdir = layout.external_series_dir("binance", "funding_rate", "XRPUSDT", "8H")
    fdir.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"ts": pa.array([t.to_pydatetime() for t in settle], type=TS_TYPE),
                             "funding_rate": pa.array(np.full(len(settle), 0.0001)), "mark_price": pa.array(np.full(len(settle), 100.0))}),
                   fdir / "2024.parquet")
    return layout


def test_run_market_runs_the_sprint_2c_runner_and_annotates_without_opening_a_holdout(synthetic_market_lake):
    cfg = rep.ReplicationConfig(strategies=("hold", "S1", "S1+S5"), regime_modes=("none",), timeframes=("4H",), quick=True,
                                lake_dir=str(synthetic_market_lake.root))
    args = rep.v1c_args(cfg, evaluate_holdout=False)
    series = rep.run_market(args, "XRP-USDT", "4H", cfg, log=lambda m: None)
    assert series["instrument"] == "XRP-USDT" and not series.get("skipped") and series["benchmark"]["instrument"] == "XRP-USDT"
    by = {r["candidate"]: r for r in series["results"]}
    assert set(by) == {"hold", "S1", "S1+S5"}
    assert series["s5_active"] is False and 0.0 < series["funding_coverage"] < 0.9
    assert by["S1"]["judged"] and by["S1"]["display_candidate"] == "S1" and by["S1"]["configuration"] == "S1 4H [none]"
    assert by["S1"]["oos"]["n_trades"] > 0 and by["S1"]["oos"]["windows"] >= 2
    assert not by["hold"]["judged"]
    assert not by["S1+S5"]["judged"] and by["S1+S5"]["display_candidate"].startswith("S1 (run without S5")
    for r in series["results"]:
        assert "holdout" not in r and r["holdout_confirmed"] is None and set(r["acceptance"]) >= {"passed", "failed"}
        assert r["oos"]["n_trades"] >= 0 and r["family"] == r["candidate"]
    assert rep.holdout_openings([series]) == []
    # Verdict machinery on the live output: one market, no stored BTC pass for S1 -> 'fails everywhere' or 'robust' depending on the gates.
    fams = rep.family_verdicts([series], [], ["XRP-USDT"], cfg)
    assert [f["family"] for f in fams] == ["S1", "S1+S5"]
    s1, s15 = fams
    assert s1["label"] in ("robust across markets", "fails everywhere") and s1["n_configurations"] == 1
    assert s15["n_configurations"] == 0 and s15["s5_inactive_markets"] == ["XRP-USDT"] and s15["label"] == "not run"
    overall = rep.overall_verdict(fams, [series], ["XRP-USDT"])
    assert overall["n_judged"] == 1 and overall["label"] in ("robust across markets", "fails everywhere")
    beats = rep.beats_hold([series])
    assert len(beats) == 1 and beats[0]["best"] == "S1 4H [none]" and isinstance(beats[0]["beats_hold"], bool)
    passers = [{"candidate": "S1", "timeframe": "4H", "mode": "none", "configuration": "S1 4H [none]", "btc": {}, "btc_holdout": None, "btc_holdout_confirmed": None},
               {"candidate": "S2", "timeframe": "4H", "mode": "gate", "configuration": "S2 4H [gate]", "btc": {}, "btc_holdout": None, "btc_holdout_confirmed": None}]
    primary = rep.configuration_replication([series], passers, ["XRP-USDT"])
    assert primary[0]["n_judged"] == 1 and primary[0]["needed"] == 1 and primary[0]["markets"][0]["ran"]
    assert primary[1]["n_judged"] == 0 and not primary[1]["replicated"] and primary[1]["markets"][0]["ran"] is False


def test_reproduction_check_tolerates_only_the_stored_rounding():
    stored = [{"candidate": "S1", "instrument": "BTC-USDT", "timeframe": "4H", "regime": {"mode": "none"}, "selected_params": {"a": [1, 2], "bracket": "none"},
               "oos": {"total_return": 0.123457, "cagr": 0.02, "sharpe": 0.5, "max_drawdown": 0.1, "calmar": 0.2, "profit_factor": 1.3, "n_trades": 50},
               "acceptance": {"passed": False}}]
    good = {"results": [{"candidate": "S1", "instrument": "BTC-USDT", "timeframe": "4H", "regime": {"mode": "none"}, "selected_params": {"a": (1, 2), "bracket": "none"},
                         "oos": {"total_return": 0.1234571, "cagr": 0.02, "sharpe": 0.5, "max_drawdown": 0.1, "calmar": 0.2, "profit_factor": 1.3, "n_trades": 50},
                         "acceptance": {"passed": False}}]}
    assert rep.reproduction_check(good, stored)[0]["ok"]
    off = json.loads(json.dumps(good))
    off["results"][0]["oos"]["sharpe"] = 0.500002
    assert not rep.reproduction_check(off, stored)[0]["ok"]
    trades = json.loads(json.dumps(good))
    trades["results"][0]["oos"]["n_trades"] = 51
    assert not rep.reproduction_check(trades, stored)[0]["ok"]
    rule = json.loads(json.dumps(good))
    rule["results"][0]["selected_params"]["bracket"] = "tp2"
    assert not rep.reproduction_check(rule, stored)[0]["ok"]
    verdict = json.loads(json.dumps(good))
    verdict["results"][0]["acceptance"]["passed"] = True
    assert not rep.reproduction_check(verdict, stored)[0]["verdict_matches"]
    missing = json.loads(json.dumps(good))
    missing["results"][0]["timeframe"] = "6H"
    assert not rep.reproduction_check(missing, stored)[0]["ok"]


# -- verdict rules on hand-made results -------------------------------------------------------------------------

def _res(cand, inst, tf, mode, *, calmar, passed, holdout=None, s5_active=True, cov=1.0):
    r = {"candidate": cand, "instrument": inst, "timeframe": tf, "regime": {"mode": mode, "label": mode}, "selected_params": {"bracket": "none"},
         "oos": {"calmar": calmar, "cagr": calmar / 10, "max_drawdown": 0.1, "profit_factor": 1.1 + calmar, "sharpe": calmar, "n_trades": 60, "total_return": 0.1},
         "acceptance": {"passed": passed, "failed": [] if passed else ["calmar_gt_0_5"], "rolling_positive_share": 0.7, "worst_calendar_year_return": -0.05},
         "robustness": {"share_above_threshold": 0.8}, "dsr": {"dsr": 0.1}, "policy_sizing": {"label": "p"}}
    if holdout is not None:
        r["holdout"] = {"total_return": holdout, "profit_factor": 1.5 if holdout > 0 else 0.5, "n_trades": 20, "max_drawdown": 0.05}
    return rep.annotate_result(r, s5_active=s5_active, funding_coverage=cov)


def _series(inst, results, *, s5_active=True, hold_holdout=None):
    hold = _res("hold", inst, "4H", "none", calmar=0.3, passed=False, holdout=hold_holdout)
    return {"instrument": inst, "timeframe": "4H", "results": [hold] + results, "benchmark": {"cagr": 0.2, "max_drawdown": 0.7, "calmar": 0.3},
            "holdout_span": "2025-10-20->2026-10-20", "s5_active": s5_active, "funding_coverage": 1.0 if s5_active else 0.5, "positioning": {}}


STORED_BTC = [{"candidate": "S2", "instrument": "BTC-USDT", "timeframe": "4H", "regime": {"mode": "gate"}, "acceptance": {"passed": True}, "oos": {"calmar": 0.8}},
              {"candidate": "S1", "instrument": "BTC-USDT", "timeframe": "4H", "regime": {"mode": "none"}, "acceptance": {"passed": False}, "oos": {"calmar": 0.25}},
              {"candidate": "S1", "instrument": "ETH-USDT", "timeframe": "4H", "regime": {"mode": "none"}, "acceptance": {"passed": False}, "oos": {"calmar": 0.0}}]


def test_family_and_overall_verdicts_follow_the_preregistered_rule():
    cfg = rep.ReplicationConfig(strategies=("hold", "S1", "S2"), regime_modes=("none", "gate"), timeframes=("4H",))
    markets = ["A-USDT", "B-USDT", "C-USDT", "D-USDT"]
    assert rep.markets_needed(4) == 2 and rep.markets_needed(7) == 4 and rep.markets_needed(1) == 1
    # S2 passes on 2 of 4 markets (robust), S1 passes nowhere but did not pass on BTC either (fails everywhere).
    series = [
        _series("A-USDT", [_res("S2", "A-USDT", "4H", "gate", calmar=0.9, passed=True, holdout=0.03), _res("S1", "A-USDT", "4H", "none", calmar=0.1, passed=False)]),
        _series("B-USDT", [_res("S2", "B-USDT", "4H", "gate", calmar=0.7, passed=True, holdout=-0.03), _res("S1", "B-USDT", "4H", "none", calmar=0.2, passed=False)]),
        _series("C-USDT", [_res("S2", "C-USDT", "4H", "gate", calmar=0.2, passed=False), _res("S1", "C-USDT", "4H", "none", calmar=-0.1, passed=False)]),
        _series("D-USDT", [_res("S2", "D-USDT", "4H", "gate", calmar=0.1, passed=False), _res("S1", "D-USDT", "4H", "none", calmar=0.0, passed=False)]),
    ]
    fams = {f["family"]: f for f in rep.family_verdicts(series, STORED_BTC, markets, cfg)}
    assert fams["S2"]["label"] == "robust across markets" and fams["S2"]["markets_passing"] == ["A-USDT", "B-USDT"]
    assert fams["S2"]["confirmed_markets"] == ["A-USDT"] and fams["S2"]["contradicted_markets"] == ["B-USDT"]
    assert fams["S2"]["medians_btc"]["calmar"] == 0.8 and fams["S2"]["medians_new"]["calmar"] == pytest.approx(0.45)
    assert fams["S1"]["label"] == "fails everywhere" and not fams["S1"]["passes_on_btc_2c"]
    overall = rep.overall_verdict(list(fams.values()), series, markets)
    assert overall["label"] == "robust across markets" and overall["n_passed"] == 2 and overall["n_confirmed"] == 1 and overall["n_contradicted"] == 1
    # One passing market of four: fragile. None, for a family that passed on BTC: BTC-specific.
    series[1]["results"][1]["acceptance"]["passed"] = False
    fams = {f["family"]: f for f in rep.family_verdicts(series, STORED_BTC, markets, cfg)}
    assert fams["S2"]["label"] == "fragile"
    assert rep.overall_verdict(list(fams.values()), series, markets)["label"] == "fragile"
    series[0]["results"][1]["acceptance"]["passed"] = False
    fams = {f["family"]: f for f in rep.family_verdicts(series, STORED_BTC, markets, cfg)}
    assert fams["S2"]["label"] == "BTC-specific"
    assert rep.overall_verdict(list(fams.values()), series, markets)["label"] == "BTC-specific"
    # An inactive S5 market never counts for the S5 family.
    cfg5 = rep.ReplicationConfig(strategies=("hold", "S1+S5"), regime_modes=("none",), timeframes=("4H",))
    s5 = [_series("A-USDT", [_res("S1+S5", "A-USDT", "4H", "none", calmar=0.9, passed=True, s5_active=False, cov=0.5)], s5_active=False)]
    fam5 = rep.family_verdicts(s5, [], ["A-USDT"], cfg5)[0]
    assert fam5["n_configurations"] == 0 and fam5["s5_inactive_markets"] == ["A-USDT"] and fam5["label"] == "not run"
    assert rep.overall_verdict([fam5], s5, ["A-USDT"])["n_judged"] == 0


def test_primary_test_counts_passes_per_btc_passer_and_beats_hold_uses_calmar():
    markets = ["A-USDT", "B-USDT"]
    series = [_series("A-USDT", [_res("S2", "A-USDT", "4H", "gate", calmar=0.9, passed=True, holdout=0.02)], hold_holdout=-0.04),
              _series("B-USDT", [_res("S2", "B-USDT", "4H", "gate", calmar=0.3, passed=False)], hold_holdout=-0.02)]
    passers = rep.btc_passers_2c(STORED_BTC, rep.ReplicationConfig(strategies=("hold", "S2"), timeframes=("4H",)))
    assert [p["configuration"] for p in passers] == ["S2 4H [gate]"]
    primary = rep.configuration_replication(series, passers, markets)[0]
    assert primary["n_pass"] == 1 and primary["n_judged"] == 2 and primary["needed"] == 1 and primary["replicated"]
    assert primary["confirmed"] == ["A-USDT"] and primary["contradicted"] == []
    beats = rep.beats_hold(series)
    assert [b["beats_hold"] for b in beats] == [True, False] and beats[0]["hold_holdout"] == -0.04
    openings = rep.holdout_openings(series)
    assert [(o["configuration"], o["role"], o["confirmed"]) for o in openings] == [
        ("hold A-USDT 4H [none]", "control", None), ("S2 A-USDT 4H [gate]", "configuration", True), ("hold B-USDT 4H [none]", "control", None)]


def test_holdout_ledger_is_append_only_and_names_second_looks(tmp_path):
    path = str(tmp_path / "ledger.json")
    assert rep.load_ledger(path) == [] and rep.load_ledger("-") == []
    series = [_series("A-USDT", [_res("S2", "A-USDT", "4H", "gate", calmar=0.9, passed=True, holdout=0.02)], hold_holdout=-0.04)]
    entries = [{"generated_at": "a", "openings": rep.holdout_openings(series)}]
    rep.write_ledger(path, entries)
    loaded = rep.load_ledger(path)
    loaded.append({"generated_at": "b", "openings": []})
    rep.write_ledger(path, loaded)
    assert [e["generated_at"] for e in rep.load_ledger(path)] == ["a", "b"]
    assert rep.guard_second_look(rep.load_ledger(path), series, evaluate_holdout=True) == ["S2 A-USDT 4H [gate]"]
    assert rep.guard_second_look(rep.load_ledger(path), series, evaluate_holdout=False) == []
    (tmp_path / "bad.json").write_text("[]", encoding="utf-8")
    with pytest.raises(rep.ReplicationError):
        rep.load_ledger(str(tmp_path / "bad.json"))


def test_shortlist_additions_carry_a_source_tag_and_leave_existing_rows_untouched(tmp_path):
    series = [_series("A-USDT", [_res("S2", "A-USDT", "4H", "gate", calmar=0.9, passed=True, holdout=0.02),
                                 _res("S1", "A-USDT", "4H", "none", calmar=0.8, passed=True, holdout=-0.02),  # contradicted: never added
                                 _res("S2", "A-USDT", "6H", "none", calmar=0.7, passed=False, holdout=0.05)])]  # not a passer: never added
    additions = rep.shortlist_additions(series, source={"study": "R12 replication", "results": "r.json"})
    assert [(a["candidate"], a["timeframe"]) for a in additions] == [("S2", "4H")] and additions[0]["source"]["study"] == "R12 replication"
    assert additions[0]["holdout_confirmed"] is True and additions[0]["passed"] is True
    path = tmp_path / "shortlist.json"
    existing = {"status": "forward evidence only; nothing approved", "configurations": [
        {"rank": 1, "candidate": "S1+S5", "instrument": "BTC-USDT", "timeframe": "6H", "regime_config": {"mode": "none"}, "cagr": 0.05}], "controls": []}
    path.write_text(json.dumps(existing), encoding="utf-8")
    data = rep.append_to_shortlist(path, additions, note="test")
    assert data["configurations"][0] == existing["configurations"][0]
    assert data["configurations"][1]["rank"] == 2 and data["configurations"][1]["source"]["study"] == "R12 replication"
    assert data["amendments"][0]["added"] == ["S2 A-USDT 4H [gate]"] and data["status"] == existing["status"]
    again = rep.append_to_shortlist(path, additions, note="test")  # the same configuration is not added twice
    assert len(again["configurations"]) == 2 and again["amendments"][1]["added"] == []
    assert rep.append_to_shortlist(path, [], note="nothing") == again


# -- the report -------------------------------------------------------------------------------------------------

def _run(series, *, markets, stored=STORED_BTC, holdout=True):
    cfg = rep.ReplicationConfig(strategies=("hold", "S1", "S2"), regime_modes=("none", "gate"), timeframes=("4H",))
    families = rep.family_verdicts(series, stored, markets, cfg)
    passers = rep.btc_passers_2c(stored, cfg)
    return {
        "meta": {"generated_at": "2026-11-04 20:00 UTC", "markets": markets, "config": cfg.to_dict(), "preregistration": rep.PREREGISTRATION,
                 "preregistration_sha256": "abc", "snapshot": {"snapshot_at": "2026-11-04T16:32:33+00:00", "picks": [
                     {"instrument": "A-USDT", "quote_volume_24h": 1e6, "history_before_cutoff": "2019-12-31 23:00", "rank": 1, "chosen": True, "reason": "r"}]},
                 "protocol_check": {"ok": True, "checked": ["fee"]}, "v1c_meta": {"holdout_span": "2025-10-20->2026-10-20", "policy_sizing": {"label": "p"},
                                                                                  "regime": {"label": "g"}, "fee_rate": 0.001, "slippage_rate": 0.0005},
                 "evaluate_holdout": holdout, "data_end": rep.DATA_END, "gates": {"calmar_min": 0.5}, "holdout_ledger": [
                     {"generated_at": "2026-11-04 20:00 UTC", "openings": rep.holdout_openings(series)}], "holdout_ledger_path": "ledger.json"},
        "reproduction": [{"candidate": "S1", "instrument": "BTC-USDT", "timeframe": "4H", "regime": "none", "ok": True, "max_abs_difference": 4e-7,
                          "rounds_to_stored": True, "n_trades": 184, "n_trades_stored": 184, "selected_matches": True, "verdict_matches": True,
                          "reproduced": {"total_return": 0.09362, "sharpe": 0.37417, "max_drawdown": 0.083135}, "stored": {"total_return": 0.09362, "sharpe": 0.37417, "max_drawdown": 0.083135}}],
        "series": series, "stored_2c": stored, "btc_passers_2c": passers, "configuration_replication": rep.configuration_replication(series, passers, markets),
        "families": families, "overall": rep.overall_verdict(families, series, markets), "beats_hold": rep.beats_hold(series), "shortlist_additions": [],
    }


def test_report_sentences_follow_the_numbers():
    markets = ["A-USDT", "B-USDT"]
    fragile = [_series("A-USDT", [_res("S2", "A-USDT", "4H", "gate", calmar=0.9, passed=True, holdout=-0.03), _res("S1", "A-USDT", "4H", "none", calmar=0.1, passed=False)], hold_holdout=-0.04),
               _series("B-USDT", [_res("S2", "B-USDT", "4H", "gate", calmar=0.2, passed=False), _res("S1", "B-USDT", "4H", "none", calmar=0.1, passed=False)], hold_holdout=-0.02)]
    run = _run(fragile, markets=markets)
    text = render_report(run)
    summary = "\n".join(executive_summary(run))
    assert "Result: robust across markets" in summary and "S2 4H [gate] passed on 1 of 2 new markets (replicated: needs 1)" in summary
    assert "confirmed 0 (none) and contradicted 1 (S2 4H [gate] on A)" in summary
    assert "1 of 2 market-timeframe series the best timing rule beat hold" in summary
    assert "Nothing was confirmed on a new market, so the fleet's shortlist is unchanged" in summary
    for heading in ("## Fixed before the first run", "## Reproduction of Sprint 2c", "## The primary test", "## Family verdicts", "## Summary",
                    "## Sprint 2c's own numbers", "## Against the controls", "## The untouched 12 months", "### Every opening of the holdout (ledger)",
                    "## Paper-fleet shortlist", "## Owner decisions", "## Method notes and caveats"):
        assert heading in text, heading
    assert "| A-USDT | S2 4H [gate] | +9.0% |" not in text  # the holdout table shows the holdout return, not the Calmar
    assert "| A-USDT | S2 4H [gate] | -3.0% |" in text and "contradicted |" in text
    assert "1 of 1 reproduced" in text and "**Nothing here authorizes paper, demo or live trading.**" in text
    # Nothing passing: the BTC-specific wording, no holdout opened, the shortlist unchanged.
    none = [_series("A-USDT", [_res("S2", "A-USDT", "4H", "gate", calmar=0.2, passed=False)]), _series("B-USDT", [_res("S2", "B-USDT", "4H", "gate", calmar=0.1, passed=False)])]
    run0 = _run(none, markets=markets)
    s0 = "\n".join(executive_summary(run0))
    assert "Result: BTC-specific" in s0 and "Nothing passed walk-forward on a new market" in s0 and "S2: BTC-specific (passes on 0 of 2 markets)" in s0
    assert "Unchanged: no configuration was both a walk-forward passer and confirmed" in render_report(run0)
    # Confirmed: the fleet sentence names the addition.
    good = [_series("A-USDT", [_res("S2", "A-USDT", "4H", "gate", calmar=0.9, passed=True, holdout=0.03)]), _series("B-USDT", [_res("S2", "B-USDT", "4H", "gate", calmar=0.9, passed=True, holdout=0.02)])]
    run2 = _run(good, markets=markets)
    run2["shortlist_additions"] = rep.shortlist_additions(good, source={"study": "R12 replication"})
    s2 = "\n".join(executive_summary(run2))
    assert "2 confirmed configuration(s) were appended" in s2 and "S2 A-USDT 4H, S2 B-USDT 4H" in s2 and "confirmed 2 (" in s2


# -- the command line -------------------------------------------------------------------------------------------

def _cli():
    spec = importlib.util.spec_from_file_location("run_replication_v1d", ROOT / "scripts" / "run_replication_v1d.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_cli_opens_the_holdout_only_for_the_full_preregistered_study(tmp_path, capsys):
    cli = _cli()
    prereg = tmp_path / "prereg.json"
    rep.preregister(_PreregRest(VOLUMES), prereg)
    common = ["--preregistration", str(prereg), "--lake-dir", str(tmp_path / "lake"), "--study-lake-dir", str(tmp_path / "study"), "--report", "-", "--json", "-"]
    for argv in (["--evaluate-holdout", "--quick"], ["--evaluate-holdout", "--markets", "XRP-USDT"], ["--evaluate-holdout", "--families", "S1"],
                 ["--evaluate-holdout", "--timeframes", "4H"], ["--evaluate-holdout", "--no-control"], ["--evaluate-holdout", "--holdout-ledger", "-"],
                 ["--evaluate-holdout", "--skip-reproduction"], ["--markets", "BCH-USDT"]):
        assert cli.main(argv + common) == 2, argv
    assert cli.main(["--preregister", "--preregistration", str(prereg)]) == 2  # written once
    assert cli.main(["--quick", "--preregistration", str(tmp_path / "missing.json"), "--report", "-", "--json", "-"]) == 2
    err = capsys.readouterr().err
    assert "full pre-registered study" in err and "not pre-registered markets" in err and "run --preregister first" in err


def test_a_shortlist_amendment_the_fleet_cannot_load_is_rolled_back(tmp_path):
    """The fleet refuses a shortlist it cannot reconcile with its results files, so an amendment it cannot read is never left in place."""
    cli = _cli()
    path = tmp_path / "shortlist.json"
    original = (ROOT / "docs" / "research" / "paper_fleet_shortlist_v1c.json").read_text(encoding="utf-8")
    path.write_text(original, encoding="utf-8")
    series = [_series("A-USDT", [_res("S2", "A-USDT", "4H", "gate", calmar=0.9, passed=True, holdout=0.02)])]
    additions = rep.shortlist_additions(series, source={"study": "R12 replication"})
    note = cli._apply_shortlist_additions(path, additions)
    assert note.startswith("NOT applied") and path.read_text(encoding="utf-8") == original


def test_recorded_additions_can_be_applied_later_without_a_new_run(tmp_path):
    cli = _cli()
    shortlist = tmp_path / "shortlist.json"
    original = (ROOT / "docs" / "research" / "paper_fleet_shortlist_v1c.json").read_text(encoding="utf-8")
    shortlist.write_text(original, encoding="utf-8")
    series = [_series("A-USDT", [_res("S2", "A-USDT", "4H", "gate", calmar=0.9, passed=True, holdout=0.02)])]
    run = _run(series, markets=["A-USDT"])
    run["shortlist_additions"] = rep.shortlist_additions(series, source={"study": "R12 replication"})
    results = tmp_path / "results.json"
    results.write_text(json.dumps(run), encoding="utf-8")
    report = tmp_path / "report.md"
    # The fleet cannot reconcile a row from another study with its results file: rolled back, exit 1, the report says so.
    assert cli.main(["--apply-shortlist-from-json", str(results), "--shortlist", str(shortlist), "--report", str(report)]) == 1
    assert shortlist.read_text(encoding="utf-8") == original
    assert "NOT applied" in json.loads(results.read_text(encoding="utf-8"))["shortlist_note"] and "NOT applied" in report.read_text(encoding="utf-8")
    run["shortlist_additions"] = []
    results.write_text(json.dumps(run), encoding="utf-8")
    assert cli.main(["--apply-shortlist-from-json", str(results), "--shortlist", str(shortlist), "--report", "-"]) == 0
    assert cli.main(["--apply-shortlist-from-json", str(results), "--shortlist", "-", "--report", "-"]) == 0


def test_render_from_json_rebuilds_the_report(tmp_path):
    cli = _cli()
    markets = ["A-USDT"]
    series = [_series("A-USDT", [_res("S2", "A-USDT", "4H", "gate", calmar=0.2, passed=False)])]
    run = _run(series, markets=markets)
    src = tmp_path / "results.json"
    src.write_text(json.dumps(run), encoding="utf-8")
    out = tmp_path / "report.md"
    assert cli.main(["--render-from-json", str(src), "--report", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Replication v1d")
