"""Fill-cost replay from OKX's PUBLIC tick and order-book archive (plan row R22, SIMULATION ONLY).

The research engine charges 0.10 % fee plus 0.05 % slippage a side and assumes a market order
fills at the next bar's open. This module measures what a market order of 1 K, 5 K, 10 K and
20 K USDT would really have cost in BTC-USDT and ETH-USDT, by replaying the venue's own archived
400-level order book at every 4H and 6H bar close and at the next bar's open, and how often a
post-only order at the touch would have filled within one bar, from the archived trades tape.
Nothing here trades, sizes or approves anything; the numbers feed a recommendation for the cost
model of FUTURE studies only (``docs/research/FILL_COST_REPLAY.md``).

Data path, public only:

- the archive LISTING comes through the data lake's GET-only public client
  (:class:`app.datalake.okx_public_rest.OKXPublicRest`, pinned to OKX's public REST host; no key,
  no header): ``GET /api/v5/public/market-data-history`` with ``instType=SPOT``, ``instIdList``,
  ``module`` (1 = tick-by-tick trades, 2 = 1-minute candles, 4 = the 400-level L2 book),
  ``dateAggrType=daily`` and ``begin``/``end`` in milliseconds (at most 10 days and 10
  instruments a query; 5 requests per 2 seconds);
- the FILES are fetched by :class:`ArchiveDownloader`, a small GET-only downloader that accepts
  only the URLs the listing returned, only on ``https://static.okx.com/cdn/...``, follows no
  redirect, sends no header, no parameter and no credential, and verifies every file against the
  listed size and the archive's own integrity check before it counts as fetched. It is handed an
  HTTP session by the command line (this module imports no network library itself);
- the files land in a git-ignored folder (``data/archive/okx`` by default), one manifest per file,
  so an interrupted run resumes by skipping the files already verified; the raw files are deleted
  after the summaries are written unless the operator keeps them.

File formats, as observed on 2026-11-05:

- trades ``<inst>-trades-<day>.zip``: one CSV ``instrument_name,trade_id,side,price,size,created_time,source``
  (``side`` is the taker side; ``created_time`` in ms). The file named ``<day>`` holds the UTC+8 day, i.e.
  16:00 UTC of the day before to 16:00 UTC of ``<day>``;
- 1-minute candles ``<inst>-candlesticks-<day>.zip``: one CSV
  ``instrument_name,open,high,low,close,vol,vol_ccy,vol_quote,open_time,confirm``, the same UTC+8 day;
- the 400-level book ``<inst>-L2orderbook-400lv-<day>.tar.gz``: one ``.data`` member of JSON lines in the
  public ``books`` channel format (``action`` ``snapshot`` or ``update``, ``ts`` in ms, ``asks``/``bids``
  as ``[price, size, order_count]``; a size of 0 removes the level; a full snapshot every 15 minutes),
  covering the UTC day 00:00 to 24:00.

Because the day boundaries differ, the replay pools every trades and candle file of an instrument into
one continuous series and walks the book files day by day on the UTC grid; a bar whose trades are not
fully covered by the pooled files is not judged.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import statistics
import tarfile
import time
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from research.engine import Costs

# -- constants ---------------------------------------------------------------------------------------------------

MARKET_DATA_HISTORY_PATH = "/api/v5/public/market-data-history"
ARCHIVE_HOST = "static.okx.com"
ARCHIVE_URL_RE = re.compile(r"^https://static\.okx\.com/cdn/[A-Za-z0-9_\-/.]+(?:\?v=\d+)?$")
MODULES: Dict[str, str] = {"trades": "1", "candles_1m": "2", "book_400": "4"}
KINDS: Tuple[str, ...] = tuple(MODULES)
FILENAME_RE = re.compile(
    r"^(?P<inst>[A-Z0-9]+-[A-Z0-9]+)-(?P<what>trades|candlesticks|L2orderbook-400lv)-(?P<day>\d{4}-\d{2}-\d{2})\.(?P<ext>zip|tar\.gz)$"
)
KIND_FOR_WHAT = {"trades": "trades", "candlesticks": "candles_1m", "L2orderbook-400lv": "book_400"}
#: The trades and candle files hold the UTC+8 day: file ``<day>`` starts at 16:00 UTC the day before. The book files hold the UTC day.
FILE_DAY_OFFSET_MS: Dict[str, int] = {"trades": -8 * 3_600_000, "candles_1m": -8 * 3_600_000, "book_400": 0}
INSTRUMENTS: Tuple[str, ...] = ("BTC-USDT", "ETH-USDT")
CLIP_SIZES_USDT: Tuple[float, ...] = (1_000.0, 5_000.0, 10_000.0, 20_000.0)
TIMEFRAMES: Tuple[str, ...] = ("4H", "6H")
BAR_MS: Dict[str, int] = {"4H": 4 * 3_600_000, "6H": 6 * 3_600_000}
MOMENTS: Tuple[str, ...] = ("close", "next_open", "plus_1s")
SIDES: Tuple[str, ...] = ("buy", "sell")
MAX_DAYS_PER_QUERY = 10
MAX_INSTRUMENTS_PER_QUERY = 10
LISTING_SLEEP_SECONDS = 0.5  # the endpoint allows 5 requests per 2 seconds
LISTING_PAD_DAYS = 1  # the listing reads the day window in UTC+8 for some modules and UTC for others; pad and filter by file name
SIZE_TOLERANCE_BYTES = int(0.011 * 1024 * 1024) + 1  # the listing rounds sizeMB (MiB) to two decimals
BOOK_DEPTH_KEPT = 100  # levels kept per side in a sample (a 20 K USDT clip in BTC or ETH touches a handful)
NEXT_OPEN_MAX_LAG_MS = 60_000  # the next bar's open is its first trade; later than this, the reference is missing
STALE_REF_MS = 60_000  # the last trade before the close must be this recent to serve as the close reference
COVERAGE_SLACK_MS = 60_000  # a bar counts as covered by the tape when the pooled files reach within this of its end
ENGINE_DEFAULT = Costs()
DEFAULT_ARCHIVE_DIR = Path("data/archive/okx")
TRADE_COLUMNS = ("instrument_name", "trade_id", "side", "price", "size", "created_time", "source")
CANDLE_COLUMNS = ("instrument_name", "open", "high", "low", "close", "vol", "vol_ccy", "vol_quote", "open_time", "confirm")
DAY_MS = 86_400_000


class FillReplayError(RuntimeError):
    """A listing, download, verification or replay problem the caller should see."""


def _utc_ms(day: date, hour: int = 0, minute: int = 0) -> int:
    return int(datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc).timestamp() * 1000)


def _iso(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_archive_url(url: str) -> str:
    """Only ``https://static.okx.com/cdn/...`` with a plain path (and OKX's ``?v=`` cache tag) is a download URL."""
    if not isinstance(url, str) or not ARCHIVE_URL_RE.match(url) or ".." in url or "//" in url[len("https://"):]:
        raise FillReplayError(f"refusing archive URL not on https://{ARCHIVE_HOST}/cdn/: {url!r}")
    return url


def file_span_ms(kind: str, day: date) -> Tuple[int, int]:
    """The nominal [start, end) the file named ``day`` covers: the UTC+8 day for trades and candles, the UTC day for the book."""
    start = _utc_ms(day) + FILE_DAY_OFFSET_MS[kind]
    return start, start + DAY_MS


