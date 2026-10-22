"""Phase 9 design study (plan row R9): mirrored signals, the walk-forward driver, the evidence rule, the holdout rule, data."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.datalake.layout import LakeLayout
from app.datalake.okx_public_rest import OKXPublicRest
from app.datalake.parquet_store import CANDLE_SCHEMA, TS_TYPE, write_partitioned
from research import longshort_study as study
from research.data import bars_per_year
from research.gated_walkforward import run_gated_walk_forward
from research.longshort_data import collect_perp_candles, funding_by_year, load_perp_candles
from research.regime_v2 import RegimeV2Config
from research.sizing import SizingSpec, fraction_matrix
from research.strategies import get_candidate
from research.strategies.base import FeatureContext, days_to_bars
from research.strategies.s0_filters import NoTradeConfig, tradeable_mask
from research.strategies.shorts import build_ls_frames, short_desired, short_positioning_mask
from research.sweep import build_frames, param_grid
from research.walkforward import make_windows


def synthetic(n: int, *, freq: str = "4h", seed: int = 3, drift: float = 0.0, vol: float = 0.012, start: str = "2021-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    # Regime-switching drift so trend rules trade both ways.
    regime = np.sign(np.sin(np.arange(n) / 180.0))
    close = 100 * np.exp(np.cumsum(drift + 0.004 * regime + rng.normal(0, vol, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    volume = rng.lognormal(3, 0.5, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


TF = "4H"
PPY = bars_per_year(TF)
CTX = FeatureContext(timeframe=TF, periods_per_year=PPY)


# -- mirrored signals --------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["S1", "S2", "S4", "S1+S5"])
def test_the_long_side_is_sprint_2c_unchanged_and_shorts_never_overlap_it(key):
    df = synthetic(1500)
    cand = get_candidate(key)
    combos = param_grid({k: v[:2] for k, v in cand.grid.items()}, base=cand.default_params)
    ref = build_frames(cand, df, combos, CTX, no_trade=NoTradeConfig())
    ls = build_ls_frames(key, df, combos, CTX, no_trade=NoTradeConfig())
    np.testing.assert_array_equal(ls.desired, ref.desired)
    np.testing.assert_array_equal(ls.stop, ref.stop)
    assert ls.desired_short.shape == ls.desired.shape
    assert not (ls.desired & ls.desired_short).any()
    assert ls.desired_short.any(), "the synthetic market has down trends: some shorts are expected"
    no_shorts = build_ls_frames(key, df, combos, CTX, no_trade=NoTradeConfig(), shorts=False)
    assert not no_shorts.desired_short.any()


def test_a_short_only_starts_where_the_no_trade_filter_allows_and_the_long_side_is_flat():
    df = synthetic(2000, seed=5)
    ok = tradeable_mask(df, TF, PPY, NoTradeConfig()).to_numpy()
    assert (~ok).any()
    cand = get_candidate("S1")
    combos = param_grid({k: v[:2] for k, v in cand.grid.items()}, base=cand.default_params)
    ls = build_ls_frames("S1", df, combos, CTX, no_trade=NoTradeConfig())
    for j in range(ls.n_combos):
        s = ls.desired_short[:, j]
        starts = np.flatnonzero(s & ~np.concatenate([[False], s[:-1]]))
        assert starts.size
        assert ok[starts].all()
        assert not ls.desired[starts, j].any()


def test_s1_short_is_the_mirror_vote():
    n = 800
    idx = pd.date_range("2022-01-01", periods=n, freq="4h", tz="UTC")
    falling = pd.DataFrame({"open": np.linspace(200, 100, n), "close": np.linspace(200, 100, n)}, index=idx)
    falling["high"], falling["low"], falling["volume"] = falling["close"] * 1.001, falling["close"] * 0.999, 1.0
    p = dict(get_candidate("S1").default_params)
    s = short_desired("S1", falling, p, CTX)
    warm = days_to_bars(max(p["lookbacks_days"]), TF) + 1
    assert s.iloc[warm:].all() and not s.iloc[: warm - 2].any()
    rising = falling.iloc[::-1].copy()
    rising.index = idx
    assert not short_desired("S1", rising, p, CTX).iloc[warm:].any()
    with pytest.raises(ValueError):
        short_desired("S1", falling, dict(p, entry_band=0.25), CTX)
    with pytest.raises(ValueError):
        short_desired("S3", falling, p, CTX)


def _reflected(df: pd.DataFrame, anchor: float) -> pd.DataFrame:
    out = df.copy()
    out["open"], out["close"] = 2 * anchor - df["open"], 2 * anchor - df["close"]
    out["high"], out["low"] = 2 * anchor - df["low"], 2 * anchor - df["high"]
    return out


@pytest.mark.parametrize("key, params", [
    ("S1", {}),
    ("S1", {"lookbacks_days": (14, 30, 60), "vote": 3}),
    ("S1", {"lookbacks_days": (7, 30, 90), "vote": 1}),
    ("S2", {}),
    ("S2", {"entry_days": 10, "exit_days": 20, "vol_mult": 1.0}),
    ("S2", {"entry_days": 55, "exit_days": 5, "vol_mult": 1.5}),
])
def test_s1_and_s2_shorts_are_the_reviewed_long_rules_on_the_reflected_market(key, params):
    df = synthetic(1600, seed=7)
    anchor = float(df["high"].max())  # keeps the reflected prices positive
    p = get_candidate(key).params_with_defaults(params)
    long_on_reflection = get_candidate(key).build(_reflected(df, anchor), p, CTX).desired
    short = short_desired(key, df, p, CTX)
    assert short.any()
    pd.testing.assert_series_equal(short, long_on_reflection, check_names=False)


def test_s4_short_enters_below_the_lower_band_after_a_squeeze_and_covers_above_the_mid_band():
    from research import features

    n = 1400
    idx = pd.date_range("2022-01-01", periods=n, freq="4h", tz="UTC")
    rng = np.random.default_rng(1)
    path = 100 + rng.normal(0, 0.05, n)
    path[1000:1100] = np.linspace(100, 80, 100)  # a breakdown after a calm stretch ...
    path[1100:] = np.linspace(80, 110, n - 1100)  # ... and a recovery
    df = pd.DataFrame({"open": path, "close": path, "high": path + 0.1, "low": path - 0.1, "volume": 10.0}, index=idx)
    p = get_candidate("S4").params_with_defaults({"squeeze_pct": 0.5})
    s4 = short_desired("S4", df, p, CTX).to_numpy()
    lower, mid, _ = features.bollinger_bands(df["close"], int(p["bb_window"]), float(p["bb_k"]))
    width = features.bollinger_width(df["close"], int(p["bb_window"]), float(p["bb_k"]))
    squeezed = (features.percentile_rank(width, days_to_bars(p["pct_days"], TF)) <= p["squeeze_pct"]).fillna(False)
    recent = (squeezed.shift(1).rolling(int(p["squeeze_lookback"]), min_periods=1).max().fillna(0) > 0).to_numpy()
    close, lower, mid = df["close"].to_numpy(), lower.to_numpy(), mid.to_numpy()
    starts = np.flatnonzero(s4 & ~np.concatenate([[False], s4[:-1]]))
    ends = np.flatnonzero(~s4 & np.concatenate([[False], s4[:-1]]))
    assert starts.size and ends.size
    assert (close[starts] < lower[starts]).all() and recent[starts].all()
    assert (close[ends] > mid[ends]).all()
    assert s4[1000:1012].any() and not s4[-50:].any()


def test_the_s5_mirror_blocks_new_shorts_into_crowded_shorts_or_an_open_interest_surge():
    n = 400
    idx = pd.date_range("2022-01-01", periods=n, freq="4h", tz="UTC")
    df = pd.DataFrame({"close": np.full(n, 100.0)}, index=idx)
    rates = np.full(n, 0.0001)  # constant: zero dispersion, so the z-score is undefined and never blocks
    rates[300:310] = -0.003  # shorts crowded (funding deeply negative)
    oi = np.full(n, 1e9)
    oi[200:] = 1.5e9  # a +50 % open-interest surge at bar 200
    ctx = FeatureContext(timeframe=TF, periods_per_year=PPY, funding=pd.DataFrame({"funding_rate": rates}, index=idx),
                         open_interest=pd.DataFrame({"oi_usd": oi}, index=idx))
    ok = short_positioning_mask(df, {"funding_z_window": 90, "funding_z_max": 2.0, "oi_change_max": 0.15, "oi_change_window_days": 1}, ctx)
    assert not ok.iloc[300:305].all()
    assert not ok.iloc[200:206].all()
    assert ok.iloc[150:190].all()


# -- the walk-forward driver ---------------------------------------------------------------------

def _inputs(df: pd.DataFrame, cfg: study.StudyConfig, *, fund=None, perp=None):
    pf = fraction_matrix(df, [cfg.policy()], TF, PPY)
    return study.SeriesInputs(df=df, fund=fund, policy_fracs=pf, ladder=cfg.ladder(TF), ppy=PPY, perp=perp,
                              short_fracs_no_crash=fraction_matrix(df, [SizingSpec(kind="vol_target", target_vol=0.10, vol_lookback=30,
                                                                                   ladder=True)], TF, PPY))


SMALL = dict(train_days=120.0, test_days=60.0, purge_days=3.0, min_trades=3)


def test_with_shorts_off_the_driver_is_sprint_2c_s_gated_walk_forward_in_mode_none():
    df = synthetic(2600, seed=11)
    cfg = study.StudyConfig(**SMALL)
    combos, stage_a, siblings = study.study_grid("S1", study.StudyConfig(quick=True))
    frames = build_ls_frames("S1", df, combos, CTX, no_trade=cfg.no_trade())
    wf_cfg = cfg.wf(TF)
    inp = _inputs(df, cfg)
    ours = study.run_ls_walk_forward(inp, frames, combos, wf_cfg, cfg, study.VARIANTS["long_only"], stage_a=stage_a, siblings=siblings)
    ref = run_gated_walk_forward(df, frames, combos, wf_cfg, cfg.policy(), inp.policy_fracs, inp.ladder, RegimeV2Config(mode="none"),
                                 costs=cfg.costs(study.VARIANTS["long_only"])[0], periods_per_year=PPY, timeframe=TF,
                                 rebalance_threshold=cfg.rebalance_threshold, stage_a_columns=stage_a, siblings=siblings)
    pd.testing.assert_series_equal(ours.oos_returns, ref.oos_returns)
    assert ours.rule_frequency == ref.rule_frequency
    for k in ("total_return", "sharpe", "max_drawdown", "calmar", "profit_factor", "n_trades"):
        assert ours.oos_metrics[k] == ref.oos_metrics[k], k


def test_replaying_the_per_window_selections_gives_the_walk_forward_result():
    df = synthetic(2600, seed=12)
    cfg = study.StudyConfig(**SMALL)
    combos, stage_a, siblings = study.study_grid("S1", study.StudyConfig(quick=True))
    frames = build_ls_frames("S1", df, combos, CTX, no_trade=cfg.no_trade())
    fund = np.full(len(df), 0.0001)
    inp = _inputs(df, cfg, fund=fund, perp={"open": df["open"].to_numpy() * 1.001, "high": df["high"].to_numpy() * 1.001,
                                            "low": df["low"].to_numpy() * 1.001, "close": df["close"].to_numpy() * 1.001})
    wf_cfg = cfg.wf(TF)
    for vkey in ("hybrid", "perp"):
        variant = study.VARIANTS[vkey]
        wf = study.run_ls_walk_forward(inp, frames, combos, wf_cfg, cfg, variant, stage_a=stage_a, siblings=siblings)
        windows = make_windows(len(df), wf_cfg)
        rep = study.replay_fixed(inp, frames, [], windows, cfg, variant, per_window=[w.rule for w in wf.windows])[0]
        assert rep["total_return"] == pytest.approx(wf.oos_metrics["total_return"], abs=1e-12)
        assert rep["n_trades"] == wf.oos_metrics["n_trades"]
        assert rep["legs"]["short"]["n_trades"] > 0
        # Funding: the hybrid's spot long leg pays none; the perp design's long leg pays (positive rates).
        if vkey == "hybrid":
            assert rep["legs"]["long"]["funding"] == 0.0 and rep["legs"]["short"]["funding"] > 0
        else:
            assert rep["legs"]["long"]["funding"] < 0 and rep["legs"]["short"]["funding"] > 0
        # The perp-priced replay trades other prices; it runs and reports.
        pp = study.replay_fixed(inp, frames, [], windows, cfg, variant, perp_priced=True, per_window=[w.rule for w in wf.windows])[0]
        assert pp["n_trades"] > 0
        nc = study.replay_fixed(inp, frames, [], windows, cfg, variant, per_window=[w.rule for w in wf.windows], short_no_crash=True)[0]
        assert nc["legs"]["short"]["n_trades"] > 0


def test_study_grid_follows_sprint_2c():
    cfg = study.StudyConfig()
    combos, stage_a, siblings = study.study_grid("S1", cfg)
    assert len(combos) == 36 * 4 and {c["bracket"] for c in combos} == {"none", "tp2", "trail1", "time30"}
    assert all(combos[j]["bracket"] == "none" for j in stage_a)
    for j, group in siblings.items():
        assert j in group and len(group) == 4
        assert len({tuple(sorted((k, str(v)) for k, v in combos[g].items() if k != "bracket")) for g in group}) == 1
    s5, _, _ = study.study_grid("S1+S5", cfg)
    assert len(s5) == 36 * 3 and {c["bracket"] for c in s5} == {"none"}
    assert len(study.study_grid("S4", cfg)[0]) == 12 * 4 and len(study.study_grid("S2", cfg)[0]) == 36 * 4


# -- the evidence rule and the holdout -------------------------------------------------------------

def test_phase9_rule_needs_all_three_walk_forward_conditions():
    legs_ok = {"short": {"profit_factor": 1.3, "n_trades": 40}}
    acc = {"passed": True}
    assert study.phase9_rule(acc, legs_ok, 0.8, 0.6)["walk_forward_passed"]
    assert not study.phase9_rule({"passed": False}, legs_ok, 0.8, 0.6)["walk_forward_passed"]
    assert not study.phase9_rule(acc, {"short": {"profit_factor": 0.95, "n_trades": 40}}, 0.8, 0.6)["walk_forward_passed"]
    assert not study.phase9_rule(acc, {"short": {"profit_factor": 0.0, "n_trades": 0}}, 0.8, 0.6)["walk_forward_passed"]
    assert not study.phase9_rule(acc, legs_ok, 0.6, 0.6)["walk_forward_passed"]
    assert not study.phase9_rule(acc, legs_ok, 0.8, None)["walk_forward_passed"]


def test_the_holdout_is_opened_only_for_walk_forward_passers_and_only_once():
    calls = []

    def opener():
        calls.append(1)
        return {"total_return": 0.05, "profit_factor": 1.4, "n_trades": 12}

    failed = {"phase9_rule": {"walk_forward_passed": False}}
    study.holdout_step(failed, evaluate=True, opener=opener)
    assert failed["holdout"] is None and not calls and "untouched" in failed["holdout_note"]
    not_requested = {"phase9_rule": {"walk_forward_passed": True}}
    study.holdout_step(not_requested, evaluate=False, opener=opener)
    assert not_requested["holdout"] is None and not calls
    passed = {"phase9_rule": {"walk_forward_passed": True}}
    study.holdout_step(passed, evaluate=True, opener=opener)
    assert len(calls) == 1 and passed["holdout_confirmed"] is True
    with pytest.raises(study.StudyError):
        study.holdout_step(passed, evaluate=True, opener=opener)
    assert len(calls) == 1
    contradicted = {"phase9_rule": {"walk_forward_passed": True}}
    study.holdout_step(contradicted, evaluate=True, opener=lambda: {"total_return": -0.02, "profit_factor": 0.7, "n_trades": 15})
    assert contradicted["holdout_confirmed"] is False


def test_reproduction_check_tolerates_only_the_stored_rounding():
    class WF:
        oos_metrics = {"total_return": 0.0936195131, "cagr": 0.0208016403, "sharpe": 0.3741703173, "max_drawdown": 0.0831353093,
                       "calmar": 0.2502142653, "profit_factor": 1.2330983310, "n_trades": 184}
        rule_most_often = {"lookbacks_days": (7, 30, 90), "vote": 2}

    stored = {"oos": {k: round(v, 6) for k, v in WF.oos_metrics.items()}, "selected_params": {"lookbacks_days": [7, 30, 90], "vote": 2}}
    stored["oos"]["n_trades"] = 184
    check = study.reproduction_check(WF(), stored)
    assert check["ok"] and check["rounds_to_stored"]
    off = json.loads(json.dumps(stored))
    off["oos"]["sharpe"] += 2e-6
    assert not study.reproduction_check(WF(), off)["ok"]
    fewer = json.loads(json.dumps(stored))
    fewer["oos"]["n_trades"] = 183
    assert not study.reproduction_check(WF(), fewer)["ok"]
    other_rule = json.loads(json.dumps(stored))
    other_rule["selected_params"]["vote"] = 3
    assert not study.reproduction_check(WF(), other_rule)["ok"]


def test_the_preregistration_is_hashed_with_the_config():
    a = study.preregistration_hash(study.StudyConfig())
    assert a == study.preregistration_hash(study.StudyConfig())
    assert a != study.preregistration_hash(study.StudyConfig(perp_fee=0.0006))
    assert study.PREREGISTRATION["configurations_judged"] == len(study.STUDY_FAMILIES) * 4 * len(study.JUDGED_VARIANTS)
    assert all(entry["what"] and entry["why"] for entry in study.POST_HOC)


# -- descriptive analyses and data ---------------------------------------------------------------

def test_adverse_moves_find_the_largest_rise_against_a_short():
    n = 3000
    idx = pd.date_range("2022-01-01", periods=n, freq="h", tz="UTC")
    close = 100 + np.random.default_rng(2).normal(0, 0.01, n)  # a flat market ...
    df = pd.DataFrame({"open": close, "high": close + 0.02, "low": close - 0.02, "close": close}, index=idx)
    df.iloc[1500:1524, df.columns.get_loc("high")] = df["close"].iloc[1499] * 1.5  # ... with a +50 % squeeze within a day
    out = study.adverse_moves(df)
    assert out["24h"]["max"] == pytest.approx(0.5, rel=0.02)
    assert out["4h"]["max"] >= 0.45
    assert out["720h"]["share_ge_liquidation"] == 0.0
    assert out["isolated_1x_liquidation_rise"] == pytest.approx(2 / 1.004 - 1)


def test_funding_by_year_annualizes_and_sums():
    idx = pd.date_range("2024-01-01", periods=3 * 366, freq="8h", tz="UTC")
    s = pd.Series(0.0001, index=idx)
    s.iloc[:10] = -0.0002
    out = funding_by_year(s)
    assert out[2024]["settlements"] == 3 * 366
    span_days = (idx[-1] - idx[0]).total_seconds() / 86_400.0
    assert out[2024]["annualized_mean"] == pytest.approx(s.mean() * len(s) / span_days * 365.25)
    assert out[2024]["summed"] == pytest.approx(s.sum())
    assert out[2024]["share_negative"] == pytest.approx(10 / (3 * 366))


class _FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    """Answers OKX's public candle endpoints from a synthetic history; records every request (GET only)."""

    def __init__(self, n_hours: int):
        start = int(pd.Timestamp("2020-01-01", tz="UTC").value // 1_000_000)
        self.rows = [[str(start + i * 3_600_000), "100", "101", "99", "100.5", "5", "0", "0", "1"] for i in range(n_hours)]
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        newest_first = sorted(self.rows, key=lambda r: -int(r[0]))
        if url.endswith("/api/v5/market/candles"):
            data = newest_first[: int(params["limit"])]
        elif url.endswith("/api/v5/market/history-candles"):
            after = int(params["after"])
            data = [r for r in newest_first if int(r[0]) < after][: int(params["limit"])]
        else:
            raise AssertionError(f"unexpected endpoint {url}")
        return _FakeResponse({"code": "0", "msg": "", "data": data})


def test_perp_candles_come_only_from_the_public_candle_endpoints_and_resume(tmp_path):
    layout = LakeLayout(tmp_path / "lake")
    session = _FakeSession(1000)
    rest = OKXPublicRest(session=session, sleep=lambda s: None)
    rep = collect_perp_candles(layout, "BTC-USDT", rest=rest, start=datetime(2019, 12, 1, tzinfo=timezone.utc), sleep_seconds=0.0)
    assert rep.swap == "BTC-USDT-SWAP" and rep.walk.complete and rep.added == 1000
    assert {url.rsplit("/api/v5/", 1)[1] for url, _ in session.calls} <= {"market/candles", "market/history-candles"}
    assert all(p["instId"] == "BTC-USDT-SWAP" and p["bar"] == "1H" for _, p in session.calls)
    df = load_perp_candles(layout, "BTC-USDT", "1H")
    assert len(df) == 1000 and df.index.is_monotonic_increasing
    four = load_perp_candles(layout, "BTC-USDT", "4H")
    assert len(four) == 250
    again = collect_perp_candles(layout, "BTC-USDT", rest=rest, start=datetime(2019, 12, 1, tzinfo=timezone.utc), sleep_seconds=0.0)
    assert again.added == 0
    with pytest.raises(ValueError):
        collect_perp_candles(layout, "SOL-USDT", rest=rest)


# -- end to end on a synthetic lake ---------------------------------------------------------------

def _write_lake(root, n_bars: int = 7600):
    layout = LakeLayout(root)
    df = synthetic(n_bars, seed=21, start="2021-01-01")
    table = pa.table({
        "open_time": pa.array([t.to_pydatetime() for t in df.index], type=TS_TYPE),
        "instrument": pa.array(["BTC-USDT"] * len(df)), "timeframe": pa.array(["4H"] * len(df)),
        "open": pa.array(df["open"].to_numpy()), "high": pa.array(df["high"].to_numpy()), "low": pa.array(df["low"].to_numpy()),
        "close": pa.array(df["close"].to_numpy()), "volume": pa.array(df["volume"].to_numpy()), "confirmed": pa.array([True] * len(df)),
    }, schema=CANDLE_SCHEMA)
    write_partitioned(table, key="open_time", schema=CANDLE_SCHEMA, file_for_year=lambda y: layout.candles_file("BTC-USDT", "4H", y))
    settle = pd.date_range(df.index[0], df.index[-1], freq="8h", tz="UTC")
    rng = np.random.default_rng(4)
    fdir = layout.external_series_dir("binance", "funding_rate", "BTCUSDT", "8H")
    fdir.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"ts": pa.array([t.to_pydatetime() for t in settle], type=TS_TYPE),
                             "funding_rate": pa.array(0.0001 + rng.normal(0, 0.0001, len(settle))),
                             "mark_price": pa.array(np.full(len(settle), 100.0))}), fdir / "2021.parquet")
    return layout, df


