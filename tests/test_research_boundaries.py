"""The research sandbox must never import the trading, exchange or supervisor code paths."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = (
    "app.execution",
    "app.exchange",
    "app.shadow",
    "app.okx",
    "app.notify",
    "app.paper",
    "app.live",
    "app.api",
    "app.strategy.registry",  # candidates are never auto-registered for the demo runtime
    "anthropic",
    "openai",
)
IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w\.]+)\s+import|import\s+([\w\.]+))", re.MULTILINE)


def _imports(path: Path):
    text = path.read_text(encoding="utf-8")
    for match in IMPORT_RE.finditer(text):
        yield match.group(1) or match.group(2)


def test_research_package_and_runner_stay_in_the_sandbox():
    files = list((ROOT / "research").rglob("*.py")) + [ROOT / "scripts" / "run_research.py", ROOT / "scripts" / "run_research_v1b.py", ROOT / "scripts" / "run_research_v1c.py",
                                                       ROOT / "scripts" / "run_paper_fleet.py", ROOT / "scripts" / "run_allocator_v2.py",
                                                       ROOT / "scripts" / "run_long_short_study.py", ROOT / "scripts" / "run_replication_v1d.py",
                                                       ROOT / "scripts" / "run_research_round_1.py", ROOT / "scripts" / "run_research_round_2.py",
                                                       ROOT / "scripts" / "run_trader_policy_v1.py", ROOT / "scripts" / "run_research_round_3.py"]
    assert files
    for path in files:
        for module in _imports(path):
            for forbidden in FORBIDDEN:
                assert not (module == forbidden or module.startswith(forbidden + ".")), (
                    f"{path.relative_to(ROOT)} imports {module} (forbidden: {forbidden})"
                )


def test_the_allocator_code_imports_no_risk_database_or_broker_code_either():
    """Plan row R5b: allocator v2 stays research code; `app/risk` (the demo and live risk manager) is never touched or used."""
    stricter = FORBIDDEN + ("app.risk", "app.db", "app.broker", "app.backtest")
    for path in [ROOT / "research" / "allocator.py", ROOT / "research" / "allocator_study.py", ROOT / "scripts" / "run_allocator_v2.py",
                 *sorted((ROOT / "research" / "paper_fleet").glob("*.py"))]:
        for module in _imports(path):
            for forbidden in stricter:
                assert not (module == forbidden or module.startswith(forbidden + ".")), f"{path.relative_to(ROOT)} imports {module}"
    for path in (ROOT / "app").rglob("*.py"):
        assert "research.allocator" not in path.read_text(encoding="utf-8"), path


def test_research_is_not_wired_into_the_live_registry():
    for name in ("registry.py", "library.py"):
        for module in _imports(ROOT / "app" / "strategy" / name):
            assert not module.startswith("research"), f"app/strategy/{name} imports {module}"


def test_the_long_short_design_study_stays_paper_only():
    """Plan row R9: the long/short study is research code — no risk, database, broker, execution or exchange code, and the
    trading runtime never imports it. Its only network access is the GET-only public client of the data lake."""
    stricter = FORBIDDEN + ("app.risk", "app.db", "app.broker", "app.backtest")
    study_files = [ROOT / "research" / name for name in ("longshort.py", "longshort_data.py", "longshort_study.py", "report_longshort.py")]
    study_files += [ROOT / "research" / "strategies" / "shorts.py", ROOT / "scripts" / "run_long_short_study.py"]
    for path in study_files:
        assert path.exists(), path
        modules = list(_imports(path))
        for module in modules:
            for forbidden in stricter:
                assert not (module == forbidden or module.startswith(forbidden + ".")), f"{path.relative_to(ROOT)} imports {module}"
        network = [m for m in modules if m.split(".")[0] in ("requests", "httpx", "urllib", "websocket", "websockets", "aiohttp", "socket")]
        assert not network, f"{path.relative_to(ROOT)} opens its own network path: {network}"
    for path in (ROOT / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "research.longshort" not in text and "research.strategies.shorts" not in text, path


def test_the_replication_study_stays_in_the_sandbox_and_widens_no_app_allowlist():
    """Plan row R12: the replication study is research code. Its collectors reach the network only through the data lake's GET-only
    public clients; the trading runtime never imports it; the app's instrument and symbol allowlists are not widened for it."""
    stricter = FORBIDDEN + ("app.risk", "app.db", "app.broker", "app.backtest")
    study_files = [ROOT / "research" / name for name in ("markets.py", "replication.py", "replication_data.py", "report_replication.py")]
    study_files.append(ROOT / "scripts" / "run_replication_v1d.py")
    for path in study_files:
        assert path.exists(), path
        modules = list(_imports(path))
        for module in modules:
            for forbidden in stricter:
                assert not (module == forbidden or module.startswith(forbidden + ".")), f"{path.relative_to(ROOT)} imports {module}"
        network = [m for m in modules if m.split(".")[0] in ("requests", "httpx", "urllib", "websocket", "websockets", "aiohttp", "socket")]
        assert not network, f"{path.relative_to(ROOT)} opens its own network path: {network}"
    text = "\n".join(p.read_text(encoding="utf-8") for p in study_files)
    for needle in ("/api/v5/trade", "/api/v5/account", "/api/v5/asset", "x-simulated-trading", "OK-ACCESS", "place_order", ".post(", "requests.post"):
        assert needle not in text, needle
    paths = set(re.findall(r'"(/api/v5/[\w/\-]+)"', text))
    assert paths <= {"/api/v5/market/candles", "/api/v5/market/history-candles", "/api/v5/market/tickers"}, paths
    for path in (ROOT / "app").rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        assert "research.replication" not in content and "research.markets" not in content, path
    from app.datalake.binance_public import SYMBOLS
    from app.okx.client import ALLOWED_INSTRUMENTS

    assert ALLOWED_INSTRUMENTS == ("BTC-USDT", "ETH-USDT") and SYMBOLS == ("BTCUSDT", "ETHUSDT")