# -- the listing -------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ArchiveFile:
    """One daily archive file as the public listing described it."""

    instrument: str
    kind: str
    day: date
    filename: str
    size_mb: float
    url: str
    date_ts: int

    @property
    def size_bytes_listed(self) -> int:
        return int(round(self.size_mb * 1024 * 1024))

    def to_json(self) -> Dict[str, Any]:
        d = asdict(self)
        d["day"] = self.day.isoformat()
        return d

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> "ArchiveFile":
        return cls(str(d["instrument"]), str(d["kind"]), date.fromisoformat(str(d["day"])), str(d["filename"]), float(d["size_mb"]),
                   str(d["url"]), int(d["date_ts"]))


def parse_filename(filename: str) -> Tuple[str, str, date]:
    m = FILENAME_RE.match(filename)
    if not m:
        raise FillReplayError(f"unexpected archive file name {filename!r}")
    return m.group("inst"), KIND_FOR_WHAT[m.group("what")], date.fromisoformat(m.group("day"))


def parse_listing(data: Sequence[Any], *, kind: str, instruments: Sequence[str], start: date, end: date) -> List[ArchiveFile]:
    """The ``data`` list of one listing response -> validated files for ``kind`` within [start, end], oldest first."""
    wanted = set(instruments)
    out: Dict[Tuple[str, date], ArchiveFile] = {}
    for block in data:
        if not isinstance(block, dict):
            raise FillReplayError("listing block is not an object")
        for detail in block.get("details") or []:
            inst = str(detail.get("instId") or "")
            for g in detail.get("groupDetails") or []:
                filename = str(g.get("filename") or "")
                f_inst, f_kind, f_day = parse_filename(filename)
                if f_kind != kind:
                    raise FillReplayError(f"listing for module {MODULES[kind]} returned a {f_kind} file: {filename}")
                if inst and inst != f_inst:
                    raise FillReplayError(f"listing instrument {inst} does not match file {filename}")
                if f_inst not in wanted or not (start <= f_day <= end):
                    continue
                url = validate_archive_url(str(g.get("url") or ""))
                item = ArchiveFile(f_inst, kind, f_day, filename, float(g.get("sizeMB") or 0.0), url, int(g.get("dateTs") or 0))
                out[(f_inst, f_day)] = item
    return [out[k] for k in sorted(out, key=lambda k: (k[1], k[0]))]


def listing_params(kind: str, instruments: Sequence[str], begin_day: date, end_day: date) -> Dict[str, str]:
    """The public listing's parameters; ``begin``/``end`` at 04:00 UTC so the date portion is the same day in UTC and UTC+8."""
    return {
        "instType": "SPOT",
        "instIdList": ",".join(instruments),
        "module": MODULES[kind],
        "dateAggrType": "daily",
        "begin": str(_utc_ms(begin_day, 4)),
        "end": str(_utc_ms(end_day, 4)),
    }


def list_archive_files(rest: Any, *, kind: str, instruments: Sequence[str], start: date, end: date, sleep: Callable[[float], None] = time.sleep,
                       sleep_seconds: float = LISTING_SLEEP_SECONDS) -> List[ArchiveFile]:
    """List the daily files of ``kind`` for ``instruments`` over [start, end] through the GET-only public client."""
    if kind not in MODULES:
        raise ValueError(f"unknown archive kind {kind!r}; expected one of {KINDS}")
    if end < start:
        raise ValueError("end before start")
    for inst in instruments:
        if not re.match(r"^[A-Z0-9]+-[A-Z0-9]+$", inst):
            raise ValueError(f"unexpected instrument id {inst!r}")
    chunk_days = MAX_DAYS_PER_QUERY - 2 * LISTING_PAD_DAYS
    files: Dict[Tuple[str, date], ArchiveFile] = {}
    first = True
    for i in range(0, len(instruments), MAX_INSTRUMENTS_PER_QUERY):
        insts = list(instruments[i:i + MAX_INSTRUMENTS_PER_QUERY])
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(end, chunk_start + timedelta(days=chunk_days - 1))
            if not first:
                sleep(sleep_seconds)
            first = False
            params = listing_params(kind, insts, chunk_start - timedelta(days=LISTING_PAD_DAYS), chunk_end + timedelta(days=LISTING_PAD_DAYS))
            data = rest.get(MARKET_DATA_HISTORY_PATH, params)
            for f in parse_listing(data, kind=kind, instruments=insts, start=chunk_start, end=chunk_end):
                files[(f.instrument, f.day)] = f
            chunk_start = chunk_end + timedelta(days=1)
    return [files[k] for k in sorted(files, key=lambda k: (k[1], k[0]))]


def list_all_kinds(rest: Any, *, instruments: Sequence[str], start: date, end: date, kinds: Sequence[str] = KINDS,
                   tail_days: Optional[Mapping[str, int]] = None, **kw: Any) -> List[ArchiveFile]:
    """All kinds over [start, end]; ``tail_days`` extends the window of a kind (the trades file named ``end + 1`` holds the
    evening of the UTC day ``end``)."""
    out: List[ArchiveFile] = []
    for kind in kinds:
        tail = int((tail_days or {}).get(kind, 0))
        out.extend(list_archive_files(rest, kind=kind, instruments=instruments, start=start, end=end + timedelta(days=tail), **kw))
    return out


# -- the downloader ----------------------------------------------------------------------------------------------


@dataclass
class FetchSummary:
    fetched: int = 0
    skipped: int = 0
    failed: int = 0
    bytes: int = 0
    errors: List[str] = field(default_factory=list)


class ArchiveDownloader:
    """GET-only, host-pinned, resumable downloads of listed archive files into ``root/<instrument>/<kind>/``.

    ``session`` must offer ``get(url, stream=True, timeout=..., allow_redirects=False)`` returning an object with
    ``status_code``, ``iter_content(chunk_size)`` and ``close()`` (``requests.Session`` does). The downloader never
    passes headers, parameters, cookies or authentication, and refuses any URL that is not a listed
    ``https://static.okx.com/cdn/...`` file.
    """

    def __init__(self, root: Path, session: Any, *, timeout: float = 120.0, chunk_size: int = 1 << 20, max_retries: int = 3,
                 sleep: Callable[[float], None] = time.sleep, now_fn: Callable[[], datetime] = lambda: datetime.now(tz=timezone.utc)) -> None:
        if session is None or not hasattr(session, "get"):
            raise ValueError("ArchiveDownloader needs an HTTP session with a get() method")
        self.root = Path(root)
        self._session = session
        self._timeout = float(timeout)
        self._chunk = int(chunk_size)
        self._max_retries = max(1, int(max_retries))
        self._sleep = sleep
        self._now = now_fn

    # paths
    def path_for(self, f: ArchiveFile) -> Path:
        return self.root / f.instrument / f.kind / f.filename

    @staticmethod
    def manifest_for(path: Path) -> Path:
        return path.with_name(path.name + ".json")

    def is_complete(self, f: ArchiveFile) -> bool:
        path = self.path_for(f)
        manifest = self.manifest_for(path)
        if not path.exists() or not manifest.exists():
            return False
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return bool(m.get("verified")) and m.get("url") == f.url and int(m.get("size_bytes", -1)) == path.stat().st_size

    # one file
    def fetch(self, f: ArchiveFile, *, log: Optional[Callable[[str], None]] = None) -> Path:
        validate_archive_url(f.url)
        path = self.path_for(f)
        if self.is_complete(f):
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        last: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                size, digest = self._download(f.url, part)
                self._verify(f, part, size)
                part.replace(path)
                manifest = {
                    "filename": f.filename, "instrument": f.instrument, "kind": f.kind, "day": f.day.isoformat(), "url": f.url,
                    "listed_size_mb": f.size_mb, "size_bytes": size, "sha256": digest, "date_ts": f.date_ts,
                    "fetched_at": self._now().strftime("%Y-%m-%dT%H:%M:%SZ"), "verified": True,
                }
                self.manifest_for(path).write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
                if log:
                    log(f"fetched {f.filename} ({size / 1048576:.1f} MB)")
                return path
            except (OSError, FillReplayError, ValueError) as exc:
                last = exc
                if part.exists():
                    try:
                        part.unlink()
                    except OSError:
                        pass
                if log:
                    log(f"download of {f.filename} failed (attempt {attempt}/{self._max_retries}): {exc}")
                if attempt < self._max_retries:
                    self._sleep(2.0 * attempt)
        raise FillReplayError(f"{f.filename}: {last}")

    def _download(self, url: str, part: Path) -> Tuple[int, str]:
        validate_archive_url(url)
        response = self._session.get(url, stream=True, timeout=self._timeout, allow_redirects=False)
        try:
            status = int(getattr(response, "status_code", 0))
            if status != 200:
                raise FillReplayError(f"HTTP {status} (redirects are not followed)")
            digest = hashlib.sha256()
            size = 0
            with open(part, "wb") as fh:
                for chunk in response.iter_content(chunk_size=self._chunk):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        return size, digest.hexdigest()

    @staticmethod
    def _verify(f: ArchiveFile, part: Path, size: int) -> None:
        if f.size_mb > 0 and abs(size - f.size_bytes_listed) > SIZE_TOLERANCE_BYTES:
            raise FillReplayError(f"size {size} bytes differs from the listed {f.size_mb} MB")
        verify_archive(part, f.kind)

    def fetch_all(self, files: Iterable[ArchiveFile], *, log: Optional[Callable[[str], None]] = None) -> FetchSummary:
        s = FetchSummary()
        for f in files:
            if self.is_complete(f):
                s.skipped += 1
                continue
            try:
                path = self.fetch(f, log=log)
                s.fetched += 1
                s.bytes += path.stat().st_size
            except FillReplayError as exc:
                s.failed += 1
                s.errors.append(str(exc))
        return s


