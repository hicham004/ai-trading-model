"""Plan row R22: the fill-cost replay (the listing, the host-pinned downloader, the parsers, the book, the arithmetic, the replay, the CLI)."""

from __future__ import annotations

import hashlib
import io
import json
import math
import tarfile
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from research import fill_replay as fr

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "fill_replay" / "listing_2026-11-05.json").read_text(encoding="utf-8"))
HOST = "https://static.okx.com/cdn/okex/traderecords"


def _ms(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


# -- synthetic archives --------------------------------------------------------------------------------------------

def zip_csv_bytes(member: str, header, rows) -> bytes:
    buf = io.BytesIO()
    text = ",".join(header) + "\n" + "".join(",".join(str(v) for v in r) + "\n" for r in rows)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, text)
    return buf.getvalue()


def targz_bytes(member: str, lines) -> bytes:
    data = "\n".join(json.dumps(ln, separators=(",", ":")) for ln in lines).encode("utf-8") + b"\n"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        info = tarfile.TarInfo(member)
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def archive_file(instrument: str, kind: str, day: date, payload: bytes) -> fr.ArchiveFile:
    what = {"trades": "trades", "candles_1m": "candlesticks", "book_400": "L2orderbook-400lv"}[kind]
    ext = "tar.gz" if kind == "book_400" else "zip"
    name = f"{instrument}-{what}-{day.isoformat()}.{ext}"
    url = f"{HOST}/{what}/daily/{day:%Y%m%d}/{name}" + ("" if kind == "book_400" else "?v=1001")
    return fr.ArchiveFile(instrument, kind, day, name, round(len(payload) / 1048576, 2), url, fr._utc_ms(day))