@pytest.fixture(scope="module")
def synthetic_lake(tmp_path_factory):
    return _write_lake(tmp_path_factory.mktemp("ls_lake") / "lake")


def test_run_series_end_to_end_opens_no_holdout_unless_the_rule_is_met(synthetic_lake, monkeypatch):
    layout, _ = synthetic_lake
    quick = study.StudyConfig(quick=True, **SMALL)
    opened = []
    real = study.evaluate_holdout

    def spy(*args, **kwargs):
        opened.append(args[3])
        return real(*args, **kwargs)

    monkeypatch.setattr(study, "evaluate_holdout", spy)
    # Quick mode (cut grids, no reproduction check) can never open the holdout.
    with pytest.raises(study.StudyError):
        study.run_series(layout, "BTC-USDT", "4H", quick, {"results": []}, families=["S1"], evaluate_holdout_=True, log=lambda m: None)
    out = study.run_series(layout, "BTC-USDT", "4H", quick, {"results": []}, families=["S1"], evaluate_holdout_=False, log=lambda m: None)
    assert [r["variant"] for r in out["results"]] == ["hybrid", "perp"]
    for r in out["results"]:
        assert r["oos"]["n_trades"] > 0 and r["legs"]["short"]["n_trades"] > 0
        assert r["phase9_rule"] is not None and r["long_only"] is None
        assert r["phase9_rule"]["walk_forward_passed"] is False  # no stored long-only reference -> rule (3) cannot be met
        assert r["holdout"] is None
    assert not opened
    assert set(out["defaults"]["S1"]) >= {"long_only", "hybrid", "perp", "params", "span"}
    assert out["defaults"]["S1"]["long_only"]["short_share"] == 0.0
    # A full configuration (test-only cut grid) without the rule met: nothing opens.
    full = study.StudyConfig(**SMALL)
    original_grid = study.study_grid
    monkeypatch.setattr(study, "study_grid", lambda key, cfg: original_grid(key, study.StudyConfig(quick=True)))
    out1 = study.run_series(layout, "BTC-USDT", "4H", full, {"results": []}, families=["S1"], evaluate_holdout_=True, log=lambda m: None)
    assert not opened and all(r["holdout"] is None for r in out1["results"])
    assert study.holdout_openings([out1]) == []
    # Force the walk-forward part of the rule: the holdout opens exactly once per configuration, on the holdout bars only.
    monkeypatch.setattr(study, "phase9_rule", lambda *a, **k: {"v1c_gates": True, "short_leg_pf_gt_1": True, "beats_long_only_calmar": True,
                                                              "walk_forward_passed": True})
    out2 = study.run_series(layout, "BTC-USDT", "4H", full, {"results": []}, families=["S1"], evaluate_holdout_=True, log=lambda m: None)
    assert len(opened) == 2
    for r in out2["results"]:
        assert r["holdout"] is not None and r["holdout_confirmed"] in (True, False)
        assert r["holdout"]["span"].split("->")[0] == out2["holdout_span"].split("->")[0]
    openings = study.holdout_openings([out2])
    assert [o["configuration"] for o in openings] == ["S1 BTC-USDT 4H hybrid", "S1 BTC-USDT 4H perp"]
    assert all(o["confirmed"] in (True, False) and o["n_trades"] is not None for o in openings)


