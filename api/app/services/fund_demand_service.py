"""Fund demand data: FRED Bank Lending + BOJ Flow of Funds.

Real data sources:
  - Bank Lending: FRED series CRDQJPAPABIS (BIS total credit to private
    non-financial sector, quarterly, billions of JPY).
  - Flow of Funds: BOJ 時系列データ検索サイトの公式ダウンロード ZIP
    (https://www.stat-search.boj.or.jp/info/fof2_en.zip) を取得し、
    部門別「Liabilities/Financial surplus or deficit/.../Flow」系列
    （家計 FOF_FFAF430L700, 非金融法人 FOF_FFAF410L700,
    一般政府 FOF_FFAF420L700）の四半期値を抽出する。
    フォールバックは BOJ Excel (sjexp.htm 配下) → e-Stat API → モック。

Each source falls back to mock data independently on failure.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import zipfile
from datetime import datetime, timedelta

from app.models.schemas import (
    BankLending,
    BankLendingDataPoint,
    FlowOfFunds,
    FlowOfFundsDataPoint,
    FundDemandResponse,
)
from app.services.cache import cached
from app.services.common_range import filter_to_actual_range
from app.services.data_utils import (
    estat_available,
    fetch_estat_stats_data,
    record_data_source_status,
    warn_fred_key_missing_once,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

_MOCK_FLOW_OF_FUNDS: list[dict] = []
for q in ["2022-Q1", "2022-Q2", "2022-Q3", "2022-Q4",
           "2023-Q1", "2023-Q2", "2023-Q3", "2023-Q4",
           "2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4"]:
    _MOCK_FLOW_OF_FUNDS.extend([
        {"date": q, "sector": "households",    "net_lending": round(12.0 + (hash(q) % 10) * 0.5, 1)},
        {"date": q, "sector": "corporations",  "net_lending": round(-4.0 + (hash(q) % 6) * 0.3, 1)},
        {"date": q, "sector": "government",    "net_lending": round(-18.0 - (hash(q) % 8) * 0.4, 1)},
    ])

_MOCK_BANK_LENDING: list[dict] = [
    {"date": "2022-01", "total_lending": 510.2, "yoy_change_percent": 1.5},
    {"date": "2022-04", "total_lending": 513.0, "yoy_change_percent": 1.8},
    {"date": "2022-07", "total_lending": 516.5, "yoy_change_percent": 2.0},
    {"date": "2022-10", "total_lending": 518.1, "yoy_change_percent": 2.1},
    {"date": "2023-01", "total_lending": 520.3, "yoy_change_percent": 2.0},
    {"date": "2023-04", "total_lending": 523.0, "yoy_change_percent": 1.9},
    {"date": "2023-07", "total_lending": 526.2, "yoy_change_percent": 1.9},
    {"date": "2023-10", "total_lending": 528.5, "yoy_change_percent": 2.0},
    {"date": "2024-01", "total_lending": 530.0, "yoy_change_percent": 1.9},
    {"date": "2024-04", "total_lending": 532.5, "yoy_change_percent": 1.8},
    {"date": "2024-07", "total_lending": 535.0, "yoy_change_percent": 1.7},
    {"date": "2024-10", "total_lending": 537.0, "yoy_change_percent": 1.6},
]


# ---------------------------------------------------------------------------
# Quarter helpers
# ---------------------------------------------------------------------------

_Q_MONTH = {1: "01", 2: "04", 3: "07", 4: "10"}


def _quarter_month(ts) -> str:
    """Return 'YYYY-MM' for the start month of the quarter containing *ts*."""
    q = (ts.month - 1) // 3 + 1
    return f"{ts.year}-{_Q_MONTH[q]}"


# BOJ FOF: sector code -> (series id, output sector label)
# 系列名は "Liabilities/Financial surplus or deficit/<sector>/Flow"
# 値は 億円 (Not seasonally adjusted)。10000 で割って兆円に変換する。
_BOJ_FOF_SERIES: dict[str, str] = {
    "households":   "FOF_FFAF430L700",
    "corporations": "FOF_FFAF410L700",  # Nonfinancial corporations
    "government":   "FOF_FFAF420L700",  # General government
}

# 公式 ZIP（四半期 + 年度）。BOJ は同 URL を最新版で更新する運用。
_BOJ_FOF_ZIP_URL = "https://www.stat-search.boj.or.jp/info/fof2_en.zip"
_BOJ_FOF_QUARTERLY_FILE = "ff_dl_fof_quarterly_en.csv"


# ---------------------------------------------------------------------------
# Live data fetchers
# ---------------------------------------------------------------------------


@cached("fred_bank_lending")
def _fetch_bank_lending() -> list[BankLendingDataPoint] | None:
    """Fetch bank lending from FRED (BIS total credit, quarterly, billions JPY)."""
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        warn_fred_key_missing_once()
        logger.debug("FRED_API_KEY not set -- using mock bank lending")
        record_data_source_status(
            "fred:bank_lending", ok=False, detail="api_key_missing"
        )
        return None
    try:
        from fredapi import Fred

        fred = Fred(api_key=api_key)
        end = datetime.now()
        # Fetch 26 years so we have 1 extra year for YoY calculation
        start = end - timedelta(days=365 * 26)
        series = fred.get_series(
            "CRDQJPAPABIS", observation_start=start, observation_end=end
        )
        series = series.dropna()
        if series.empty:
            return None

        # Convert billions JPY -> trillion JPY
        series_trillion = series / 1000.0

        # Build a dict keyed by (year, quarter) for YoY lookup
        by_yq: dict[tuple[int, int], tuple] = {}
        for ts, val in series_trillion.items():
            q = (ts.month - 1) // 3 + 1
            by_yq[(ts.year, q)] = (ts, float(val))

        results: list[BankLendingDataPoint] = []
        # Only output the last ~5 years (skip first year used for YoY baseline)
        cutoff = end - timedelta(days=365 * 25)
        for (year, q), (ts, val) in sorted(by_yq.items()):
            if ts < cutoff:
                continue
            prev = by_yq.get((year - 1, q))
            if prev is not None:
                _, prev_val = prev
                yoy = round((val - prev_val) / prev_val * 100, 1)
            else:
                yoy = 0.0
            results.append(
                BankLendingDataPoint(
                    date=_quarter_month(ts),
                    total_lending=round(val, 1),
                    yoy_change_percent=yoy,
                )
            )
        if results:
            record_data_source_status(
                "fred:bank_lending", ok=True, detail=f"points={len(results)}"
            )
            return results
        record_data_source_status(
            "fred:bank_lending", ok=False, detail="empty_series"
        )
        return None
    except Exception as e:
        logger.exception("FRED bank lending fetch failed")
        record_data_source_status(
            "fred:bank_lending", ok=False, detail=f"exception:{type(e).__name__}"
        )
        return None


# ---------------------------------------------------------------------------
# Flow of Funds: A) BOJ 時系列データ検索サイト 公式 ZIP
# ---------------------------------------------------------------------------


def _parse_boj_quarterly_csv(csv_bytes: bytes) -> list[FlowOfFundsDataPoint] | None:
    """BOJ 時系列データ検索サイト形式 CSV をパースして部門別 net_lending を返す。

    CSV 形式:
      行0 (ヘッダ): "",  "",  "",  "199704", "199801", ..., "202504"
      行1 以降    : 系列ID, グループ名, 系列名, 値, 値, ...
    値は 億円。1万で割って兆円に丸める。
    """
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return None
    header = rows[0]
    # 期間ラベルは index 3 以降。例: "202404" -> (2024, 4)
    period_cols: list[tuple[int, int, int]] = []  # (col_index, year, quarter)
    for i in range(3, len(header)):
        s = header[i].strip()
        if len(s) == 6 and s.isdigit():
            year = int(s[:4])
            q = int(s[4:])
            if 1 <= q <= 4:
                period_cols.append((i, year, q))
    if not period_cols:
        logger.warning("BOJ FOF CSV: no period columns parsed")
        return None

    # 系列ID -> 行 のインデックス
    series_row: dict[str, list[str]] = {}
    target_ids = set(_BOJ_FOF_SERIES.values())
    for row in rows[1:]:
        if not row:
            continue
        sid = row[0].strip()
        if sid in target_ids:
            series_row[sid] = row

    points: list[FlowOfFundsDataPoint] = []
    for sector, sid in _BOJ_FOF_SERIES.items():
        row = series_row.get(sid)
        if row is None:
            logger.warning("BOJ FOF series %s (%s) not found", sid, sector)
            continue
        for col, year, q in period_cols:
            if col >= len(row):
                continue
            cell = row[col].strip()
            if not cell:
                continue
            try:
                val_oku = float(cell)
            except ValueError:
                continue
            # 億円 -> 兆円
            val_trillion = round(val_oku / 10000.0, 1)
            points.append(
                FlowOfFundsDataPoint(
                    date=f"{year}-Q{q}",
                    sector=sector,
                    net_lending=val_trillion,
                )
            )
    if not points:
        return None
    # 並び順: 日付昇順, sector 順 households -> corporations -> government
    sector_order = {"households": 0, "corporations": 1, "government": 2}
    points.sort(
        key=lambda p: (p.date, sector_order.get(p.sector, 99))
    )
    return points


def _fetch_flow_of_funds_via_boj_search() -> list[FlowOfFundsDataPoint] | None:
    """A) BOJ 時系列データ検索サイト (stat-search.boj.or.jp) の公式 ZIP を取得。

    URL: https://www.stat-search.boj.or.jp/info/fof2_en.zip
    中身: ff_dl_fof_quarterly_en.csv (四半期、全系列)
    """
    try:
        import httpx

        resp = httpx.get(
            _BOJ_FOF_ZIP_URL,
            timeout=60.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (japan-economic-dashboard)"},
        )
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            names = zf.namelist()
            if _BOJ_FOF_QUARTERLY_FILE not in names:
                logger.warning(
                    "BOJ FOF zip missing %s (got %s)",
                    _BOJ_FOF_QUARTERLY_FILE,
                    names,
                )
                return None
            csv_bytes = zf.read(_BOJ_FOF_QUARTERLY_FILE)
        points = _parse_boj_quarterly_csv(csv_bytes)
        if points:
            logger.info(
                "BOJ FOF (stat-search ZIP) parsed: %d points across %d sectors",
                len(points),
                len({p.sector for p in points}),
            )
        return points
    except Exception:
        logger.exception("BOJ stat-search FOF fetch failed")
        return None


# ---------------------------------------------------------------------------
# Flow of Funds: B) BOJ 公表ページ (Excel / 直接 CSV) フォールバック
# ---------------------------------------------------------------------------


def _fetch_flow_of_funds_via_boj_xlsx() -> list[FlowOfFundsDataPoint] | None:
    """B) BOJ 資金循環統計の公表ページ Excel フォールバック。

    現状、公表ページ自体 (https://www.boj.or.jp/statistics/sj/sjexp.htm) が
    リダイレクト/再編により 404 を返すことを task-director 側で確認済。
    将来 URL 復活した場合に備えてフックだけ残す（TODO: URL 検証要）。

    URL 検証要 TODO:
      - https://www.boj.or.jp/statistics/sj/sjexp.htm  (現在 404)
      - https://www.boj.or.jp/statistics/sj/sjhiq.htm  (現在 404)
      - 復活時は openpyxl で部門別 NL/NB シートを抽出する実装を入れる。
    """
    logger.info(
        "BOJ public page (sjexp.htm/sjhiq.htm) fallback skipped: URLs currently 404; "
        "TODO 再公開時に Excel パースを実装"
    )
    return None


# ---------------------------------------------------------------------------
# Flow of Funds: C) e-Stat API フォールバック
# ---------------------------------------------------------------------------


def _fetch_flow_of_funds_via_estat() -> list[FlowOfFundsDataPoint] | None:
    """C) e-Stat API フォールバック。

    e-Stat 上の資金循環統計は政府統計コード 003 (BOJ 提供) で登録されており、
    部門別純貸出/純借入の statsDataId は時期により変わる（例 0003109741 系）。
    appId 未設定または該当表が見つからない場合は None を返す。

    URL 検証要 TODO:
      - 安定した statsDataId が確定していないため、現状は呼ばれても None を返す
        スタブ実装。将来 e-Stat 側で 安定 ID が確定したら埋める。
    """
    if not estat_available():
        logger.info("ESTAT_APP_ID not set -- skipping e-Stat FOF fallback")
        return None
    # スタブ: 安定 statsDataId が決まっていないため未実装
    logger.info(
        "e-Stat FOF fallback: stable statsDataId not yet pinned; "
        "TODO 部門別純貸出/純借入の表 ID 確定後に実装"
    )
    # 参考: 試し打ちのフックを残す（コメントアウト）。
    # data = fetch_estat_stats_data("0003109741")
    # if data is None: return None
    # ... parse VALUE objects, map cat01 -> sector, time -> YYYY-Qn ...
    return None


# ---------------------------------------------------------------------------
# Flow of Funds: 順次試行
# ---------------------------------------------------------------------------


@cached("boj_flow_of_funds")
def _fetch_flow_of_funds() -> list[FlowOfFundsDataPoint] | None:
    """A → B → C の順に試行。最初に成功したものを返す。

    全失敗時は None。呼び出し側でモックにフォールバックする。
    """
    for label, fn in (
        ("A:boj-stat-search", _fetch_flow_of_funds_via_boj_search),
        ("B:boj-xlsx",        _fetch_flow_of_funds_via_boj_xlsx),
        ("C:estat",           _fetch_flow_of_funds_via_estat),
    ):
        try:
            result = fn()
        except Exception:
            logger.exception("flow_of_funds path %s raised", label)
            continue
        if result:
            logger.info("flow_of_funds source picked: %s (%d points)", label, len(result))
            return result
        logger.info("flow_of_funds source %s returned no data", label)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_fund_demand() -> FundDemandResponse:
    """Return fund demand data. Falls back to mock on failure.

    各系列の取得成否（real / mock）はログに記録する。
    flow_of_funds は A) BOJ stat-search ZIP → B) BOJ 公表ページ Excel
    → C) e-Stat API → モック の順で試行する。
    """

    status: dict[str, str] = {}

    # Bank lending (via FRED)
    lending_data = _fetch_bank_lending()
    status["bank_lending"] = "real" if lending_data else "mock"
    if lending_data is None:
        lending_data = [BankLendingDataPoint(**d) for d in _MOCK_BANK_LENDING]

    # Flow of funds (A→B→C→mock)
    flow_data = _fetch_flow_of_funds()
    status["flow_of_funds"] = "real" if flow_data else "mock"
    if flow_data is None:
        flow_data = [FlowOfFundsDataPoint(**d) for d in _MOCK_FLOW_OF_FUNDS]

    logger.info("fund_demand data sources: %s", status)

    # 共通レンジ（GDPギャップ実績期間）に揃える
    lending_data = filter_to_actual_range(lending_data, label="bank_lending")
    flow_data = filter_to_actual_range(flow_data, label="flow_of_funds")

    return FundDemandResponse(
        flow_of_funds=FlowOfFunds(data=flow_data),
        bank_lending=BankLending(data=lending_data),
        data_status=status,
    )
