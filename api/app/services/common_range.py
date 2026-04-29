"""共通の実績期間レンジを定義し、各サービスのデータをそのレンジに揃える。

思想:
  GDPギャップで表示している実績期間を基準として全パネルの開始・終了を合わせる。
  予測（IS-LMの金利・為替予測）は据え置き、実績データのみフィルタ対象。

外部公開関数:
  - get_actual_period_range() -> (start_quarter, end_quarter)
      "YYYY-Qn" 形式の開始・終了クォーターを返す。GDPギャップ実績データに基づく。
  - filter_to_actual_range(data, key="date") -> filtered list
      `date` フィールド（"YYYY-Qn" / "YYYY-MM" / "YYYY-MM-DD"）を解釈し
      共通レンジ内のデータのみ残す。

環境変数:
  - DASHBOARD_RANGE_START / DASHBOARD_RANGE_END で上書き可能（テスト・デバッグ用）
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import date

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# キャッシュ（_RANGE_TTL 秒）
# ---------------------------------------------------------------------------

_RANGE_TTL = 3600  # 1 hour
_range_cache: tuple[float, tuple[str, str]] | None = None


# ---------------------------------------------------------------------------
# クォーターラベル ⇄ (年, 四半期番号) 変換
# ---------------------------------------------------------------------------


def _parse_quarter_label(label: str) -> tuple[int, int] | None:
    """'YYYY-Qn' → (year, q). Returns None if format mismatched."""
    m = re.match(r"^(\d{4})-Q([1-4])$", str(label).strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _quarter_index(year: int, q: int) -> int:
    """Sortable monotonic index: year*4 + (q-1)."""
    return year * 4 + (q - 1)


def _date_to_quarter(year: int, month: int) -> tuple[int, int]:
    """月から所属四半期を返す。"""
    return year, (month - 1) // 3 + 1


def _parse_iso_date(s: str) -> tuple[int, int, int] | None:
    """'YYYY-MM' or 'YYYY-MM-DD' を (year, month, day) に。失敗時 None。"""
    s = str(s).strip()
    m = re.match(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$", s)
    if not m:
        return None
    year = int(m.group(1))
    month = int(m.group(2))
    day = int(m.group(3)) if m.group(3) else 1
    return year, month, day


# ---------------------------------------------------------------------------
# 公開API: 共通レンジ取得
# ---------------------------------------------------------------------------


def _compute_range_from_gdp_gap() -> tuple[str, str] | None:
    """gdp_gap_service の実績データから実績期間レンジを算出。

    estimated_average の data（mock または FRED 実データ）の最初と最後の
    クォーターラベルを返す。失敗時 None。
    """
    try:
        # 遅延importで循環参照を回避
        from app.services.gdp_gap_service import (
            _MOCK_REAL_GDP,
            _QUARTERS,
            _fetch_real_gdp,
        )

        result = _fetch_real_gdp()
        if result is not None:
            _, quarters = result
        else:
            quarters = list(_QUARTERS)
            # _MOCK_REAL_GDP と長さを揃える
            if len(quarters) > len(_MOCK_REAL_GDP):
                quarters = quarters[: len(_MOCK_REAL_GDP)]

        if not quarters:
            return None

        # 最初・最後の有効クォーターラベル
        valid = [q for q in quarters if _parse_quarter_label(q) is not None]
        if not valid:
            return None
        return valid[0], valid[-1]
    except Exception:
        logger.exception("共通レンジ算出に失敗")
        return None


def get_actual_period_range() -> tuple[str, str]:
    """実績期間の (start_quarter, end_quarter) を返す。"""
    global _range_cache

    # 環境変数による上書き
    env_start = os.getenv("DASHBOARD_RANGE_START")
    env_end = os.getenv("DASHBOARD_RANGE_END")
    if env_start and env_end:
        return env_start, env_end

    now = time.monotonic()
    if _range_cache is not None:
        expires_at, value = _range_cache
        if now < expires_at:
            return value

    computed = _compute_range_from_gdp_gap()
    if computed is None:
        # フォールバック: 当年と前年4Qで広めに切る
        today = date.today()
        end_year = today.year
        start_year = end_year - 24
        computed = (f"{start_year}-Q1", f"{end_year}-Q4")
        logger.warning(
            "共通レンジをGDPギャップから取得できず。フォールバック: %s〜%s",
            computed[0],
            computed[1],
        )

    _range_cache = (now + _RANGE_TTL, computed)
    return computed


def reset_cache() -> None:
    """テスト用: レンジキャッシュをクリア。"""
    global _range_cache
    _range_cache = None


# ---------------------------------------------------------------------------
# データフィルタ
# ---------------------------------------------------------------------------


def _is_in_quarter_range(
    year: int, q: int, start_yq: tuple[int, int], end_yq: tuple[int, int]
) -> bool:
    idx = _quarter_index(year, q)
    return _quarter_index(*start_yq) <= idx <= _quarter_index(*end_yq)


def _parse_year_only(s: str) -> int | None:
    """'YYYY' → year (int). Returns None if not a bare 4-digit year."""
    m = re.match(r"^(\d{4})$", str(s).strip())
    return int(m.group(1)) if m else None


def is_date_in_range(date_str: str, range_: tuple[str, str] | None = None) -> bool:
    """date_str が共通レンジ内かを判定。

    対応フォーマット:
      - 'YYYY-Qn'    クォーター: 直接マッチ
      - 'YYYY-MM'    月次: 当該月の所属クォーターがレンジ内なら true
      - 'YYYY-MM-DD' 日次: 同上
      - 'YYYY'       年次: その年のいずれかの四半期がレンジ内なら true
    """
    rng = range_ or get_actual_period_range()
    start_yq = _parse_quarter_label(rng[0])
    end_yq = _parse_quarter_label(rng[1])
    if start_yq is None or end_yq is None:
        return True  # レンジ不正なら除外しない

    # 1) クォーター直書き
    yq = _parse_quarter_label(date_str)
    if yq is not None:
        return _is_in_quarter_range(yq[0], yq[1], start_yq, end_yq)

    # 2) 月次・日次
    iso = _parse_iso_date(date_str)
    if iso is not None:
        year, month, _day = iso
        y, q = _date_to_quarter(year, month)
        return _is_in_quarter_range(y, q, start_yq, end_yq)

    # 3) 年次 ("YYYY"): その年のいずれかの四半期がレンジ内なら true
    year_only = _parse_year_only(date_str)
    if year_only is not None:
        for q in (1, 2, 3, 4):
            if _is_in_quarter_range(year_only, q, start_yq, end_yq):
                return True
        return False

    # 不明形式: 残す（破壊的にしない）
    return True


def filter_to_actual_range(
    items: list,
    key: str = "date",
    range_: tuple[str, str] | None = None,
    label: str | None = None,
) -> list:
    """共通レンジに収まる要素のみ返す。

    items は dict のリスト or `.date` 属性を持つ pydantic モデルのリストを想定。
    極端に減った場合は警告ログを出す。
    """
    rng = range_ or get_actual_period_range()
    out = []
    for item in items:
        if isinstance(item, dict):
            d = item.get(key)
        else:
            d = getattr(item, key, None)
        if d is None:
            out.append(item)
            continue
        if is_date_in_range(str(d), rng):
            out.append(item)

    if items and len(out) < max(2, len(items) // 4) and label:
        logger.warning(
            "共通レンジ適用で %s のデータ点が %d → %d に減少（レンジ %s〜%s）",
            label,
            len(items),
            len(out),
            rng[0],
            rng[1],
        )
    return out