def test_research_round_1_stays_in_the_sandbox_and_opens_no_network_path():
    """Plan row R13: research round 1 is research code — no risk, database, broker, execution or exchange code, no network path of its
    own (it reads the frozen study lake), and the trading runtime never imports it or its rules."""
    stricter = FORBIDDEN + ("app.risk", "app.db", "app.broker", "app.backtest")
    study_files = [ROOT / "research" / name for name in ("round1.py", "report_round1.py")]
    study_files += [ROOT / "research" / "strategies" / "round1.py", ROOT / "scripts" / "run_research_round_1.py"]
    for path in study_files:
        assert path.exists(), path
        modules = list(_imports(path))
        for module in modules:
            for forbidden in stricter:
                assert not (module == forbidden or module.startswith(forbidden + ".")), f"{path.relative_to(ROOT)} imports {module}"
        network = [m for m in modules if m.split(".")[0] in ("requests", "httpx", "urllib", "websocket", "websockets", "aiohttp", "socket")]
        assert not network, f"{path.relative_to(ROOT)} opens its own network path: {network}"
    text = chr(10).join(p.read_text(encoding="utf-8") for p in study_files)
    for needle in ("/api/v5/", "x-simulated-trading", "OK-ACCESS", "place_order", ".post(", "requests.post", "OKXPublicRest("):
        assert needle not in text, needle
    for path in (ROOT / "app").rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        assert "research.round1" not in content and "research.strategies.round1" not in content, path