def verify_archive(path: Path, kind: str) -> None:
    """The archive opens and holds exactly one data member (zip CRCs checked; the tar.gz is read through)."""
    if kind in ("trades", "candles_1m"):
        try:
            with zipfile.ZipFile(path) as z:
                members = [i for i in z.infolist() if not i.is_dir()]
                if len(members) != 1 or not members[0].filename.lower().endswith(".csv"):
                    raise FillReplayError(f"expected one CSV member, found {[m.filename for m in members]}")
                if z.testzip() is not None:
                    raise FillReplayError("zip CRC check failed")
        except zipfile.BadZipFile as exc:
            raise FillReplayError(f"not a zip file: {exc}") from exc
    elif kind == "book_400":
        try:
            with tarfile.open(path, "r:gz") as t:
                members = [m for m in t.getmembers() if m.isfile()]
        except (tarfile.TarError, EOFError, OSError) as exc:
            raise FillReplayError(f"not a readable tar.gz: {exc}") from exc
        if len(members) != 1:
            raise FillReplayError(f"expected one data member, found {[m.name for m in members]}")
    else:
        raise ValueError(f"unknown archive kind {kind!r}")


def archive_status(root: Path) -> Dict[str, Any]:
    """What the archive folder holds: verified files (manifests) and whether their raw file is still present."""
    root = Path(root)
    items: List[Dict[str, Any]] = []
    for manifest in sorted(root.glob("*/*/*.json")) if root.exists() else []:
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        raw = manifest.with_name(manifest.name[:-len(".json")])
        items.append({"instrument": m.get("instrument"), "kind": m.get("kind"), "day": m.get("day"), "filename": m.get("filename"),
                      "size_bytes": m.get("size_bytes"), "sha256": m.get("sha256"), "fetched_at": m.get("fetched_at"), "raw_present": raw.exists(),
                      "verified": bool(m.get("verified"))})
    present = sum(1 for i in items if i["raw_present"])
    return {"root": str(root), "files": items, "verified": len(items), "raw_present": present,
            "raw_bytes": sum(int(i["size_bytes"] or 0) for i in items if i["raw_present"])}


def manifests_as_files(root: Path, instruments: Sequence[str]) -> List[ArchiveFile]:
    """The verified files on disk (raw file present), as :class:`ArchiveFile` objects, for ``--replay`` without a listing."""
    out: List[ArchiveFile] = []
    for item in archive_status(root)["files"]:
        if not item["raw_present"] or not item["verified"] or item["instrument"] not in instruments:
            continue
        manifest = json.loads((Path(root) / item["instrument"] / item["kind"] / (item["filename"] + ".json")).read_text(encoding="utf-8"))
        out.append(ArchiveFile(item["instrument"], item["kind"], date.fromisoformat(item["day"]), item["filename"], float(manifest["listed_size_mb"]),
                               manifest["url"], int(manifest.get("date_ts", 0))))
    return sorted(out, key=lambda f: (f.instrument, f.kind, f.day))


def delete_raw_files(root: Path, files: Iterable[ArchiveFile]) -> int:
    """Remove the raw archives (the manifests stay as the record of what was fetched and verified)."""
    n = 0
    for f in files:
        path = Path(root) / f.instrument / f.kind / f.filename
        if path.exists():
            path.unlink()
            n += 1
    return n


# -- parsers -----------------------------------------------------------------------------------------------------


@dataclass
class TradesSeries:
    """The pooled trades of one instrument: ascending timestamps, and the [start, end) intervals the source files cover."""

    instrument: str
    ts: np.ndarray  # int64 ms, ascending
    price: np.ndarray  # float64
    size: np.ndarray  # float64 base units
    buy: np.ndarray  # bool: the taker bought
    trade_id: np.ndarray  # int64
    intervals: List[Tuple[int, int]] = field(default_factory=list)
    files: List[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return int(self.ts.size)

    def covers(self, start_ms: int, end_ms: int, *, slack_ms: int = COVERAGE_SLACK_MS) -> bool:
        """Whether the source files nominally cover [start_ms, end_ms) (within ``slack_ms`` at the end)."""
        for a, b in self.intervals:
            if a <= start_ms and b >= end_ms - slack_ms:
                return True
        return False


def _zip_csv_rows(path: Path) -> Iterator[List[str]]:
    with zipfile.ZipFile(path) as z:
        members = [i for i in z.infolist() if not i.is_dir()]
        if len(members) != 1:
            raise FillReplayError(f"{path.name}: expected one member")
        with z.open(members[0]) as raw:
            yield from csv.reader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))


def load_trades(path: Path, instrument: str) -> TradesSeries:
    rows = _zip_csv_rows(path)
    header = next(rows, None)
    if header is None or len(header) != len(TRADE_COLUMNS):
        raise FillReplayError(f"{path.name}: unexpected trades header {header}")
    ts: List[int] = []
    px: List[float] = []
    sz: List[float] = []
    buy: List[bool] = []
    tid: List[int] = []
    for r in rows:
        if len(r) < 6 or r[0] != instrument:
            continue
        ts.append(int(r[5]))
        px.append(float(r[3]))
        sz.append(float(r[4]))
        buy.append(r[2] == "buy")
        tid.append(int(r[1]))
    t = np.asarray(ts, dtype=np.int64)
    order = np.argsort(t, kind="stable")
    series = TradesSeries(instrument, t[order], np.asarray(px, dtype=np.float64)[order], np.asarray(sz, dtype=np.float64)[order],
                          np.asarray(buy, dtype=bool)[order], np.asarray(tid, dtype=np.int64)[order], files=[path.name])
    try:
        _, kind, day = parse_filename(path.name)
        series.intervals = [file_span_ms(kind, day)]
    except FillReplayError:
        series.intervals = [(int(t.min()), int(t.max()) + 1)] if t.size else []
    return series