class FakeResponse:
    def __init__(self, payload: bytes, status: int = 200):
        self.status_code = status
        self._payload = payload
        self.closed = False

    def iter_content(self, chunk_size):
        for i in range(0, len(self._payload), chunk_size):
            yield self._payload[i:i + chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    """Serves bytes by URL; records every call and its keyword arguments."""

    def __init__(self, payloads, *, status=200, corrupt=()):
        self.payloads = dict(payloads)
        self.status = status
        self.corrupt = set(corrupt)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        payload = self.payloads[url]
        if url in self.corrupt:
            payload = payload[: len(payload) // 2]
        return FakeResponse(payload, self.status)


def synthetic_day(instrument="BTC-USDT", day=date(2026, 10, 30)):
    """Two book days (day, day + 1) with the trades and candles of their UTC+8 files, built around one scripted boundary.

    Book: bids 99.9 x 20 / 99.8 x 50 / 99.7 x 500, asks 100.1 x 20 / 100.2 x 50 / 100.3 x 500 from the 00:00 snapshot. At 03:59:59 the
    ask touch shrinks to 0.05 (5 USDT); at 04:00:00.200 it is restored. Trades: one every minute at 100.0 (alternating taker side),
    the first after 04:00 at 04:00:00.500; at 04:05 a sell prints at 99.85 (through the bid); at 04:10 and 04:11 buys of 20 and 15 print
    at the ask 100.1. Candles: 100.0 flat, except the 03:59 minute closes at 100.05 and the 04:00 minute opens at 100.02.
    """
    d0 = fr._utc_ms(day)
    files = {}
    # trades and candles: files named day and day + 1 (UTC+8 days), one more trades file for the tail
    for file_day in (day, day + timedelta(days=1), day + timedelta(days=2)):
        start, end = fr.file_span_ms("trades", file_day)
        rows = []
        candles = []
        tid = file_day.toordinal() * 10_000_000
        for ts in range(start, end, 60_000):
            trade_ts = ts + 500 if ts == d0 + 4 * 3_600_000 else ts
            tid += 1
            side = "buy" if (ts // 60_000) % 2 == 0 else "sell"
            rows.append([instrument, tid, side, "100.0", "0.01", trade_ts, 0])
            o = c = "100.0"
            if ts == d0 + 4 * 3_600_000 - 60_000:
                c = "100.05"
            if ts == d0 + 4 * 3_600_000:
                o = "100.02"
            candles.append([instrument, o, "100.1", "99.9", c, "0.01", "1", "1", ts, 1])
        if start <= d0 + 4 * 3_600_000 < end:
            rows.append([instrument, tid + 1, "sell", "99.85", "0.5", d0 + 4 * 3_600_000 + 5 * 60_000, 0])
            rows.append([instrument, tid + 2, "buy", "100.1", "20", d0 + 4 * 3_600_000 + 10 * 60_000, 0])
            rows.append([instrument, tid + 3, "buy", "100.1", "15", d0 + 4 * 3_600_000 + 11 * 60_000, 0])
        rows.sort(key=lambda r: r[5])
        tz = zip_csv_bytes(f"{instrument}-trades-{file_day}.csv", fr.TRADE_COLUMNS, rows)
        cz = zip_csv_bytes(f"{instrument}-candlesticks-{file_day}.csv", fr.CANDLE_COLUMNS, candles)
        files[archive_file(instrument, "trades", file_day, tz)] = tz
        files[archive_file(instrument, "candles_1m", file_day, cz)] = cz
    for book_day in (day, day + timedelta(days=1)):
        b0 = fr._utc_ms(book_day)
        snapshot = {"instId": instrument, "action": "snapshot", "ts": str(b0 + 3),
                    "asks": [["100.1", "20", "1"], ["100.2", "50", "2"], ["100.3", "500", "3"]],
                    "bids": [["99.9", "20", "1"], ["99.8", "50", "2"], ["99.7", "500", "3"]]}
        events = [snapshot]
        if book_day == day:
            events.append({"instId": instrument, "action": "update", "ts": str(b0 + 4 * 3_600_000 - 1000), "asks": [["100.1", "0.05", "1"]], "bids": []})
            events.append({"instId": instrument, "action": "update", "ts": str(b0 + 4 * 3_600_000 + 200), "asks": [["100.1", "20", "1"]], "bids": []})
        for k in range(1, 96):
            events.append(dict(snapshot, ts=str(b0 + k * 900_000 + 3)))
        events.append({"instId": instrument, "action": "update", "ts": str(b0 + fr.DAY_MS - 120), "asks": [], "bids": [["99.7", "500", "3"]]})
        events.sort(key=lambda e: int(e["ts"]))
        bz = targz_bytes(f"{instrument}-L2orderbook-400lv-{book_day}.data", events)
        files[archive_file(instrument, "book_400", book_day, bz)] = bz
    return files


def fetch_synthetic(tmp_path: Path, files=None, instrument="BTC-USDT"):
    files = files or synthetic_day(instrument)
    session = FakeSession({f.url: payload for f, payload in files.items()})
    dl = fr.ArchiveDownloader(tmp_path / "archive", session, sleep=lambda s: None, now_fn=lambda: _utc("2026-11-05T12:00:00"))
    summary = dl.fetch_all(list(files))
    assert summary.failed == 0 and summary.fetched == len(files)
    return tmp_path / "archive", list(files), session


# -- URLs and the listing ------------------------------------------------------------------------------------------

def test_validate_archive_url_pins_the_host_and_the_path():
    ok = f"{HOST}/trades/daily/20261030/BTC-USDT-trades-2026-10-30.zip?v=1001"
    assert fr.validate_archive_url(ok) == ok
    assert fr.validate_archive_url("https://static.okx.com/cdn/okx/match/orderbook/pro/L2/400lv/daily/20261101/BTC-USDT-L2orderbook-400lv-2026-11-01.tar.gz")
    for bad in ("http://static.okx.com/cdn/okex/x.zip", "https://static.okx.com.evil.example/cdn/x.zip", "https://evil.example/static.okx.com/cdn/x.zip",
                "https://user@static.okx.com/cdn/x.zip", "https://static.okx.com/cdn/../x.zip", "https://static.okx.com//cdn/x.zip",
                "https://static.okx.com/cdn/x.zip?v=1&token=abc", "https://www.okx.com/cdn/x.zip", "https://static.okx.com/api/v5/x", "", None):
        with pytest.raises(fr.FillReplayError):
            fr.validate_archive_url(bad)


def test_parse_filename_and_the_recorded_listing():
    assert fr.parse_filename("BTC-USDT-trades-2026-10-30.zip") == ("BTC-USDT", "trades", date(2026, 10, 30))
    assert fr.parse_filename("ETH-USDT-candlesticks-2026-10-29.zip") == ("ETH-USDT", "candles_1m", date(2026, 10, 29))
    assert fr.parse_filename("ETH-USDT-L2orderbook-400lv-2026-10-28.tar.gz") == ("ETH-USDT", "book_400", date(2026, 10, 28))
    for bad in ("allspot-trades-2026-10-30.zip", "BTC-USDT-L2orderbook-5000lv-2026-10-28.tar.gz", "BTC-USDT-trades-2026-10-30.csv", "x"):
        with pytest.raises(fr.FillReplayError):
            fr.parse_filename(bad)
    files = fr.parse_listing(FIXTURE["trades"]["response"]["data"], kind="trades", instruments=["BTC-USDT", "ETH-USDT"], start=date(2026, 10, 29),
                             end=date(2026, 10, 30))
    assert [(f.day.isoformat(), f.instrument) for f in files] == [("2026-10-29", "BTC-USDT"), ("2026-10-29", "ETH-USDT"), ("2026-10-30", "BTC-USDT"),
                                                                 ("2026-10-30", "ETH-USDT")]
    assert files[2].filename == "BTC-USDT-trades-2026-10-30.zip" and files[2].size_mb == 8.87 and files[2].size_bytes_listed == 9300869
    assert files[2].url.startswith("https://static.okx.com/cdn/okex/traderecords/trades/daily/20261030/") and files[2].date_ts == 1793289600000
    books = fr.parse_listing(FIXTURE["book_400"]["response"]["data"], kind="book_400", instruments=["BTC-USDT"], start=date(2026, 10, 1), end=date(2026, 10, 31))
    assert [f.day.isoformat() for f in books] == ["2026-10-28", "2026-10-29"] and all(f.kind == "book_400" for f in books)
    assert books[0].url == ("https://static.okx.com/cdn/okx/match/orderbook/pro/L2/400lv/daily/20261028/BTC-USDT-L2orderbook-400lv-2026-10-28.tar.gz")
    assert fr.parse_listing(FIXTURE["trades"]["response"]["data"], kind="trades", instruments=["BTC-USDT"], start=date(2026, 10, 30), end=date(2026, 10, 30))[0].instrument == "BTC-USDT"
    assert fr.parse_listing(FIXTURE["trades"]["response"]["data"], kind="trades", instruments=["SOL-USDT"], start=date(2026, 10, 1), end=date(2026, 10, 31)) == []
    with pytest.raises(fr.FillReplayError):  # the wrong module's files are refused, never silently relabelled
        fr.parse_listing(FIXTURE["trades"]["response"]["data"], kind="book_400", instruments=["BTC-USDT"], start=date(2026, 10, 1), end=date(2026, 10, 31))
    assert fr.ArchiveFile.from_json(files[0].to_json()) == files[0]


def test_parse_listing_refuses_foreign_urls_and_mismatched_instruments():
    good = {"instId": "BTC-USDT", "groupDetails": [{"dateTs": "1793289600000", "filename": "BTC-USDT-trades-2026-10-30.zip", "sizeMB": "8.87",
                                                     "url": f"{HOST}/trades/daily/20261030/BTC-USDT-trades-2026-10-30.zip?v=1001"}]}
    base = [{"dateAggrType": "daily", "details": [good]}]
    assert len(fr.parse_listing(base, kind="trades", instruments=["BTC-USDT"], start=date(2026, 10, 30), end=date(2026, 10, 30))) == 1
    foreign = [{"dateAggrType": "daily", "details": [dict(good, groupDetails=[dict(good["groupDetails"][0], url="https://cdn.evil.example/BTC-USDT-trades-2026-10-30.zip")])]}]
    with pytest.raises(fr.FillReplayError):
        fr.parse_listing(foreign, kind="trades", instruments=["BTC-USDT"], start=date(2026, 10, 30), end=date(2026, 10, 30))
    mismatch = [{"dateAggrType": "daily", "details": [dict(good, instId="ETH-USDT")]}]
    with pytest.raises(fr.FillReplayError):
        fr.parse_listing(mismatch, kind="trades", instruments=["BTC-USDT", "ETH-USDT"], start=date(2026, 10, 30), end=date(2026, 10, 30))


class FakeRest:
    """Answers the listing from the requested parameters: one file per instrument and day of the window, plus a day on each side
    (the real endpoint reads the window in UTC+8 for the trades modules and in UTC for the book)."""

    def __init__(self):
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        assert path == fr.MARKET_DATA_HISTORY_PATH
        kind = {v: k for k, v in fr.MODULES.items()}[params["module"]]
        begin = datetime.fromtimestamp(int(params["begin"]) / 1000, tz=timezone.utc).date() - timedelta(days=1)
        end = datetime.fromtimestamp(int(params["end"]) / 1000, tz=timezone.utc).date() + timedelta(days=1)
        details = []
        for inst in params["instIdList"].split(","):
            group = []
            d = end
            while d >= begin:
                f = archive_file(inst, kind, d, b"x" * 1000)
                group.append({"dateTs": str(f.date_ts), "filename": f.filename, "sizeMB": "0.00", "url": f.url})
                d -= timedelta(days=1)
            details.append({"instId": inst, "instType": "SPOT", "groupDetails": group})
        return [{"dateAggrType": "daily", "details": details, "totalSizeMB": "0", "ts": "1"}]


def test_list_archive_files_chunks_pads_filters_and_paces():
    rest = FakeRest()
    sleeps = []
    files = fr.list_archive_files(rest, kind="trades", instruments=["BTC-USDT", "ETH-USDT"], start=date(2026, 10, 1), end=date(2026, 10, 25),
                                  sleep=sleeps.append, sleep_seconds=0.5)
    assert len(rest.calls) == 4 and sleeps == [0.5, 0.5, 0.5]  # 25 days in chunks of 8 (10 with a day of padding on each side)
    first = rest.calls[0][1]
    assert first == {"instType": "SPOT", "instIdList": "BTC-USDT,ETH-USDT", "module": "1", "dateAggrType": "daily",
                     "begin": str(_ms("2026-09-30T04:00:00")), "end": str(_ms("2026-10-09T04:00:00"))}
    assert rest.calls[-1][1]["begin"] == str(_ms("2026-10-24T04:00:00")) and rest.calls[-1][1]["end"] == str(_ms("2026-10-26T04:00:00"))
    assert len(files) == 50 and files[0].day == date(2026, 10, 1) and files[-1].day == date(2026, 10, 25)
    assert files == sorted(files, key=lambda f: (f.day, f.instrument)) and {f.kind for f in files} == {"trades"}
    with_tail = fr.list_all_kinds(FakeRest(), instruments=["BTC-USDT"], start=date(2026, 10, 20), end=date(2026, 10, 21), sleep=lambda s: None,
                                  tail_days={"trades": 1, "candles_1m": 1})
    by_kind = {k: sorted(f.day for f in with_tail if f.kind == k) for k in fr.KINDS}
    assert by_kind["book_400"] == [date(2026, 10, 20), date(2026, 10, 21)]
    assert by_kind["trades"] == by_kind["candles_1m"] == [date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)]
    with pytest.raises(ValueError):
        fr.list_archive_files(FakeRest(), kind="book_5000", instruments=["BTC-USDT"], start=date(2026, 10, 1), end=date(2026, 10, 2))
    with pytest.raises(ValueError):
        fr.list_archive_files(FakeRest(), kind="trades", instruments=["BTC-USDT"], start=date(2026, 10, 2), end=date(2026, 10, 1))
    with pytest.raises(ValueError):
        fr.list_archive_files(FakeRest(), kind="trades", instruments=["../x"], start=date(2026, 10, 1), end=date(2026, 10, 2))


# -- the downloader --------------------------------------------------------------------------------------------------

def test_downloader_fetches_verifies_writes_manifests_and_resumes(tmp_path):
    files = synthetic_day()
    session = FakeSession({f.url: payload for f, payload in files.items()})
    dl = fr.ArchiveDownloader(tmp_path / "archive", session, sleep=lambda s: None, now_fn=lambda: _utc("2026-11-05T12:00:00"))
    summary = dl.fetch_all(list(files))
    assert summary.fetched == len(files) and summary.failed == 0 and summary.skipped == 0 and summary.bytes == sum(len(p) for p in files.values())
    for url, kwargs in session.calls:
        assert kwargs == {"stream": True, "timeout": 120.0, "allow_redirects": False}  # no headers, params, cookies or auth, ever
        assert url.startswith("https://static.okx.com/cdn/")
    f = next(f for f in files if f.kind == "trades" and f.day == date(2026, 10, 30))
    path = dl.path_for(f)
    assert path == tmp_path / "archive" / "BTC-USDT" / "trades" / "BTC-USDT-trades-2026-10-30.zip" and path.read_bytes() == files[f]
    manifest = json.loads(dl.manifest_for(path).read_text(encoding="utf-8"))
    assert manifest["sha256"] == hashlib.sha256(files[f]).hexdigest() and manifest["size_bytes"] == len(files[f]) and manifest["verified"] is True
    assert manifest["url"] == f.url and manifest["day"] == "2026-10-30" and manifest["kind"] == "trades" and manifest["fetched_at"] == "2026-11-05T12:00:00Z"
    assert not list((tmp_path / "archive").rglob("*.part"))
    again = dl.fetch_all(list(files))
    assert again.skipped == len(files) and again.fetched == 0 and len(session.calls) == len(files)  # nothing re-downloaded
    status = fr.archive_status(tmp_path / "archive")
    assert status["verified"] == len(files) and status["raw_present"] == len(files) and status["raw_bytes"] == summary.bytes
    on_disk = fr.manifests_as_files(tmp_path / "archive", ["BTC-USDT"])
    assert {(x.instrument, x.kind, x.day, x.url) for x in on_disk} == {(x.instrument, x.kind, x.day, x.url) for x in files}
    assert fr.manifests_as_files(tmp_path / "archive", ["ETH-USDT"]) == []
    removed = fr.delete_raw_files(tmp_path / "archive", on_disk)
    assert removed == len(files) and fr.archive_status(tmp_path / "archive")["raw_present"] == 0 and fr.manifests_as_files(tmp_path / "archive", ["BTC-USDT"]) == []
    assert dl.fetch_all(list(files)).fetched == len(files)  # a deleted raw file is fetched again (resumable)


def test_downloader_refuses_foreign_urls_redirects_and_corrupt_files(tmp_path):
    files = synthetic_day()
    f = next(iter(files))
    foreign = fr.ArchiveFile(f.instrument, f.kind, f.day, f.filename, f.size_mb, "https://cdn.evil.example/" + f.filename, f.date_ts)
    session = FakeSession({})
    dl = fr.ArchiveDownloader(tmp_path / "a", session, sleep=lambda s: None)
    with pytest.raises(fr.FillReplayError):
        dl.fetch(foreign)
    assert session.calls == []  # refused before any request
    summary = dl.fetch_all([foreign])
    assert summary.failed == 1 and summary.fetched == 0 and "refusing archive URL" in summary.errors[0]
    redirect = FakeSession({f.url: files[f]}, status=302)
    dl = fr.ArchiveDownloader(tmp_path / "b", redirect, sleep=lambda s: None, max_retries=2)
    with pytest.raises(fr.FillReplayError, match="HTTP 302"):
        dl.fetch(f)
    assert len(redirect.calls) == 2 and not [p for p in (tmp_path / "b").rglob("*") if p.is_file()]  # retried, nothing kept
    corrupt = FakeSession({f.url: files[f]}, corrupt={f.url})
    dl = fr.ArchiveDownloader(tmp_path / "c", corrupt, sleep=lambda s: None, max_retries=2)
    summary = dl.fetch_all([f])
    assert summary.failed == 1 and not list((tmp_path / "c").rglob("*.part"))
    assert "differs from the listed" in summary.errors[0] or "zip" in summary.errors[0]  # the tiny synthetic file lists as 0.00 MB: the integrity check catches it
    assert not dl.is_complete(f)
    bad_size = fr.ArchiveFile(f.instrument, f.kind, f.day, f.filename, f.size_mb + 1.0, f.url, f.date_ts)
    dl = fr.ArchiveDownloader(tmp_path / "d", FakeSession({f.url: files[f]}), sleep=lambda s: None, max_retries=1)
    assert dl.fetch_all([bad_size]).failed == 1
    with pytest.raises(ValueError):
        fr.ArchiveDownloader(tmp_path / "e", None)


def test_verify_archive_checks_the_member_layout(tmp_path):
    one = tmp_path / "one.zip"
    one.write_bytes(zip_csv_bytes("x.csv", ["a"], [[1]]))
    fr.verify_archive(one, "trades")
    two = tmp_path / "two.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.csv", "a\n")
        z.writestr("b.csv", "b\n")
    two.write_bytes(buf.getvalue())
    with pytest.raises(fr.FillReplayError):
        fr.verify_archive(two, "candles_1m")
    notzip = tmp_path / "x.zip"
    notzip.write_bytes(b"not a zip")
    with pytest.raises(fr.FillReplayError):
        fr.verify_archive(notzip, "trades")
    book = tmp_path / "b.tar.gz"
    book.write_bytes(targz_bytes("b.data", [{"a": 1}]))
    fr.verify_archive(book, "book_400")
    notgz = tmp_path / "n.tar.gz"
    notgz.write_bytes(b"nope")
    with pytest.raises(fr.FillReplayError):
        fr.verify_archive(notgz, "book_400")
    with pytest.raises(ValueError):
        fr.verify_archive(one, "book_5000")


# -- parsers and the book ---------------------------------------------------------------------------------------------

def test_trades_candles_and_book_parsers(tmp_path):
    day = date(2026, 10, 30)
    rows = [["BTC-USDT", 3, "sell", "100.2", "0.5", _ms("2026-10-29T16:00:02"), 0], ["ETH-USDT", 9, "buy", "1", "1", _ms("2026-10-29T16:00:00"), 0],
            ["BTC-USDT", 1, "buy", "100.0", "0.25", _ms("2026-10-29T16:00:00"), 0], ["BTC-USDT", 2, "buy", "100.1", "0.1", _ms("2026-10-29T16:00:01"), 0]]
    tz = tmp_path / "BTC-USDT-trades-2026-10-30.zip"
    tz.write_bytes(zip_csv_bytes("t.csv", fr.TRADE_COLUMNS, rows))
    t = fr.load_trades(tz, "BTC-USDT")
    assert t.n == 3 and list(t.trade_id) == [1, 2, 3] and list(t.price) == [100.0, 100.1, 100.2] and list(t.buy) == [True, True, False]
    assert t.intervals == [fr.file_span_ms("trades", day)] == [(_ms("2026-10-29T16:00:00"), _ms("2026-10-30T16:00:00"))]
    assert t.covers(_ms("2026-10-29T16:00:00"), _ms("2026-10-30T16:00:00")) and not t.covers(_ms("2026-10-30T12:00:00"), _ms("2026-10-30T18:00:00"))
    tz2 = tmp_path / "BTC-USDT-trades-2026-10-31.zip"
    tz2.write_bytes(zip_csv_bytes("t.csv", fr.TRADE_COLUMNS, [["BTC-USDT", 3, "sell", "100.2", "0.5", _ms("2026-10-29T16:00:02"), 0],
                                                            ["BTC-USDT", 4, "sell", "100.3", "0.5", _ms("2026-10-30T16:00:00"), 0]]))
    pooled = fr.concat_trades([fr.load_trades(tz2, "BTC-USDT"), t])
    assert pooled.n == 4 and list(pooled.trade_id) == [1, 2, 3, 4] and pooled.intervals == [(_ms("2026-10-29T16:00:00"), _ms("2026-10-31T16:00:00"))]
    assert pooled.covers(_ms("2026-10-30T12:00:00"), _ms("2026-10-30T18:00:00")) and pooled.files == [tz2.name, tz.name]
    with pytest.raises(ValueError):
        fr.concat_trades([t, fr.TradesSeries("ETH-USDT", np.array([], dtype=np.int64), np.array([]), np.array([]), np.array([], dtype=bool), np.array([], dtype=np.int64))])
    bad = tmp_path / "bad.zip"
    bad.write_bytes(zip_csv_bytes("t.csv", ["a", "b"], [[1, 2]]))
    with pytest.raises(fr.FillReplayError):
        fr.load_trades(bad, "BTC-USDT")
    cz = tmp_path / "BTC-USDT-candlesticks-2026-10-30.zip"
    cz.write_bytes(zip_csv_bytes("c.csv", fr.CANDLE_COLUMNS, [["BTC-USDT", "1", "2", "0.5", "1.5", "1", "1", "1", _ms("2026-10-30T00:00:00"), 1],
                                                           ["ETH-USDT", "9", "9", "9", "9", "1", "1", "1", _ms("2026-10-30T00:00:00"), 1]]))
    candles = fr.load_candles_1m(cz, "BTC-USDT")
    assert candles == {_ms("2026-10-30T00:00:00"): (1.0, 2.0, 0.5, 1.5)}
    with pytest.raises(fr.FillReplayError):
        fr.load_candles_1m(bad, "BTC-USDT")
    bz = tmp_path / "b.tar.gz"
    bz.write_bytes(targz_bytes("b.data", [
        {"instId": "BTC-USDT", "action": "update", "ts": "5", "asks": [["101", "1", "1"]], "bids": []},
        {"instId": "BTC-USDT", "action": "snapshot", "ts": "10", "asks": [["101", "1", "1"], ["102", "2", "1"], ["100.5", "0", "0"]], "bids": [["99", "3", "1"], ["98", "4", "1"]]},
        {"instId": "BTC-USDT", "action": "update", "ts": "20", "asks": [["101", "0", "0"], ["101.5", "0.5", "1"]], "bids": [["99.5", "1", "1"]]},
    ]))
    events = list(fr.iter_book_events(bz))
    assert [e[0] for e in events] == [5, 10, 20] and events[1][1] == "snapshot"
    book = fr.OrderBook()
    for e in events:
        book.apply(*e)
    assert book.updates_before_sync == 1 and book.snapshots == 1 and book.events == 2 and book.last_ts == 20
    bids, asks = book.top()
    assert bids == [(99.5, 1.0), (99.0, 3.0), (98.0, 4.0)] and asks == [(101.5, 0.5), (102.0, 2.0)]
    assert book.top(depth=1) == ([(99.5, 1.0)], [(101.5, 0.5)])
    with pytest.raises(fr.FillReplayError):
        book.apply(30, "delete", [], [])
    book.reset()
    assert not book.synced and book.bids == {} and book.events == 0


# -- the arithmetic ----------------------------------------------------------------------------------------------------

def test_walk_book_and_cost_bps_by_hand():
    levels = [(100.0, 0.05), (101.0, 0.1)]  # 5 USDT at the first level, 10.1 at the second
    small = fr.walk_book(levels, 4.0)
    assert small.avg_price == 100.0 and small.levels == 1 and small.beyond_first_share == 0.0 and small.complete and small.filled_base == pytest.approx(0.04)
    mid = fr.walk_book(levels, 10.0)
    assert mid.levels == 2 and mid.beyond_first_share == pytest.approx(0.5) and mid.complete
    assert mid.avg_price == pytest.approx(10.0 / (0.05 + 5.0 / 101.0)) and mid.filled_quote == pytest.approx(10.0)
    thin = fr.walk_book(levels, 100.0)
    assert not thin.complete and thin.levels == 2 and thin.filled_quote == pytest.approx(15.1)
    assert math.isnan(fr.walk_book([], 1.0).avg_price) and not fr.walk_book([], 1.0).complete
    with pytest.raises(ValueError):
        fr.walk_book(levels, 0.0)
    assert fr.cost_bps("buy", 100.4975, 99.95) == pytest.approx((100.4975 / 99.95 - 1) * 1e4)
    assert fr.cost_bps("sell", 99.5, 100.0) == pytest.approx(50.0) and fr.cost_bps("buy", 99.5, 100.0) == pytest.approx(-50.0)
    assert math.isnan(fr.cost_bps("buy", 100.0, None)) and math.isnan(fr.cost_bps("buy", float("nan"), 100.0)) and math.isnan(fr.cost_bps("sell", 1.0, 0.0))


def test_bar_boundaries_and_file_spans():
    day = date(2026, 10, 30)
    assert fr.bar_boundaries(day, "6H") == [_ms(f"2026-10-30T{h:02d}:00:00") for h in (0, 6, 12, 18)]
    assert fr.bar_boundaries(day, "4H") == [_ms(f"2026-10-30T{h:02d}:00:00") for h in (0, 4, 8, 12, 16, 20)]
    assert fr.file_span_ms("trades", day) == fr.file_span_ms("candles_1m", day) == (_ms("2026-10-29T16:00:00"), _ms("2026-10-30T16:00:00"))
    assert fr.file_span_ms("book_400", day) == (_ms("2026-10-30T00:00:00"), _ms("2026-10-31T00:00:00"))
    assert fr.listing_params("book_400", ["BTC-USDT"], day, day)["begin"] == str(_ms("2026-10-30T04:00:00"))


def _series(rows, start, end):
    ts = np.array([r[0] for r in rows], dtype=np.int64)
    return fr.TradesSeries("BTC-USDT", ts, np.array([r[1] for r in rows], dtype=float), np.array([r[2] for r in rows], dtype=float),
                           np.array([r[3] for r in rows], dtype=bool), np.arange(len(rows), dtype=np.int64), [(start, end)], ["x"])


def test_post_only_outcome_from_the_tape():
    t = _ms("2026-10-30T04:00:00")
    end = t + fr.BAR_MS["4H"]
    rows = [(t + 60_000, 100.0, 0.1, True), (t + 300_000, 99.85, 0.5, False), (t + 600_000, 100.1, 6.0, True), (t + 660_000, 100.1, 6.0, True), (t + 720_000, 100.0, 0.1, False)]
    tape = _series(rows, t - 1, end + 1)
    buy = fr.post_only_outcome(tape, t_ms=t, end_ms=end, side="buy", limit_px=99.9, queue_ahead=2.0, own_base=10.0)
    assert buy["evaluable"] and buy["filled"] and buy["filled_through"] and buy["fill_ms"] == t + 300_000 and buy["minutes_to_fill"] == 5.0 and buy["trades_in_bar"] == 5
    sell_small = fr.post_only_outcome(tape, t_ms=t, end_ms=end, side="sell", limit_px=100.1, queue_ahead=1.0, own_base=1000 / 100.1)
    assert sell_small["filled"] and not sell_small["filled_through"] and sell_small["fill_ms"] == t + 660_000 and not sell_small["traded_through_at_all"]
    sell_big = fr.post_only_outcome(tape, t_ms=t, end_ms=end, side="sell", limit_px=100.1, queue_ahead=1.0, own_base=5000 / 100.1)
    assert sell_big["evaluable"] and not sell_big["filled"] and sell_big["fill_ms"] is None
    uncovered = fr.post_only_outcome(_series(rows, t - 1, t + 3_600_000), t_ms=t, end_ms=end, side="buy", limit_px=99.9, queue_ahead=2.0, own_base=10.0)
    assert not uncovered["evaluable"] and not uncovered["filled"] and uncovered["trades_in_bar"] == 0
    empty = fr.post_only_outcome(_series([(t - 10, 100.0, 1.0, True)], t - 1, end + 1), t_ms=t, end_ms=end, side="buy", limit_px=99.9, queue_ahead=2.0, own_base=1.0)
    assert empty["evaluable"] and not empty["filled"] and empty["trades_in_bar"] == 0


# -- the replay end to end ---------------------------------------------------------------------------------------------

def test_replay_archive_on_the_synthetic_days(tmp_path):
    root, files, _ = fetch_synthetic(tmp_path)
    plan = fr.plan_replay(root, files)
    assert set(plan) == {"BTC-USDT"} and [d for d, _ in plan["BTC-USDT"].books] == [date(2026, 10, 30), date(2026, 10, 31)] and len(plan["BTC-USDT"].trades) == 3
    logs = []
    replay = fr.replay_archive(root, files, instruments=["BTC-USDT", "ETH-USDT"], log=logs.append)
    assert replay["errors"] == ["ETH-USDT: no trades file with a 400-level book file on disk"]
    cov = replay["coverage"][0]
    assert cov["days"] == ["2026-10-30", "2026-10-31"] and cov["book_resets"] == 0 and cov["snapshots"] == 192
    assert cov["from_first_snapshot"] == 2  # the first day's 00:00 close sample, once for the 4H and once for the 6H boundary
    assert cov["trades_span"] == {"first": "2026-10-29T16:00:00Z", "last": "2026-11-01T15:59:00Z"} and cov["boundaries"] == {"4H": 12, "6H": 8}
    assert cov["trades_intervals"] == [{"start": "2026-10-29T16:00:00Z", "end": "2026-11-01T16:00:00Z"}] and cov["candles_1m"] == 3 * 1440
    records = replay["records"]
    assert len(records) == 20
    by = {(r["timeframe"], r["t"]): r for r in records}
    first = by[("4H", "2026-10-30T00:00:00Z")]
    assert first["moments"]["close"]["from_first_snapshot"] is True and first["moments"]["close"]["bid"] == 99.9 and first["moments"]["close"]["ask"] == 100.1
    assert first["ref"]["candle_close"] == 100.0 and first["ref"]["tape_close"] == 100.0 and first["ref"]["first_trade_lag_ms"] == 0
    r4 = by[("4H", "2026-10-30T04:00:00Z")]
    assert r4["ref"] == {"candle_close": 100.05, "candle_open": 100.02, "tape_close": 100.0, "tape_open": 100.0, "tape_close_age_ms": 60_000,
                         "first_trade_ms": _ms("2026-10-30T04:00:00") + 500, "first_trade_lag_ms": 500}
    close = r4["moments"]["close"]
    assert close["synced"] and not close["from_first_snapshot"] and close["ask_size"] == 0.05 and close["bid_size"] == 20.0 and close["event_ts"] == _ms("2026-10-30T03:59:59")
    assert close["mid"] == pytest.approx(100.0) and close["spread_bps"] == pytest.approx(20.0)
    buy_1k = close["fills"]["buy"]["1K"]
    assert buy_1k["levels"] == 2 and buy_1k["beyond_first_share"] == pytest.approx(1 - 5.005 / 1000) and buy_1k["complete"]
    assert buy_1k["avg_px"] == pytest.approx(1000 / (0.05 + (1000 - 5.005) / 100.2))
    assert buy_1k["cost_vs_close_bps"] == pytest.approx((buy_1k["avg_px"] / 100.05 - 1) * 1e4) and buy_1k["cost_vs_open_bps"] == pytest.approx((buy_1k["avg_px"] / 100.02 - 1) * 1e4)
    assert close["fills"]["buy"]["20K"]["complete"] and close["fills"]["sell"]["1K"]["levels"] == 1 and close["fills"]["sell"]["1K"]["avg_px"] == 99.9
    assert close["fills"]["sell"]["1K"]["cost_vs_mid_bps"] == pytest.approx(10.0)
    nxt = r4["moments"]["next_open"]
    assert nxt["event_ts"] == _ms("2026-10-30T04:00:00") + 200 and nxt["ask_size"] == 20.0 and nxt["fills"]["buy"]["1K"]["levels"] == 1
    assert r4["moments"]["plus_1s"]["ask_size"] == 20.0
    po = r4["post_only"]
    assert po["buy"]["1K"]["filled"] and po["buy"]["1K"]["filled_through"] and po["buy"]["1K"]["minutes_to_fill"] == 5.0 and po["buy"]["1K"]["queue_ahead"] == 20.0
    assert po["sell"]["1K"]["filled"] and not po["sell"]["1K"]["filled_through"] and po["sell"]["1K"]["minutes_to_fill"] == 10.0  # queue ahead = the shrunk 0.05
    assert po["sell"]["1K"]["queue_ahead"] == 0.05
    assert not po["sell"]["5K"]["filled"] and po["sell"]["5K"]["evaluable"]
    assert r4["bar_end_mid"] == pytest.approx(100.0) and po["buy"]["1K"]["markout_bps"] == pytest.approx((100.0 / 99.9 - 1) * 1e4)
    assert po["sell"]["5K"]["missed_move_bps"] == pytest.approx(-(100.0 / 100.02 - 1) * 1e4)  # against the 04:00 candle open of 100.02
    assert po["sell"]["1K"]["missed_move_bps"] is None
    assert r4["bar"]["covered"] and r4["bar"]["trades"] == 240 + 3 and r4["bar"]["volume_usdt"] == pytest.approx(240 * 1.0 + 0.5 * 99.85 + 35 * 100.1)
    r6 = by[("6H", "2026-10-30T06:00:00Z")]
    assert r6["moments"]["close"]["fills"]["buy"]["1K"]["levels"] == 1 and r6["post_only"]["buy"]["20K"]["filled"] is False  # no trade through 99.9 after 04:05
    day2 = by[("6H", "2026-10-31T00:00:00Z")]
    assert day2["moments"]["close"]["from_first_snapshot"] is False  # the book carried over from the day before
    assert day2["moments"]["close"]["bids"] if False else day2["moments"]["close"]["bid"] == 99.9
    last = by[("4H", "2026-10-31T20:00:00Z")]
    assert last["bar"]["covered"] and last["post_only"]["buy"]["1K"]["evaluable"] and last["bar_end_mid"] is None  # no third book day
    assert last["post_only"]["buy"]["1K"]["markout_bps"] is None
    assert "BTC-USDT 2026-10-30: 99 book events, 96 snapshots, 10 boundaries" in logs[1]  # 96 snapshots + 2 scripted updates + the end-of-day update


def test_results_summary_tables_and_json(tmp_path):
    root, files, _ = fetch_synthetic(tmp_path)
    replay = fr.replay_archive(root, files, instruments=["BTC-USDT"])
    results = fr.build_results(replay, files=files, archive_root=root, now=_utc("2026-11-05T12:30:00"), window=(date(2026, 10, 30), date(2026, 10, 31)))
    assert results["generated_at"] == "2026-11-05T12:30:00Z" and results["window"] == {"start": "2026-10-30", "end": "2026-10-31"}
    assert results["engine_default"] == {"fee_bps_per_side": 10.0, "slippage_bps_per_side": 5.0, "round_trip_bps": 30.0}
    assert len(results["files"]) == len(files) and all(m["sha256"] for m in results["files"])
    s = results["summary"]
    assert s["clips"] == ["1K", "5K", "10K", "20K"] and s["instruments"] == ["BTC-USDT"] and s["timeframes"] == ["4H", "6H"]
    row = next(r for r in s["market_orders"] if r["timeframe"] == "6H" and r["moment"] == "close" and r["side"] == "sell" and r["clip"] == "1K")
    assert row["n"] == 8 and row["vs_mid_bps"]["median"] == pytest.approx(10.0) and row["multi_level_pct"] == 0.0 and row["spread_bps"]["median"] == pytest.approx(20.0)
    row4 = next(r for r in s["market_orders"] if r["timeframe"] == "4H" and r["moment"] == "close" and r["side"] == "sell" and r["clip"] == "1K")
    assert row4["n"] == 12 and row4["vs_mid_bps"]["min"] == pytest.approx(10.0) and row4["vs_mid_bps"]["max"] == pytest.approx(10.0)  # the thin ask moves the mid, not the bid
    buy_row = next(r for r in s["market_orders"] if r["timeframe"] == "4H" and r["moment"] == "close" and r["side"] == "buy" and r["clip"] == "1K")
    assert buy_row["multi_level_pct"] == pytest.approx(100 / 12) and buy_row["vs_close_bps"]["n"] == 12
    post = next(r for r in s["post_only"] if r["timeframe"] == "4H" and r["side"] == "sell" and r["clip"] == "5K")
    assert post["n"] == 12 and post["not_covered"] == 0 and post["fill_rate"] == 0.0 and post["fill_rate_through"] == 0.0
    post_buy = next(r for r in s["post_only"] if r["timeframe"] == "4H" and r["side"] == "buy" and r["clip"] == "1K")
    assert post_buy["fill_rate"] == pytest.approx(1 / 12) and post_buy["fill_rate_queue_only"] == 0.0 and post_buy["minutes_to_fill"]["median"] == 5.0
    ref = s["references"][0]
    assert ref["boundaries"] == 16 and ref["close_tape_vs_candle_bps"]["max"] == pytest.approx(abs(100 / 100.05 - 1) * 1e4) and ref["lag_over_1s_pct"] == 0.0
    text = fr.render_tables(results)
    for needle in ("**A. Coverage**", "**B. Market orders at the bar close", "**C. Cost against the candle close", "**D. Post-only at the touch",
                   "**E. Reference cross-check", "| BTC-USDT | 2 | 2026-10-30 | 2026-10-31 |", "| BTC-USDT | 4H | sell | 1K | 12 | 10.00 |",
                   "Generated by `scripts/run_fill_replay.py --replay` on 2026-11-05T12:30:00Z"):
        assert needle in text, needle
    head = fr.headline(results)["BTC-USDT"]
    assert head["largest_clip"] == "20K" and head["post_only_fill_rate_min"] == 0.0 and head["smallest_clip_vs_mid_median_bps"] == pytest.approx(10.0)
    out = fr.write_results(tmp_path / "r" / "results.json", results)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["summary"] == json.loads(json.dumps(s, default=fr._json_default)) and len(data["records"]) == 20
    assert data["records"][0]["moments"]["close"]["fills"]["buy"]["1K"]["cost_vs_mid_bps"] == pytest.approx(10.0, abs=1e-6)
    assert "NaN" not in out.read_text(encoding="utf-8") and out.read_text(encoding="utf-8").count('\n  {"bar": ') == 20  # one record per line
    empty = fr.build_results({"records": [], "coverage": [], "errors": ["x"], "instruments": ["BTC-USDT"]}, files=[], archive_root=root, now=_utc("2026-11-05T12:30:00"))
    assert json.loads(fr.write_results(tmp_path / "empty.json", empty).read_text(encoding="utf-8"))["records"] == [] and "**A. Coverage**" in fr.render_tables(empty)
    assert fr.headline(empty) == {}


# -- the command line -----------------------------------------------------------------------------------------------------

def test_cli_modes_run_through_the_injected_client_and_session(tmp_path, capsys):
    import scripts.run_fill_replay as cli

    files = synthetic_day()
    session = FakeSession({f.url: payload for f, payload in files.items()})
    rest = FakeRest()
    rest_files = {}

    class ListingRest(FakeRest):
        """The listing names exactly the synthetic files (same names, sizes and URLs) so the fake session can serve them."""

        def get(self, path, params=None):
            self.calls.append((path, dict(params or {})))
            kind = {v: k for k, v in fr.MODULES.items()}[params["module"]]
            group = [{"dateTs": str(f.date_ts), "filename": f.filename, "sizeMB": f"{f.size_mb:.2f}", "url": f.url} for f in files if f.kind == kind]
            return [{"dateAggrType": "daily", "details": [{"instId": "BTC-USDT", "groupDetails": group}]}]

    rest = ListingRest()
    archive = tmp_path / "archive"
    env = {}
    now = lambda: _utc("2026-11-05T12:00:00")  # noqa: E731
    assert cli.main(["--status", "--archive-dir", str(archive)], env, now_fn=now) == cli.EXIT_OK
    assert "0 verified files" in capsys.readouterr().out
    assert cli.main(["--replay", "--archive-dir", str(archive)], env, now_fn=now) == cli.EXIT_SETUP
    assert "nothing to replay" in capsys.readouterr().err
    assert cli.main(["--list", "--start", "2026-10-30", "--end", "2026-10-31", "--instruments", "BTC-USDT", "--archive-dir", str(archive)], env, rest=rest,
                    now_fn=now, sleep=lambda s: None) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "8 archive files for BTC-USDT, book days 2026-10-30 to 2026-10-31" in out and "BTC-USDT-trades-2026-11-01.zip" in out and len(rest.calls) == 3
    assert cli.main(["--fetch", "--start", "2026-10-30", "--end", "2026-10-31", "--instruments", "BTC-USDT", "--archive-dir", str(archive)], env, rest=rest,
                    session=session, now_fn=now, sleep=lambda s: None) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "fetch done: 8 fetched" in out and "0 failed" in out and fr.archive_status(archive)["raw_present"] == 8
    results = tmp_path / "out" / "results.json"
    tables = tmp_path / "out" / "tables.md"
    code = cli.main(["--replay", "--keep", "--archive-dir", str(archive), "--instruments", "BTC-USDT", "--out", str(results), "--tables", str(tables)], env, now_fn=now)
    assert code == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "**A. Coverage**" in out and "results written" in out and "raw files deleted" not in out and results.exists() and tables.exists()
    assert fr.archive_status(archive)["raw_present"] == 8
    code = cli.main(["--all", "--start", "2026-10-30", "--end", "2026-10-31", "--instruments", "BTC-USDT", "--archive-dir", str(archive), "--out", str(results),
                     "--tables", str(tables), "--json"], env, rest=rest, session=session, now_fn=now, sleep=lambda s: None)
    assert code == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "8 already present" in out and '"headline"' in out
    assert fr.archive_status(archive)["raw_present"] == 0 and fr.archive_status(archive)["verified"] == 8  # raw files deleted, manifests kept
    assert cli.main(["--status", "--archive-dir", str(archive), "--json"], env, now_fn=now) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)["raw_present"] == 0
    for url, kwargs in session.calls:
        assert "headers" not in kwargs and "params" not in kwargs and "auth" not in kwargs and kwargs["allow_redirects"] is False
    for bad in (["--keep", "--status"], ["--replay", "--days", "0"], ["--list", "--start", "2026-10-31", "--end", "2026-10-30"], ["--list", "--instruments", "SOL-USDT"],
                ["--fetch", "--sleep", "-1"], ["--replay", "--clips", "0"], ["--list", "--fetch"], []):
        with pytest.raises(SystemExit):
            cli.parse_args(bad)
    args = cli.parse_args(["--list"])
    assert cli._window(args, date(2026, 11, 5)) == (date(2026, 10, 24), date(2026, 11, 2))
    assert cli._window(cli.parse_args(["--list", "--days", "3", "--end", "2026-10-31"]), date(2026, 11, 5)) == (date(2026, 10, 29), date(2026, 10, 31))


def test_cli_fetch_reports_failures_and_keeps_going(tmp_path, capsys):
    import scripts.run_fill_replay as cli

    files = synthetic_day()
    broken = next(f for f in files if f.kind == "book_400")
    session = FakeSession({f.url: payload for f, payload in files.items()}, corrupt={broken.url})

    class ListingRest(FakeRest):
        def get(self, path, params=None):
            kind = {v: k for k, v in fr.MODULES.items()}[params["module"]]
            group = [{"dateTs": str(f.date_ts), "filename": f.filename, "sizeMB": f"{f.size_mb:.2f}", "url": f.url} for f in files if f.kind == kind]
            return [{"dateAggrType": "daily", "details": [{"instId": "BTC-USDT", "groupDetails": group}]}]

    code = cli.main(["--fetch", "--start", "2026-10-30", "--end", "2026-10-31", "--instruments", "BTC-USDT", "--archive-dir", str(tmp_path / "a")], {},
                    rest=ListingRest(), session=session, now_fn=lambda: _utc("2026-11-05T12:00:00"), sleep=lambda s: None)
    assert code == cli.EXIT_ERRORS
    captured = capsys.readouterr()
    assert "7 fetched" in captured.out and "1 failed" in captured.out and broken.filename in captured.err