def test_research_round_2_stays_in_the_sandbox_and_opens_no_network_path():
    """Plan row R16: research round 2 is research code - no risk, database, broker, execution or exchange code, no network path of its
    own (it reads a frozen study lake built from the research lake), and the trading runtime never imports it or its rules."""
    stricter = FORBIDDEN + ("app.risk", "app.db", "app.broker", "app.backtest")
    study_files = [ROOT / "research" / name for name in ("round2.py", "report_round2.py")]
    study_files += [ROOT / "research" / "strategies" / "round2.py", ROOT / "scripts" / "run_research_round_2.py"]
    for path in study_files:
        assert path.exists(), path
        modules = list(_imports(path))
        for module in modules:
            for forbidden in stricter:
                assert not (module == forbidden or module.startswith(forbidden + ".")), f"{path.relative_to(ROOT)} imports {module}"
        network = [m for m in modules if m.split(".")[0] in ("requests", "httpx", "urllib", "websocket", "websockets", "aiohttp", "socket")]
        assert not network, f"{path.relative_to(ROOT)} opens its own network path: {network}"
    text = chr(10).join(p.read_text(encoding="utf-8") for p in study_files)
    for needle in ("/api/v5/", "x-simulated-trading", "OK-ACCESS", "place_order", ".post(", "requests.post", "OKXPublicRest("):
        assert needle not in text, needle
    for path in (ROOT / "app").rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        assert "research.round2" not in content and "research.strategies.round2" not in content, path


def test_research_round_3_stays_in_the_sandbox_and_opens_no_network_path():
    """Plan row R19: research round 3 is research code - no risk, database, broker, execution or exchange code, no network path of its
    own (it reads a frozen study lake built from the research lake), and the trading runtime never imports it or its rules."""
    stricter = FORBIDDEN + ("app.risk", "app.db", "app.broker", "app.backtest")
    study_files = [ROOT / "research" / name for name in ("round3.py", "report_round3.py")]
    study_files += [ROOT / "research" / "strategies" / "round3.py", ROOT / "scripts" / "run_research_round_3.py"]
    for path in study_files:
        assert path.exists(), path
        modules = list(_imports(path))
        for module in modules:
            for forbidden in stricter:
                assert not (module == forbidden or module.startswith(forbidden + ".")), f"{path.relative_to(ROOT)} imports {module}"
        network = [m for m in modules if m.split(".")[0] in ("requests", "httpx", "urllib", "websocket", "websockets", "aiohttp", "socket")]
        assert not network, f"{path.relative_to(ROOT)} opens its own network path: {network}"
    text = chr(10).join(p.read_text(encoding="utf-8") for p in study_files)
    for needle in ("/api/v5/", "x-simulated-trading", "OK-ACCESS", "place_order", ".post(", "requests.post", "OKXPublicRest("):
        assert needle not in text, needle
    for path in (ROOT / "app").rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        assert "research.round3" not in content and "research.strategies.round3" not in content, path


def test_the_r17_positioning_feed_stays_in_the_sandbox_and_widens_no_app_allowlist():
    """Plan row R17: the research-side positioning feed reaches the network only through the data lake's GET-only public client (it is
    handed one, never builds one), names no endpoint of its own (the app's path constants and parsers are reused), is bounded to the
    replication markets' swaps, and the app's swap, instrument and symbol allowlists are not widened for it."""
    stricter = FORBIDDEN + ("app.risk", "app.db", "app.broker", "app.backtest")
    path = ROOT / "research" / "positioning_data.py"
    assert path.exists()
    modules = list(_imports(path))
    for module in modules:
        for forbidden in stricter:
            assert not (module == forbidden or module.startswith(forbidden + ".")), f"{path.relative_to(ROOT)} imports {module}"
    network = [m for m in modules if m.split(".")[0] in ("requests", "httpx", "urllib", "websocket", "websockets", "aiohttp", "socket")]
    assert not network, f"{path.relative_to(ROOT)} opens its own network path: {network}"
    text = path.read_text(encoding="utf-8")
    for needle in ("/api/v5/trade", "/api/v5/account", "/api/v5/asset", "x-simulated-trading", "OK-ACCESS", "place_order", ".post(", "requests.post",
                   "OKXPublicRest("):
        assert needle not in text, needle
    assert set(re.findall(r'"(/api/v5/[\w/\-]+)"', text)) == set()  # the paths come from app.datalake.derivatives, not from literals here
    for p in (ROOT / "app").rglob("*.py"):
        assert "research.positioning_data" not in p.read_text(encoding="utf-8"), p
    from app.datalake.binance_public import SYMBOLS
    from app.datalake.derivatives import SWAP_INSTRUMENTS
    from app.okx.client import ALLOWED_INSTRUMENTS
    from research.positioning_data import RESEARCH_SWAPS

    assert SWAP_INSTRUMENTS == ("BTC-USDT-SWAP", "ETH-USDT-SWAP") and ALLOWED_INSTRUMENTS == ("BTC-USDT", "ETH-USDT") and SYMBOLS == ("BTCUSDT", "ETHUSDT")
    assert RESEARCH_SWAPS and not set(RESEARCH_SWAPS) & set(SWAP_INSTRUMENTS)