def concat_trades(parts: Sequence[TradesSeries]) -> TradesSeries:
    """Pool several files of one instrument: sorted by time, duplicates (same trade id) dropped, intervals merged."""
    if not parts:
        raise ValueError("nothing to pool")
    inst = parts[0].instrument
    if any(p.instrument != inst for p in parts):
        raise ValueError("cannot pool different instruments")
    ts = np.concatenate([p.ts for p in parts])
    price = np.concatenate([p.price for p in parts])
    size = np.concatenate([p.size for p in parts])
    buy = np.concatenate([p.buy for p in parts])
    tid = np.concatenate([p.trade_id for p in parts])
    order = np.lexsort((tid, ts))
    ts, price, size, buy, tid = ts[order], price[order], size[order], buy[order], tid[order]
    if tid.size:
        keep = np.ones(tid.size, dtype=bool)
        keep[1:] = tid[1:] != tid[:-1]
        ts, price, size, buy, tid = ts[keep], price[keep], size[keep], buy[keep], tid[keep]
    intervals: List[Tuple[int, int]] = []
    for a, b in sorted(iv for p in parts for iv in p.intervals):
        if intervals and a <= intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], b))
        else:
            intervals.append((a, b))
    return TradesSeries(inst, ts, price, size, buy, tid, intervals, [f for p in parts for f in p.files])


def load_candles_1m(path: Path, instrument: str) -> Dict[int, Tuple[float, float, float, float]]:
    """``open_time_ms -> (open, high, low, close)`` of the archive's 1-minute candles."""
    rows = _zip_csv_rows(path)
    header = next(rows, None)
    if header is None or len(header) != len(CANDLE_COLUMNS):
        raise FillReplayError(f"{path.name}: unexpected candle header {header}")
    out: Dict[int, Tuple[float, float, float, float]] = {}
    for r in rows:
        if len(r) < 9 or r[0] != instrument:
            continue
        out[int(r[8])] = (float(r[1]), float(r[2]), float(r[3]), float(r[4]))
    return out


def iter_book_events(path: Path) -> Iterator[Tuple[int, str, list, list]]:
    """``(ts_ms, action, asks, bids)`` from the tar.gz JSON lines, in file order."""
    with tarfile.open(path, "r:gz") as t:
        member = next((m for m in t.getmembers() if m.isfile()), None)
        if member is None:
            raise FillReplayError(f"{path.name}: no data member")
        raw = t.extractfile(member)
        if raw is None:
            raise FillReplayError(f"{path.name}: unreadable member")
        for line in io.TextIOWrapper(raw, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            yield int(d["ts"]), str(d.get("action", "")), d.get("asks") or [], d.get("bids") or []


class OrderBook:
    """Price -> size per side, rebuilt from snapshots and updates; nothing is read before the first snapshot."""

    def __init__(self) -> None:
        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}
        self.synced = False
        self.last_ts: Optional[int] = None
        self.events = 0
        self.snapshots = 0
        self.updates_before_sync = 0

    def reset(self) -> None:
        self.__init__()

    def apply(self, ts: int, action: str, asks: Sequence[Sequence[str]], bids: Sequence[Sequence[str]]) -> None:
        if action == "snapshot":
            self.asks = {float(lvl[0]): float(lvl[1]) for lvl in asks if float(lvl[1]) > 0}
            self.bids = {float(lvl[0]): float(lvl[1]) for lvl in bids if float(lvl[1]) > 0}
            self.synced = True
            self.snapshots += 1
        elif action == "update":
            if not self.synced:
                self.updates_before_sync += 1
                return
            for side, levels in ((self.asks, asks), (self.bids, bids)):
                for lvl in levels:
                    px = float(lvl[0])
                    sz = float(lvl[1])
                    if sz <= 0:
                        side.pop(px, None)
                    else:
                        side[px] = sz
        else:
            raise FillReplayError(f"unknown book action {action!r}")
        self.last_ts = ts
        self.events += 1

    def top(self, depth: int = BOOK_DEPTH_KEPT) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
        bids = sorted(self.bids.items(), key=lambda kv: -kv[0])[:depth]
        asks = sorted(self.asks.items())[:depth]
        return bids, asks


# -- the arithmetic ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Fill:
    avg_price: float
    filled_quote: float
    filled_base: float
    levels: int
    beyond_first_share: float
    complete: bool


def walk_book(levels: Sequence[Tuple[float, float]], notional_usdt: float) -> Fill:
    """Fill a market order of ``notional_usdt`` against ``levels`` (best first): the average price, the levels touched,
    the share of the clip filled beyond the first level. ``complete`` is False when the kept levels run out."""
    if notional_usdt <= 0:
        raise ValueError("notional must be positive")
    remaining = float(notional_usdt)
    quote = 0.0
    base = 0.0
    used = 0
    first_level_quote = 0.0
    for i, (px, sz) in enumerate(levels):
        if remaining <= 1e-9:
            break
        level_quote = px * sz
        take = min(remaining, level_quote)
        if i == 0:
            first_level_quote = take
        base += take / px
        quote += take
        remaining -= take
        used += 1
    complete = remaining <= 1e-9
    avg = quote / base if base > 0 else float("nan")
    beyond = 1.0 - (first_level_quote / notional_usdt)
    return Fill(avg, quote, base, used, max(0.0, min(1.0, beyond)), complete)


def cost_bps(side: str, fill_price: float, reference: Optional[float]) -> float:
    """Positive = worse than the reference for the trader (paid more buying, received less selling)."""
    if reference is None or not (reference > 0) or not (fill_price > 0) or math.isnan(fill_price):
        return float("nan")
    return (fill_price / reference - 1.0) * 1e4 if side == "buy" else (1.0 - fill_price / reference) * 1e4