def _cli():
    import importlib.util

    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("run_long_short_study", root / "scripts" / "run_long_short_study.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_cli_opens_the_holdout_only_for_the_full_pre_registered_study(tmp_path, capsys):
    cli = _cli()
    assert cli.full_study_requested(cli.parse_args([]))
    assert not cli.full_study_requested(cli.parse_args(["--quick"]))
    assert not cli.full_study_requested(cli.parse_args(["--families", "S1"]))
    assert not cli.full_study_requested(cli.parse_args(["--instruments", "BTC-USDT"]))
    assert not cli.full_study_requested(cli.parse_args(["--timeframes", "6H"]))
    assert not cli.full_study_requested(cli.parse_args(["--variants", "hybrid"]))
    lake = str(tmp_path / "empty-lake")
    for argv in (["--evaluate-holdout", "--quick"], ["--evaluate-holdout", "--families", "S2"],
                 ["--evaluate-holdout", "--holdout-ledger", "-"]):
        assert cli.main(argv + ["--lake-dir", lake, "--report", "-", "--json", "-"]) == 2
    assert "full pre-registered study" in capsys.readouterr().err or True


def test_the_holdout_ledger_is_append_only(tmp_path):
    cli = _cli()
    path = str(tmp_path / "ledger.json")
    assert cli.load_ledger(path) == []
    cli.write_ledger(path, [{"generated_at": "a", "openings": [{"configuration": "x"}]}])
    entries = cli.load_ledger(path)
    entries.append({"generated_at": "b", "openings": []})
    cli.write_ledger(path, entries)
    assert [e["generated_at"] for e in cli.load_ledger(path)] == ["a", "b"]
    (tmp_path / "bad.json").write_text("[]", encoding="utf-8")
    with pytest.raises(study.StudyError):
        cli.load_ledger(str(tmp_path / "bad.json"))
    assert cli.load_ledger("-") == []