def test_the_breadth_study_stays_in_the_sandbox_widens_no_allowlist_and_opens_no_network_path():
    """Plan row R20: the breadth book and the rotation test are research code - no risk, database, broker, execution or exchange code, no
    network path of their own (they read a frozen study lake built from the research lake), the app's instrument allowlist is untouched, and
    the trading runtime and the paper fleet never import them."""
    stricter = FORBIDDEN + ("app.risk", "app.db", "app.broker", "app.backtest")
    study_files = [ROOT / "research" / name for name in ("breadth.py", "breadth_study.py", "report_breadth.py")] + [ROOT / "scripts" / "run_breadth_v1.py"]
    for path in study_files:
        assert path.exists(), path
        modules = list(_imports(path))
        for module in modules:
            for forbidden in stricter:
                assert not (module == forbidden or module.startswith(forbidden + ".")), f"{path.relative_to(ROOT)} imports {module}"
        network = [m for m in modules if m.split(".")[0] in ("requests", "httpx", "urllib", "websocket", "websockets", "aiohttp", "socket")]
        assert not network, f"{path.relative_to(ROOT)} opens its own network path: {network}"
    text = chr(10).join(p.read_text(encoding="utf-8") for p in study_files)
    for needle in ("/api/v5/", "x-simulated-trading", "OK-ACCESS", "place_order", ".post(", "requests.post", "OKXPublicRest("):
        assert needle not in text, needle
    for path in list((ROOT / "app").rglob("*.py")) + list((ROOT / "research" / "paper_fleet").rglob("*.py")):
        content = path.read_text(encoding="utf-8")
        assert "research.breadth" not in content and "report_breadth" not in content, path
    from app.okx.client import ALLOWED_INSTRUMENTS

    assert ALLOWED_INSTRUMENTS == ("BTC-USDT", "ETH-USDT")


def test_the_tokenized_stocks_collector_stays_in_the_sandbox_reads_only_public_pages_and_widens_no_allowlist():
    """Plan row R21: the tokenized-stocks collector is research code - no risk, database, broker, execution or exchange code; its only
    network path is the data lake's GET-only public client on six public endpoints; it never carries the demo header; the app's
    instrument allowlist stays BTC/ETH; the app and the paper fleet never import it."""
    stricter = FORBIDDEN + ("app.risk", "app.db", "app.broker", "app.backtest")
    files = [ROOT / "research" / "xstocks_data.py", ROOT / "scripts" / "collect_xstocks.py"]
    for path in files:
        assert path.exists(), path
        modules = list(_imports(path))
        for module in modules:
            for forbidden in stricter:
                assert not (module == forbidden or module.startswith(forbidden + ".")), f"{path.relative_to(ROOT)} imports {module}"
        network = [m for m in modules if m.split(".")[0] in ("requests", "httpx", "urllib", "websocket", "websockets", "aiohttp", "socket")]
        assert not network, f"{path.relative_to(ROOT)} opens its own network path: {network}"
    text = chr(10).join(p.read_text(encoding="utf-8") for p in files)
    for needle in ("/api/v5/trade", "/api/v5/account", "/api/v5/asset", "x-simulated-trading", "OK-ACCESS", "place_order", ".post(", "requests.post",
                   "headers="):
        assert needle not in text, needle
    paths = set(re.findall(r'"(/api/v5/[\w/\-]+)"', text))
    assert paths == {"/api/v5/public/instruments", "/api/v5/market/tickers", "/api/v5/market/candles", "/api/v5/market/history-candles",
                     "/api/v5/market/books", "/api/v5/public/price-limit"}, paths
    for path in list((ROOT / "app").rglob("*.py")) + list((ROOT / "research" / "paper_fleet").rglob("*.py")):
        content = path.read_text(encoding="utf-8")
        assert "xstocks" not in content, path
    from app.datalake.okx_public_rest import assert_public_path
    from app.okx.client import ALLOWED_INSTRUMENTS

    assert ALLOWED_INSTRUMENTS == ("BTC-USDT", "ETH-USDT")
    for p in paths:
        assert_public_path(p)  # every path the collector names is one the GET-only client would accept