def bar_boundaries(day: date, timeframe: str) -> List[int]:
    """The bar-close instants of ``timeframe`` inside the UTC ``day`` (the day's 00:00 included, the next day's not)."""
    bar = BAR_MS[timeframe]
    start = _utc_ms(day)
    return [start + k * bar for k in range(DAY_MS // bar)]


def post_only_outcome(trades: TradesSeries, *, t_ms: int, end_ms: int, side: str, limit_px: float, queue_ahead: float, own_base: float) -> Dict[str, Any]:
    """Would a post-only order resting at ``limit_px`` from ``t_ms`` fill before ``end_ms``?

    From the tape alone: it fills when the market trades through the price (a trade strictly beyond it) or when the taker
    volume at exactly that price, on the side that consumes it, reaches the displayed queue ahead plus the order's own size
    (FIFO, cancellations ahead ignored: a lower bound on the fill rate). ``evaluable`` is False when the pooled files do
    not cover the whole bar; such outcomes are not judged.
    """
    out: Dict[str, Any] = {"limit_px": limit_px, "queue_ahead": queue_ahead, "own_base": own_base, "evaluable": trades.covers(t_ms, end_ms),
                           "trades_in_bar": 0, "filled": False, "filled_through": False, "traded_through_at_all": False, "fill_ms": None,
                           "minutes_to_fill": None}
    if not out["evaluable"]:
        return out
    i0 = int(np.searchsorted(trades.ts, t_ms, side="left"))
    i1 = int(np.searchsorted(trades.ts, end_ms, side="left"))
    ts = trades.ts[i0:i1]
    px = trades.price[i0:i1]
    sz = trades.size[i0:i1]
    buy = trades.buy[i0:i1]
    out["trades_in_bar"] = int(ts.size)
    if ts.size == 0:
        return out
    if side == "buy":
        through = px < limit_px - 1e-9
        at = (np.abs(px - limit_px) <= 1e-9) & ~buy  # a taker sold into the bid
    else:
        through = px > limit_px + 1e-9
        at = (np.abs(px - limit_px) <= 1e-9) & buy  # a taker bought from the ask
    t_through = int(ts[np.argmax(through)]) if through.any() else None
    t_queue = None
    if at.any():
        cum = np.cumsum(np.where(at, sz, 0.0))
        hit = cum >= queue_ahead + own_base - 1e-12
        if hit.any():
            t_queue = int(ts[np.argmax(hit)])
    candidates = [t for t in (t_through, t_queue) if t is not None]
    if candidates:
        fill_ms = min(candidates)
        out.update(filled=True, filled_through=t_through is not None and t_through <= fill_ms, fill_ms=fill_ms,
                   minutes_to_fill=(fill_ms - t_ms) / 60_000.0)
    out["traded_through_at_all"] = bool(through.any())
    return out


# -- the replay --------------------------------------------------------------------------------------------------


@dataclass
class ReplayPlan:
    instrument: str
    trades: List[Path]
    candles: List[Path]
    books: List[Tuple[date, Path]]  # UTC days with a book file, oldest first


def plan_replay(root: Path, files: Sequence[ArchiveFile]) -> Dict[str, ReplayPlan]:
    """Per instrument: every trades and candle file on disk (pooled) and the book days to walk."""
    plans: Dict[str, ReplayPlan] = {}
    for f in sorted(files, key=lambda f: (f.instrument, f.kind, f.day)):
        path = Path(root) / f.instrument / f.kind / f.filename
        if not path.exists():
            continue
        plan = plans.setdefault(f.instrument, ReplayPlan(f.instrument, [], [], []))
        if f.kind == "trades":
            plan.trades.append(path)
        elif f.kind == "candles_1m":
            plan.candles.append(path)
        elif f.kind == "book_400":
            plan.books.append((f.day, path))
    return {k: v for k, v in plans.items() if v.trades and v.books}


@dataclass
class _Sample:
    instant_ms: int
    key: Tuple[int, str]  # (boundary t_ms, moment)
    bids: Optional[List[Tuple[float, float]]] = None
    asks: Optional[List[Tuple[float, float]]] = None
    event_ts: Optional[int] = None
    from_first_snapshot: bool = False

    @property
    def taken(self) -> bool:
        return self.bids is not None


class InstrumentReplay:
    """Walks one instrument's book days in order over its pooled trades and candles, carrying the book across consecutive days."""

    def __init__(self, instrument: str, trades: TradesSeries, candles: Mapping[int, Tuple[float, float, float, float]], *,
                 clips: Sequence[float] = CLIP_SIZES_USDT, timeframes: Sequence[str] = TIMEFRAMES, log: Optional[Callable[[str], None]] = None) -> None:
        self.instrument = instrument
        self.trades = trades
        self.candles = candles
        self.clips = tuple(float(c) for c in clips)
        self.timeframes = tuple(timeframes)
        self.log = log or (lambda m: None)
        self.book = OrderBook()
        self.records: List[Dict[str, Any]] = []
        self.coverage: Dict[str, Any] = {
            "instrument": instrument, "days": [], "trades": trades.n, "trade_files": list(trades.files),
            "trades_span": {"first": _iso(int(trades.ts[0])) if trades.n else None, "last": _iso(int(trades.ts[-1])) if trades.n else None},
            "trades_intervals": [{"start": _iso(a), "end": _iso(b)} for a, b in trades.intervals],
            "candles_1m": len(candles),
            "candles_span": {"first": _iso(min(candles)) if candles else None, "last": _iso(max(candles)) if candles else None},
            "book_events": 0, "snapshots": 0, "book_resets": 0, "updates_before_sync": 0,
            "boundaries": {tf: 0 for tf in self.timeframes}, "from_first_snapshot": 0, "day_coverage": [],
        }
        self._prev_day: Optional[date] = None

    def run_day(self, day: date, book_path: Path) -> None:
        t0 = time.time()
        if self._prev_day is not None and day != self._prev_day + timedelta(days=1):
            self.book.reset()
            self.coverage["book_resets"] += 1
        boundaries: List[Tuple[int, str]] = []
        for tf in self.timeframes:
            for t in bar_boundaries(day, tf):
                boundaries.append((t, tf))
        samples: List[_Sample] = []
        first_trade_after: Dict[int, Optional[int]] = {}
        for t in sorted({t for t, _ in boundaries}):
            i = int(np.searchsorted(self.trades.ts, t, side="left"))
            ft = int(self.trades.ts[i]) if i < self.trades.n else None
            if ft is not None and ft - t > NEXT_OPEN_MAX_LAG_MS:
                ft = None
            first_trade_after[t] = ft
            samples.append(_Sample(t, (t, "close")))
            samples.append(_Sample((ft + 1) if ft is not None else t + 1, (t, "next_open")))
            samples.append(_Sample(t + 1001, (t, "plus_1s")))
        samples.sort(key=lambda s: s.instant_ms)
        pending: List[_Sample] = []  # due before the book was synced; filled from the first snapshot and flagged
        idx = 0
        n_events = 0
        n_snapshots = 0
        first_event = None
        last_event = None
        for ts, action, asks, bids in iter_book_events(book_path):
            if first_event is None:
                first_event = ts
            last_event = ts
            while idx < len(samples) and samples[idx].instant_ms <= ts:
                s = samples[idx]
                idx += 1
                if self.book.synced:
                    s.bids, s.asks = self.book.top()
                    s.event_ts = self.book.last_ts
                else:
                    pending.append(s)
            self.book.apply(ts, action, asks, bids)
            n_events += 1
            if action == "snapshot":
                n_snapshots += 1
            if pending and self.book.synced:
                for s in pending:
                    s.bids, s.asks = self.book.top()
                    s.event_ts = self.book.last_ts
                    s.from_first_snapshot = True
                pending.clear()
        while idx < len(samples):  # instants after the file's last event (the file ends at 23:59:59): the day's final state
            s = samples[idx]
            idx += 1
            if self.book.synced and last_event is not None and s.instant_ms - last_event <= COVERAGE_SLACK_MS:
                s.bids, s.asks = self.book.top()
                s.event_ts = self.book.last_ts
        by_key = {s.key: s for s in samples}
        for t, tf in boundaries:
            self.records.append(self._record(day, t, tf, by_key, first_trade_after[t]))
            self.coverage["boundaries"][tf] += 1
        self.coverage["from_first_snapshot"] += sum(1 for s in samples if s.from_first_snapshot and s.taken)
        self.coverage["days"].append(day.isoformat())
        self.coverage["book_events"] += n_events
        self.coverage["snapshots"] += n_snapshots
        self.coverage["updates_before_sync"] = self.book.updates_before_sync
        self.coverage["day_coverage"].append({"day": day.isoformat(), "book_events": n_events, "snapshots": n_snapshots,
                                              "first_event": _iso(first_event), "last_event": _iso(last_event), "seconds": round(time.time() - t0, 1)})
        self._prev_day = day
        self.log(f"{self.instrument} {day}: {n_events:,} book events, {n_snapshots} snapshots, {len(boundaries)} boundaries in {time.time() - t0:.0f}s")

    def _record(self, day: date, t: int, tf: str, by_key: Mapping[Tuple[int, str], _Sample], first_trade_ms: Optional[int]) -> Dict[str, Any]:
        bar = BAR_MS[tf]
        trades = self.trades
        i = int(np.searchsorted(trades.ts, t, side="left"))
        tape_close = float(trades.price[i - 1]) if i > 0 and t - int(trades.ts[i - 1]) <= STALE_REF_MS else None
        tape_close_age = int(t - trades.ts[i - 1]) if i > 0 else None
        tape_open = float(trades.price[i]) if first_trade_ms is not None and i < trades.n else None
        prev_minute = self.candles.get(t - 60_000)
        this_minute = self.candles.get(t)
        candle_close = prev_minute[3] if prev_minute else None
        candle_open = this_minute[0] if this_minute else None
        ref_close = candle_close if candle_close is not None else tape_close
        ref_open = candle_open if candle_open is not None else tape_open
        i1 = int(np.searchsorted(trades.ts, t + bar, side="left"))
        covered = trades.covers(t, t + bar)
        rec: Dict[str, Any] = {
            "instrument": self.instrument, "timeframe": tf, "day": day.isoformat(), "t_ms": t, "t": _iso(t),
            "ref": {"candle_close": candle_close, "candle_open": candle_open, "tape_close": tape_close, "tape_open": tape_open,
                    "tape_close_age_ms": tape_close_age, "first_trade_ms": first_trade_ms,
                    "first_trade_lag_ms": (first_trade_ms - t) if first_trade_ms is not None else None},
            "bar": {"covered": covered, "trades": int(i1 - i) if covered else None,
                    "volume_usdt": float(np.sum(trades.price[i:i1] * trades.size[i:i1])) if covered and i1 > i else None},
            "moments": {}, "post_only": {}, "bar_end_mid": None,
        }
        for moment in MOMENTS:
            s = by_key.get((t, moment))
            if s is None or not s.taken or not s.bids or not s.asks:
                rec["moments"][moment] = {"synced": False}
                continue
            bid, bid_sz = s.bids[0]
            ask, ask_sz = s.asks[0]
            mid = (bid + ask) / 2.0
            m: Dict[str, Any] = {"synced": True, "event_ts": s.event_ts, "from_first_snapshot": s.from_first_snapshot, "bid": bid, "ask": ask,
                                 "bid_size": bid_sz, "ask_size": ask_sz, "mid": mid, "spread_bps": (ask - bid) / mid * 1e4,
                                 "touch_usdt": {"bid": bid * bid_sz, "ask": ask * ask_sz}, "crossed": bid >= ask, "fills": {}}
            for side in SIDES:
                levels = s.asks if side == "buy" else s.bids
                m["fills"][side] = {}
                for clip in self.clips:
                    f = walk_book(levels, clip)
                    m["fills"][side][_clip_key(clip)] = {
                        "avg_px": f.avg_price, "levels": f.levels, "beyond_first_share": f.beyond_first_share, "complete": f.complete,
                        "cost_vs_mid_bps": cost_bps(side, f.avg_price, mid),
                        "cost_vs_close_bps": cost_bps(side, f.avg_price, ref_close),
                        "cost_vs_open_bps": cost_bps(side, f.avg_price, ref_open),
                    }
            rec["moments"][moment] = m
        close = rec["moments"].get("close") or {}
        if close.get("synced") and not close.get("crossed"):
            for side in SIDES:
                limit_px = close["bid"] if side == "buy" else close["ask"]
                queue = close["bid_size"] if side == "buy" else close["ask_size"]
                rec["post_only"][side] = {}
                for clip in self.clips:
                    rec["post_only"][side][_clip_key(clip)] = post_only_outcome(trades, t_ms=t, end_ms=t + bar, side=side, limit_px=limit_px,
                                                                                queue_ahead=queue, own_base=clip / limit_px)
        return rec

    def finish(self) -> List[Dict[str, Any]]:
        """Mark-outs: the mid at each bar's end is the close-moment mid of the boundary one bar later (when replayed)."""
        mid_at: Dict[int, float] = {}
        for r in self.records:
            close = r["moments"].get("close") or {}
            if close.get("synced"):
                mid_at[r["t_ms"]] = close["mid"]
        for r in self.records:
            end_mid = mid_at.get(r["t_ms"] + BAR_MS[r["timeframe"]])
            r["bar_end_mid"] = end_mid
            ref_open = r["ref"]["candle_open"] or r["ref"]["tape_open"]
            for side, by_clip in r["post_only"].items():
                for o in by_clip.values():
                    sign = 1.0 if side == "buy" else -1.0
                    o["markout_bps"] = sign * (end_mid / o["limit_px"] - 1.0) * 1e4 if (end_mid is not None and o["filled"]) else None
                    o["missed_move_bps"] = (sign * (end_mid / ref_open - 1.0) * 1e4
                                            if (end_mid is not None and o["evaluable"] and not o["filled"] and ref_open) else None)
        return self.records


def _clip_key(clip: float) -> str:
    return f"{int(round(clip / 1000))}K"


def replay_archive(root: Path, files: Sequence[ArchiveFile], *, instruments: Sequence[str] = INSTRUMENTS, clips: Sequence[float] = CLIP_SIZES_USDT,
                   timeframes: Sequence[str] = TIMEFRAMES, log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Pool the trades and candles on disk per instrument, then replay every book day; returns records and coverage."""
    plans = plan_replay(root, files)
    say = log or (lambda m: None)
    out: Dict[str, Any] = {"records": [], "coverage": [], "errors": [], "instruments": list(instruments)}
    for inst in instruments:
        plan = plans.get(inst)
        if plan is None:
            out["errors"].append(f"{inst}: no trades file with a 400-level book file on disk")
            continue
        try:
            t0 = time.time()
            trades = concat_trades([load_trades(p, inst) for p in plan.trades])
            candles: Dict[int, Tuple[float, float, float, float]] = {}
            for p in plan.candles:
                candles.update(load_candles_1m(p, inst))
            say(f"{inst}: pooled {trades.n:,} trades from {len(plan.trades)} files and {len(candles):,} 1-minute candles from {len(plan.candles)} files "
                f"in {time.time() - t0:.0f}s; {len(plan.books)} book days")
        except (FillReplayError, OSError, ValueError) as exc:
            out["errors"].append(f"{inst}: {exc}")
            continue
        rp = InstrumentReplay(inst, trades, candles, clips=clips, timeframes=timeframes, log=log)
        for day, book_path in plan.books:
            try:
                rp.run_day(day, book_path)
            except (FillReplayError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                out["errors"].append(f"{inst} {day}: {exc}")
        out["records"].extend(rp.finish())
        out["coverage"].append(rp.coverage)
    return out


# -- summaries ---------------------------------------------------------------------------------------------------


def _clean(values: Iterable[Any]) -> List[float]:
    return [float(v) for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]


def _stats(values: Iterable[Any]) -> Dict[str, Optional[float]]:
    v = _clean(values)
    if not v:
        return {"n": 0, "median": None, "mean": None, "p90": None, "max": None, "min": None}
    arr = np.asarray(v)
    return {"n": int(arr.size), "median": float(np.median(arr)), "mean": float(arr.mean()), "p90": float(np.percentile(arr, 90)),
            "max": float(arr.max()), "min": float(arr.min())}


def summarize(records: Sequence[Mapping[str, Any]], *, clips: Sequence[float] = CLIP_SIZES_USDT) -> Dict[str, Any]:
    """The tables of the report: market-order costs by instrument / timeframe / moment / side / clip, the post-only
    fill rates, the reference cross-checks and the spread, each with sample counts."""
    clip_keys = [_clip_key(c) for c in clips]
    instruments = sorted({r["instrument"] for r in records})
    timeframes = sorted({r["timeframe"] for r in records})
    market: List[Dict[str, Any]] = []
    for inst in instruments:
        for tf in timeframes:
            rows = [r for r in records if r["instrument"] == inst and r["timeframe"] == tf]
            for moment in MOMENTS:
                ms = [r["moments"].get(moment) or {} for r in rows]
                ms = [m for m in ms if m.get("synced") and not m.get("crossed")]
                for side in SIDES:
                    for ck in clip_keys:
                        fills = [m["fills"][side][ck] for m in ms if ck in m["fills"].get(side, {})]
                        complete = [f for f in fills if f["complete"]]
                        market.append({
                            "instrument": inst, "timeframe": tf, "moment": moment, "side": side, "clip": ck, "n": len(complete),
                            "incomplete": len(fills) - len(complete),
                            "vs_mid_bps": _stats(f["cost_vs_mid_bps"] for f in complete),
                            "vs_close_bps": _stats(f["cost_vs_close_bps"] for f in complete),
                            "vs_open_bps": _stats(f["cost_vs_open_bps"] for f in complete),
                            "beyond_first_share": _stats(f["beyond_first_share"] for f in complete),
                            "multi_level_pct": (100.0 * sum(1 for f in complete if f["levels"] > 1) / len(complete)) if complete else None,
                            "levels": _stats(f["levels"] for f in complete),
                            "spread_bps": _stats(m["spread_bps"] for m in ms),
                        })
    post: List[Dict[str, Any]] = []
    for inst in instruments:
        for tf in timeframes:
            rows = [r for r in records if r["instrument"] == inst and r["timeframe"] == tf]
            for side in SIDES:
                for ck in clip_keys:
                    outs = [r["post_only"][side][ck] for r in rows if side in r["post_only"] and ck in r["post_only"][side]]
                    judged = [o for o in outs if o.get("evaluable")]
                    if not outs:
                        continue
                    filled = [o for o in judged if o["filled"]]
                    post.append({
                        "instrument": inst, "timeframe": tf, "side": side, "clip": ck, "n": len(judged), "not_covered": len(outs) - len(judged),
                        "fill_rate": (len(filled) / len(judged)) if judged else None,
                        "fill_rate_through": (sum(1 for o in judged if o.get("traded_through_at_all")) / len(judged)) if judged else None,
                        "fill_rate_queue_only": (sum(1 for o in filled if not o.get("filled_through")) / len(judged)) if judged else None,
                        "minutes_to_fill": _stats(o["minutes_to_fill"] for o in filled),
                        "markout_bps": _stats(o.get("markout_bps") for o in filled),
                        "missed_move_bps": _stats(o.get("missed_move_bps") for o in judged if not o["filled"]),
                        "queue_ahead_usdt": _stats(o["queue_ahead"] * o["limit_px"] for o in judged),
                    })
    refs: List[Dict[str, Any]] = []
    for inst in instruments:
        rows = [r for r in records if r["instrument"] == inst]
        seen: Dict[int, Mapping[str, Any]] = {}
        for r in rows:
            seen.setdefault(r["t_ms"], r["ref"])
        close_diff = [abs(v["tape_close"] / v["candle_close"] - 1) * 1e4 for v in seen.values() if v["tape_close"] and v["candle_close"]]
        open_diff = [abs(v["tape_open"] / v["candle_open"] - 1) * 1e4 for v in seen.values() if v["tape_open"] and v["candle_open"]]
        lags = [v["first_trade_lag_ms"] for v in seen.values() if v["first_trade_lag_ms"] is not None]
        ages = [v["tape_close_age_ms"] for v in seen.values() if v["tape_close_age_ms"] is not None]
        close_open = [abs(v["candle_open"] / v["candle_close"] - 1) * 1e4 for v in seen.values() if v["candle_open"] and v["candle_close"]]
        refs.append({"instrument": inst, "boundaries": len(seen), "with_close_ref": sum(1 for v in seen.values() if v["candle_close"] or v["tape_close"]),
                     "with_open_ref": sum(1 for v in seen.values() if v["candle_open"] or v["tape_open"]),
                     "close_tape_vs_candle_bps": _stats(close_diff), "open_tape_vs_candle_bps": _stats(open_diff),
                     "first_trade_lag_ms": _stats(lags), "lag_over_1s_pct": (100.0 * sum(1 for lag in lags if lag > 1000) / len(lags)) if lags else None,
                     "last_trade_age_ms": _stats(ages), "open_minus_close_abs_bps": _stats(close_open)})
    return {"market_orders": market, "post_only": post, "references": refs, "clips": clip_keys, "instruments": instruments, "timeframes": timeframes}


def engine_default_summary() -> Dict[str, float]:
    return {"fee_bps_per_side": ENGINE_DEFAULT.fee_rate * 1e4, "slippage_bps_per_side": ENGINE_DEFAULT.slippage_rate * 1e4,
            "round_trip_bps": 2 * (ENGINE_DEFAULT.fee_rate + ENGINE_DEFAULT.slippage_rate) * 1e4}


def build_results(replay: Mapping[str, Any], *, files: Sequence[ArchiveFile], archive_root: Path, now: datetime, clips: Sequence[float] = CLIP_SIZES_USDT,
                  window: Optional[Tuple[date, date]] = None) -> Dict[str, Any]:
    records = list(replay["records"])
    manifests = []
    for f in files:
        path = Path(archive_root) / f.instrument / f.kind / f.filename
        mp = ArchiveDownloader.manifest_for(path)
        if mp.exists():
            m = json.loads(mp.read_text(encoding="utf-8"))
            manifests.append({k: m.get(k) for k in ("instrument", "kind", "day", "filename", "listed_size_mb", "size_bytes", "sha256", "fetched_at")})
    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plan_row": "R22",
        "window": {"start": window[0].isoformat(), "end": window[1].isoformat()} if window else None,
        "instruments": list(replay.get("instruments") or sorted({r["instrument"] for r in records})),
        "clips_usdt": [float(c) for c in clips],
        "timeframes": list(TIMEFRAMES),
        "moments": {"close": "the book after the last event before the bar close", "next_open": "the book at the next bar's first trade",
                    "plus_1s": "the book one second after the bar close"},
        "engine_default": engine_default_summary(),
        "coverage": replay["coverage"],
        "errors": replay["errors"],
        "files": manifests,
        "summary": summarize(records, clips=clips),
        "records": records,
    }


def _rounded(o: Any) -> Any:
    if isinstance(o, float):
        return None if math.isnan(o) else round(o, 6)
    if isinstance(o, dict):
        return {k: _rounded(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_rounded(v) for v in o]
    return o


def write_results(path: Path, results: Mapping[str, Any]) -> Path:
    """JSON with the summaries indented and each boundary record on one line (readable diff, bounded size)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    head = {k: v for k, v in results.items() if k != "records"}
    text = json.dumps(head, indent=1, sort_keys=True, default=_json_default)
    lines = [json.dumps(_rounded(r), sort_keys=True, default=_json_default) for r in results.get("records", [])]
    if lines:
        body = text[:-2] + ",\n \"records\": [\n" + ",\n".join("  " + ln for ln in lines) + "\n ]\n}\n"
    else:
        body = text[:-2] + ",\n \"records\": []\n}\n"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)
    return path


def _json_default(o: Any) -> Any:
    if isinstance(o, (np.floating,)):
        v = float(o)
        return None if math.isnan(v) else v
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, float) and math.isnan(o):
        return None
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


# -- Markdown tables ---------------------------------------------------------------------------------------------


def _fmt(v: Optional[float], digits: int = 2) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "-"
    return f"{v:.{digits}f}"


def _pct(v: Optional[float]) -> str:
    return "-" if v is None else f"{100 * v:.0f} %"


def render_tables(results: Mapping[str, Any]) -> str:
    s = results["summary"]
    eng = results["engine_default"]
    out: List[str] = []
    out.append(f"Generated by `scripts/run_fill_replay.py --replay` on {results['generated_at']}. Engine default: {eng['fee_bps_per_side']:.0f} bps fee + "
               f"{eng['slippage_bps_per_side']:.0f} bps slippage a side ({eng['round_trip_bps']:.0f} bps a round trip). Costs are in basis points, "
               "positive = worse for the trader; n = bar boundaries replayed.\n")
    out.append("**A. Coverage**\n")
    out.append("| Instrument | Book days | First | Last | Trades pooled | Tape from | Tape to | Book events | Snapshots | Resets | 4H boundaries | 6H boundaries | Samples from the first snapshot |")
    out.append("|---|---:|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|")
    for c in results["coverage"]:
        days = c["days"]
        out.append(f"| {c['instrument']} | {len(days)} | {days[0] if days else '-'} | {days[-1] if days else '-'} | {c['trades']:,} | "
                   f"{(c['trades_span']['first'] or '-')[:16]} | {(c['trades_span']['last'] or '-')[:16]} | {c['book_events']:,} | {c['snapshots']:,} | "
                   f"{c['book_resets']} | {c['boundaries'].get('4H', 0)} | {c['boundaries'].get('6H', 0)} | {c['from_first_snapshot']} |")
    out.append("")
    out.append("**B. Market orders at the bar close: cost against the mid (bps), by clip and side** (median / mean / p90 / max over the boundaries; "
               "spread = the quoted spread at that moment)\n")
    out.append("| Instrument | TF | Side | Clip | n | vs mid median | mean | p90 | max | beyond 1st level (mean share) | clips touching 2+ levels | spread median bps |")
    out.append("|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in s["market_orders"]:
        if row["moment"] != "close":
            continue
        out.append(f"| {row['instrument']} | {row['timeframe']} | {row['side']} | {row['clip']} | {row['n']} | {_fmt(row['vs_mid_bps']['median'])} | "
                   f"{_fmt(row['vs_mid_bps']['mean'])} | {_fmt(row['vs_mid_bps']['p90'])} | {_fmt(row['vs_mid_bps']['max'])} | "
                   f"{_fmt(row['beyond_first_share']['mean'], 3)} | {_fmt(row['multi_level_pct'], 0)} % | {_fmt(row['spread_bps']['median'])} |")
    out.append("")
    out.append(f"**C. Cost against the candle close and against the next bar's open (the engine's assumed fill price; the engine charges "
               f"{eng['slippage_bps_per_side']:.0f} bps a side), by moment** (median / mean / p90; n = boundaries with that reference)\n")
    out.append("| Instrument | TF | Moment | Side | Clip | n | vs close median | mean | p90 | vs next open median | mean | p90 | engine slippage |")
    out.append("|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in s["market_orders"]:
        out.append(f"| {row['instrument']} | {row['timeframe']} | {row['moment']} | {row['side']} | {row['clip']} | {row['vs_open_bps']['n']} | "
                   f"{_fmt(row['vs_close_bps']['median'])} | {_fmt(row['vs_close_bps']['mean'])} | {_fmt(row['vs_close_bps']['p90'])} | "
                   f"{_fmt(row['vs_open_bps']['median'])} | {_fmt(row['vs_open_bps']['mean'])} | {_fmt(row['vs_open_bps']['p90'])} | "
                   f"{eng['slippage_bps_per_side']:.0f} |")
    out.append("")
    out.append("**D. Post-only at the touch: did it fill within one bar?** (limit at the best bid/ask of the close moment, FIFO behind the displayed "
               "queue, cancellations ahead ignored; \"traded through\" = the market printed beyond the limit at some point in the bar; \"queue only\" = "
               "filled by volume at the price before any trade through it; mark-out = the mid at the bar's end against the limit price, positive = the "
               "fill was favourable; missed move = the same for the unfilled orders against the next open the engine would have paid; n = bars whose "
               "trades the files cover)\n")
    out.append("| Instrument | TF | Side | Clip | n | fill rate | traded through | queue only | median minutes to fill | mark-out filled mean bps | missed move unfilled mean bps | queue ahead median USDT |")
    out.append("|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in s["post_only"]:
        out.append(f"| {row['instrument']} | {row['timeframe']} | {row['side']} | {row['clip']} | {row['n']} | {_pct(row['fill_rate'])} | "
                   f"{_pct(row['fill_rate_through'])} | {_pct(row['fill_rate_queue_only'])} | {_fmt(row['minutes_to_fill']['median'], 1)} | "
                   f"{_fmt(row['markout_bps']['mean'])} | {_fmt(row['missed_move_bps']['mean'])} | {_fmt(row['queue_ahead_usdt']['median'], 0)} |")
    out.append("")
    out.append("**E. Reference cross-check: the tape against the archive's 1-minute candles, and the next bar's first trade**\n")
    out.append("| Instrument | Boundaries | with close ref | with open ref | close: tape vs candle, max bps | open: tape vs candle, max bps | first trade lag median ms | p90 ms | lag > 1 s | last trade age median ms | abs(open - close) median bps | p90 |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in s["references"]:
        out.append(f"| {row['instrument']} | {row['boundaries']} | {row['with_close_ref']} | {row['with_open_ref']} | {_fmt(row['close_tape_vs_candle_bps']['max'], 3)} | "
                   f"{_fmt(row['open_tape_vs_candle_bps']['max'], 3)} | {_fmt(row['first_trade_lag_ms']['median'], 0)} | {_fmt(row['first_trade_lag_ms']['p90'], 0)} | "
                   f"{_fmt(row['lag_over_1s_pct'], 1)} % | {_fmt(row['last_trade_age_ms']['median'], 0)} | {_fmt(row['open_minus_close_abs_bps']['median'])} | "
                   f"{_fmt(row['open_minus_close_abs_bps']['p90'])} |")
    out.append("")
    return "\n".join(out)


def headline(results: Mapping[str, Any]) -> Dict[str, Any]:
    """A few numbers for the console and the report: the largest clip's cost against the next open at the close moment, pooled."""
    s = results["summary"]
    head: Dict[str, Any] = {}
    for inst in s["instruments"]:
        rows = [r for r in s["market_orders"] if r["instrument"] == inst and r["moment"] == "close"]
        if not rows:
            continue
        big = [r for r in rows if r["clip"] == s["clips"][-1]]
        small = [r for r in rows if r["clip"] == s["clips"][0]]
        big_med = _clean(r["vs_open_bps"]["median"] for r in big)
        small_med = _clean(r["vs_mid_bps"]["median"] for r in small)
        rates = _clean(r["fill_rate"] for r in s["post_only"] if r["instrument"] == inst)
        head[inst] = {
            "largest_clip": s["clips"][-1],
            "largest_clip_vs_open_median_bps": statistics.fmean(big_med) if big_med else None,
            "largest_clip_vs_open_p90_bps": max(_clean(r["vs_open_bps"]["p90"] for r in big), default=None),
            "smallest_clip_vs_mid_median_bps": statistics.fmean(small_med) if small_med else None,
            "post_only_fill_rate_min": min(rates, default=None),
            "post_only_fill_rate_max": max(rates, default=None),
        }
    return head