def test_the_fill_cost_replay_stays_in_the_sandbox_lists_through_the_public_client_and_downloads_only_from_the_pinned_host():
    """Plan row R22: the fill-cost replay is research code - no risk, database, broker, execution or exchange code. The archive LISTING goes
    through the data lake's GET-only public client (one public path); the archive FILES come from a GET-only downloader that the module
    never builds a network path for itself (the command line hands it a session), bound to https://static.okx.com/cdn/ and to the URLs
    the listing returned, following no redirect and sending no header; the app and the paper fleet never import it; the allowlist is unchanged."""
    stricter = FORBIDDEN + ("app.risk", "app.db", "app.broker", "app.backtest")
    module = ROOT / "research" / "fill_replay.py"
    script = ROOT / "scripts" / "run_fill_replay.py"
    for path in (module, script):
        assert path.exists(), path
        for m in _imports(path):
            for forbidden in stricter:
                assert not (m == forbidden or m.startswith(forbidden + ".")), f"{path.relative_to(ROOT)} imports {m}"
    network = [m for m in _imports(module) if m.split(".")[0] in ("requests", "httpx", "urllib", "websocket", "websockets", "aiohttp", "socket")]
    assert not network, f"research/fill_replay.py opens its own network path: {network}"
    text = module.read_text(encoding="utf-8") + chr(10) + script.read_text(encoding="utf-8")
    for needle in ("/api/v5/trade", "/api/v5/account", "/api/v5/asset", "x-simulated-trading", "OK-ACCESS", "place_order", ".post(", "requests.post",
                   "headers=", "auth=", "cookies=", "allow_redirects=True"):
        assert needle not in text, needle
    assert set(re.findall(r'"(/api/v5/[\w/\-]+)"', text)) == {"/api/v5/public/market-data-history"}
    assert set(re.findall(r"\b((?:[a-z0-9\-]+\.)+okx\.com)\b", text)) == {"static.okx.com"}  # the listing host lives in the public client, not here
    assert "allow_redirects=False" in module.read_text(encoding="utf-8")
    for p in list((ROOT / "app").rglob("*.py")) + list((ROOT / "research" / "paper_fleet").rglob("*.py")):
        assert "fill_replay" not in p.read_text(encoding="utf-8"), p
    from app.datalake.okx_public_rest import assert_public_path
    from app.okx.client import ALLOWED_INSTRUMENTS
    from research.fill_replay import ARCHIVE_HOST, FillReplayError, MARKET_DATA_HISTORY_PATH, validate_archive_url

    assert ALLOWED_INSTRUMENTS == ("BTC-USDT", "ETH-USDT") and ARCHIVE_HOST == "static.okx.com"
    assert_public_path(MARKET_DATA_HISTORY_PATH)
    validate_archive_url("https://static.okx.com/cdn/okex/traderecords/trades/daily/20261030/BTC-USDT-trades-2026-10-30.zip?v=1001")
    for bad in ("https://www.okx.com/cdn/okex/x.zip", "http://static.okx.com/cdn/okex/x.zip", "https://static.okx.com.evil.example/cdn/x.zip",
                "https://static.okx.com/api/v5/trade/order"):
        with pytest.raises(FillReplayError):
            validate_archive_url(bad)
