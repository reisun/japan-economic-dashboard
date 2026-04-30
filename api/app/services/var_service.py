"""統計的時系列モデル（VAR / AR(1)）による予測サービス。

理論モデル（IS-LM）と並置するための、データ駆動のベンチマーク予測を提供する。

実装方針
--------
- numpy のみで OLS-VAR を実装（statsmodels には依存しない）
- 内生変数: GDPギャップ(%), JGB10年利回り(%), USD/JPY, CPIコアコア(YoY%)
- ラグ次数 p=4（四半期データなので1年）
- 予測ホライズン: 8四半期（2年）
- IRF: 財政支出ショック → 各変数への波及（GDPギャップショック経由の簡略 IRF）

データソース
------------
既存サービス（gdp_gap_service / rates_service / inflation_service）から共通範囲で
取得し、四半期パネルに揃える。月次データ（金利・為替・CPI）は四半期平均にする。

備考
----
本実装は教育・比較用途。短い期間サンプル（多くて20-30四半期）でラグ4のVARを
推定するため統計的精度には限界があるが、IS-LM 構造モデルとの定性的比較には十分。
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

import numpy as np

from app.models.schemas import (
    Assumptions,
    CurrentGap,
    ExchangeRatePrediction,
    GdpImpactPoint,
    ImpactPrediction,
    InflationPredictionPoint,
    InterestRatePrediction,
    IrfPoint,
    PredictionResponse,
    RequiredFiscalSpending,
)
from app.services.gdp_gap_service import get_gdp_gap
from app.services.inflation_service import get_inflation
from app.services.prediction_service import _get_nominal_gdp
from app.services.rates_service import get_rates

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VAR_LAG_ORDER = 4
PREDICTION_STEPS = 8  # 予測四半期数
FISCAL_MULTIPLIER = 1.0
VARIABLE_NAMES = ["gdp_gap", "jgb_10y", "usdjpy", "cpi_core_core"]

VALID_METHODS = ("cabinet_office", "average", "maximum", "civilian")


# ---------------------------------------------------------------------------
# 四半期パネルの組み立て
# ---------------------------------------------------------------------------

_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")
_ISO_RE = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$")


def _to_quarter_label(s: str) -> str | None:
    """任意の日付文字列を `YYYY-QN` ラベルに正規化（不可なら None）。"""
    s = (s or "").strip()
    m = _QUARTER_RE.match(s)
    if m:
        return s
    m = _ISO_RE.match(s)
    if m:
        y = int(m.group(1))
        mo = int(m.group(2))
        q = (mo - 1) // 3 + 1
        return f"{y}-Q{q}"
    return None


def _aggregate_to_quarterly(
    points: list[dict[str, Any]], value_key: str
) -> dict[str, float]:
    """月次/任意頻度の系列を四半期平均にする。"""
    buckets: dict[str, list[float]] = {}
    for p in points:
        ql = _to_quarter_label(p.get("date", ""))
        if ql is None:
            continue
        v = p.get(value_key)
        if v is None:
            continue
        try:
            buckets.setdefault(ql, []).append(float(v))
        except (TypeError, ValueError):
            continue
    return {q: sum(vs) / len(vs) for q, vs in buckets.items() if vs}


async def _build_panel(method: str) -> tuple[list[str], np.ndarray]:
    """共通期間の四半期パネル（GDPギャップ/JGB10/USDJPY/CPIコアコア）を組み立てる。

    Returns
    -------
    quarters : list[str]  共通期間の四半期ラベル（昇順）
    Y        : np.ndarray (T, 4)  各列が VARIABLE_NAMES の順
    """
    gdp = await get_gdp_gap()
    rates = await get_rates()
    infl = await get_inflation()

    # GDPギャップ（method 別）
    if method == "cabinet_office":
        gdp_series = gdp.cabinet_office.data
    elif method == "average":
        gdp_series = gdp.estimated_average.data
    elif method == "civilian":
        gdp_series = gdp.estimated_civilian.data
    else:
        gdp_series = gdp.estimated_maximum.data
    gdp_q: dict[str, float] = {
        p.date: float(p.gdp_gap_percent)
        for p in gdp_series
        if _QUARTER_RE.match(p.date)
    }

    # JGB10y（月次想定 → 四半期平均）
    boj_dicts = [
        {"date": p.date, "jgb_10y_yield": p.jgb_10y_yield}
        for p in rates.interest_rates.boj
        if p.jgb_10y_yield is not None
    ]
    jgb_q = _aggregate_to_quarterly(boj_dicts, "jgb_10y_yield")

    # USD/JPY（FRED）
    fx_points = rates.exchange_rates.fred
    fx_dicts = [{"date": p.date, "usdjpy": p.usdjpy} for p in fx_points]
    fx_q = _aggregate_to_quarterly(fx_dicts, "usdjpy")

    # CPIコアコア（既に四半期想定）
    cpi_dicts = [
        {"date": p.date, "cpi_core_core": p.cpi_core_core}
        for p in infl.data
        if p.cpi_core_core is not None
    ]
    cpi_q = _aggregate_to_quarterly(cpi_dicts, "cpi_core_core")

    # 共通期間の抽出（4系列すべて存在する四半期のみ）
    common = sorted(
        set(gdp_q) & set(jgb_q) & set(fx_q) & set(cpi_q),
        key=lambda x: (int(x.split("-Q")[0]), int(x.split("-Q")[1])),
    )
    if len(common) < VAR_LAG_ORDER + 2:
        # 共通期間が短すぎる場合は欠損を最終観測値で埋めて延長
        all_q = sorted(
            set(gdp_q) | set(jgb_q) | set(fx_q) | set(cpi_q),
            key=lambda x: (int(x.split("-Q")[0]), int(x.split("-Q")[1])),
        )

        def _ffill(d: dict[str, float], qs: list[str]) -> dict[str, float]:
            out: dict[str, float] = {}
            last: float | None = None
            for q in qs:
                if q in d:
                    last = d[q]
                if last is not None:
                    out[q] = last
            return out

        # 後方フィルにも対応するため逆方向もパス
        def _bfill(d: dict[str, float], qs: list[str]) -> dict[str, float]:
            out: dict[str, float] = {}
            last: float | None = None
            for q in reversed(qs):
                if q in d:
                    last = d[q]
                if last is not None:
                    out[q] = last
            return out

        gdp_q2 = _ffill(gdp_q, all_q)
        jgb_q2 = _ffill(jgb_q, all_q)
        fx_q2 = _ffill(fx_q, all_q)
        cpi_q2 = _ffill(cpi_q, all_q)
        for d, src in (
            (gdp_q2, gdp_q),
            (jgb_q2, jgb_q),
            (fx_q2, fx_q),
            (cpi_q2, cpi_q),
        ):
            bf = _bfill(src, all_q)
            for q in all_q:
                if q not in d and q in bf:
                    d[q] = bf[q]
        common = [q for q in all_q if q in gdp_q2 and q in jgb_q2 and q in fx_q2 and q in cpi_q2]
        gdp_q, jgb_q, fx_q, cpi_q = gdp_q2, jgb_q2, fx_q2, cpi_q2

    if not common:
        raise ValueError("VAR: 共通期間のデータが取得できませんでした")

    Y = np.array(
        [
            [gdp_q[q], jgb_q[q], fx_q[q], cpi_q[q]]
            for q in common
        ],
        dtype=float,
    )
    return common, Y


# ---------------------------------------------------------------------------
# OLS-VAR 推定
# ---------------------------------------------------------------------------


def _fit_var(Y: np.ndarray, p: int) -> tuple[np.ndarray, np.ndarray]:
    """VAR(p) を OLS で推定。

    モデル: Y_t = c + A_1 Y_{t-1} + ... + A_p Y_{t-p} + e_t

    Returns
    -------
    c : (k,)              切片ベクトル
    A : (p, k, k)         ラグ係数（A[i] = A_{i+1}）
    """
    T, k = Y.shape
    if T <= p + 1:
        # 推定不可 → 直近観測の単位行列モデルにフォールバック
        return Y[-1], np.zeros((p, k, k))

    n = T - p
    # 説明変数行列 X: (n, k*p + 1)
    X = np.ones((n, k * p + 1))
    for i in range(p):
        X[:, 1 + i * k : 1 + (i + 1) * k] = Y[p - 1 - i : T - 1 - i]
    Yt = Y[p:]  # (n, k)

    # OLS (各方程式独立 = 同一 X なので行列で一括)
    # B = (X'X)^-1 X' Yt   shape (k*p+1, k)
    XtX = X.T @ X
    try:
        # ridge 微小項（数値安定化）
        reg = 1e-8 * np.eye(XtX.shape[0])
        B = np.linalg.solve(XtX + reg, X.T @ Yt)
    except np.linalg.LinAlgError:
        B = np.linalg.lstsq(X, Yt, rcond=None)[0]

    c = B[0]  # (k,)
    A = np.zeros((p, k, k))
    for i in range(p):
        # B[1+i*k : 1+(i+1)*k] は (k, k); 行が説明変数, 列が被説明変数
        # Y_t = c + sum_i A_{i+1} Y_{t-1-i}; 我々は Y_{t-1-i} の係数として使うので転置
        A[i] = B[1 + i * k : 1 + (i + 1) * k].T

    # 安定化: コンパニオン行列の最大固有値が >= 0.95 なら全係数を縮小して
    # 予測の暴発を防ぐ（小サンプルでは過学習で容易に非定常になる）。
    A, c = _stabilize(A, c, Y)
    return c, A


def _stabilize(
    A: np.ndarray, c: np.ndarray, Y: np.ndarray, max_eig: float = 0.85
) -> tuple[np.ndarray, np.ndarray]:
    """コンパニオン行列の固有値が上限を超える場合に係数を縮小。

    係数行列を一様に s 倍すると、定数項も平均に向かって調整する必要があるため
    `c <- c + (1-s) * A_full * mean(Y)` と等価な処理を適用して長期均衡を保つ。
    """
    p, k, _ = A.shape
    # コンパニオン行列 (kp x kp)
    comp = np.zeros((k * p, k * p))
    for i in range(p):
        comp[:k, i * k : (i + 1) * k] = A[i]
    if p > 1:
        comp[k:, : k * (p - 1)] = np.eye(k * (p - 1))
    try:
        eigs = np.linalg.eigvals(comp)
        max_abs = float(np.max(np.abs(eigs))) if eigs.size else 0.0
    except np.linalg.LinAlgError:
        max_abs = 0.0
    if max_abs <= max_eig or max_abs == 0.0:
        return A, c
    s = max_eig / max_abs
    A_s = A * s
    # 長期均衡を保つため定数項も補正: y* = c / (I - sum A_i)
    sum_A = sum(A[i] for i in range(p))
    sum_A_s = sum(A_s[i] for i in range(p))
    try:
        y_star = np.linalg.solve(np.eye(k) - sum_A, c)
        c_s = (np.eye(k) - sum_A_s) @ y_star
    except np.linalg.LinAlgError:
        # フォールバック: データ平均
        mean_y = Y.mean(axis=0)
        c_s = (np.eye(k) - sum_A_s) @ mean_y
    return A_s, c_s


def _forecast_var(
    Y: np.ndarray, c: np.ndarray, A: np.ndarray, n_steps: int
) -> np.ndarray:
    """確定的予測（ショックなし）。

    Returns
    -------
    fc : (n_steps, k)
    """
    p, k, _ = A.shape
    history = list(Y[-p:])  # 直近 p 期間
    out = []
    for _ in range(n_steps):
        y_next = c.copy()
        for i in range(p):
            y_next = y_next + A[i] @ history[-(i + 1)]
        out.append(y_next)
        history.append(y_next)
    return np.array(out)


def _compute_irf(
    A: np.ndarray, n_horizon: int, shock: np.ndarray
) -> np.ndarray:
    """直交化していないシンプルなインパルス応答。

    時刻 0 にショックベクトル `shock` (k,) が GDPギャップ等に与えられたとき、
    ホライズン h までの応答を計算する（IS なしの自由応答）。

    Returns
    -------
    irf : (n_horizon+1, k)
    """
    p, k, _ = A.shape
    history = [np.zeros(k) for _ in range(p)]
    history[-1] = shock.copy()
    irf = [shock.copy()]
    for _ in range(n_horizon):
        y_next = np.zeros(k)
        for i in range(p):
            y_next = y_next + A[i] @ history[-(i + 1)]
        irf.append(y_next)
        history.append(y_next)
    return np.array(irf)


# ---------------------------------------------------------------------------
# 予測クォーター生成
# ---------------------------------------------------------------------------


def _next_quarter(qlabel: str) -> str:
    y, q = qlabel.split("-Q")
    y, q = int(y), int(q)
    q += 1
    if q > 4:
        q = 1
        y += 1
    return f"{y}-Q{q}"


def _build_future_quarters(last_q: str, n: int) -> list[str]:
    out = []
    cur = last_q
    for _ in range(n):
        cur = _next_quarter(cur)
        out.append(cur)
    return out


# ---------------------------------------------------------------------------
# Public API: VAR 予測
# ---------------------------------------------------------------------------


DEFAULT_GAP_FILL_PERCENT = 100.0


def _build_spending_note(amount: float, gap_fill_percent: float) -> str:
    if amount > 0:
        return f"GDPギャップの{gap_fill_percent:.0f}%充足: 拡張的財政支出 {amount:+.1f}兆円/年"
    if amount < 0:
        return f"GDPギャップの{gap_fill_percent:.0f}%充足: 財政引き締め {amount:+.1f}兆円/年"
    return "財政中立（インパクトなし）"


async def get_var_prediction(
    method: str = "maximum",
    gap_fill_percent: float | None = None,
) -> PredictionResponse:
    """VAR(4) による統計的予測。

    財政支出シナリオは GDPギャップショックとして VAR に与え、その応答を
    ベースライン予測に重畳する形で簡略実装する（VARX ではなく shock-augmented VAR）。
    gap_fill_percent: GDPギャップの何%を埋める財政政策か (0-150%)
    """
    if method not in VALID_METHODS:
        method = "maximum"

    effective_gap_fill = gap_fill_percent if gap_fill_percent is not None else DEFAULT_GAP_FILL_PERCENT

    quarters, Y = await _build_panel(method)
    T, k = Y.shape

    # 推定
    # サンプルサイズに対するラグ次数の上限。各方程式の自由度を考慮し、
    # 1 説明変数あたり概ね 8 観測以上を確保（k*p + 1 説明変数, 過学習回避）。
    max_p_by_dof = max(1, (T - 8) // (k * 2))
    p = max(1, min(VAR_LAG_ORDER, max_p_by_dof))
    c, A = _fit_var(Y, p)

    # ベースライン予測
    fc = _forecast_var(Y, c, A, PREDICTION_STEPS)

    # 直近観測値（GDPギャップ %, JGB %, USDJPY, CPI %）
    last_obs = Y[-1]
    gap_pct = float(last_obs[0])
    nominal_gdp = _get_nominal_gdp()
    gap_trillion = round(gap_pct / 100.0 * nominal_gdp, 1)

    # Compute annual spending from gap fill percentage
    annual_spending = -gap_trillion / FISCAL_MULTIPLIER * effective_gap_fill / 100

    # 財政ショック → GDPギャップショック（兆円 → ％ポイント）。
    # +1兆円の財政拡張 ≈ 乗数1で +(1/nominal_gdp)*100 のギャップ拡大。
    shock_gap_pct = annual_spending / nominal_gdp * 100.0 * FISCAL_MULTIPLIER
    shock_vec = np.zeros(k)
    shock_vec[0] = shock_gap_pct
    shock_response = _compute_irf(A, PREDICTION_STEPS - 1, shock_vec)
    # ショック応答をベースラインに重畳
    fc_with_shock = fc + shock_response

    # 予測四半期
    future_q = _build_future_quarters(quarters[-1], PREDICTION_STEPS)
    # 直近実績点を先頭に挿入（IS-LM と同様 actual ＋ predictions）
    rate_predictions = [
        InterestRatePrediction(
            date=quarters[-1],
            predicted_jgb_10y=round(float(last_obs[1]), 2),
            type="actual",
        )
    ] + [
        InterestRatePrediction(
            date=future_q[i],
            predicted_jgb_10y=round(float(fc_with_shock[i, 1]), 2),
            type="prediction",
        )
        for i in range(PREDICTION_STEPS)
    ]
    fx_predictions = [
        ExchangeRatePrediction(
            date=quarters[-1],
            predicted_usdjpy=round(float(last_obs[2]), 1),
            type="actual",
        )
    ] + [
        ExchangeRatePrediction(
            date=future_q[i],
            predicted_usdjpy=round(float(fc_with_shock[i, 2]), 1),
            type="prediction",
        )
        for i in range(PREDICTION_STEPS)
    ]

    # GDP impact: difference between shocked and baseline GDP gap forecasts
    gdp_impact_predictions = [
        GdpImpactPoint(
            date=quarters[-1],
            predicted_gdp_change_percent=0.0,
            type="actual",
        )
    ] + [
        GdpImpactPoint(
            date=future_q[i],
            predicted_gdp_change_percent=round(
                float(fc_with_shock[i, 0] - fc[i, 0]), 4
            ),
            type="prediction",
        )
        for i in range(PREDICTION_STEPS)
    ]

    # Inflation prediction: extract CPI core-core from shocked forecast
    inflation_predictions = [
        InflationPredictionPoint(
            date=quarters[-1],
            predicted_inflation_percent=round(float(last_obs[3]), 2),
            type="actual",
        )
    ] + [
        InflationPredictionPoint(
            date=future_q[i],
            predicted_inflation_percent=round(float(fc_with_shock[i, 3]), 2),
            type="prediction",
        )
        for i in range(PREDICTION_STEPS)
    ]

    # IRF（+1兆円の財政拡張ショック → 各変数）
    unit_shock = np.zeros(k)
    unit_shock[0] = 1.0 / nominal_gdp * 100.0  # +1兆円相当のGDPギャップショック
    irf_arr = _compute_irf(A, PREDICTION_STEPS, unit_shock)
    irf_points = [
        IrfPoint(
            horizon=h,
            gdp_gap=round(float(irf_arr[h, 0]), 4),
            jgb_10y=round(float(irf_arr[h, 1]), 4),
            usdjpy=round(float(irf_arr[h, 2]), 3),
            cpi_core_core=round(float(irf_arr[h, 3]), 4),
        )
        for h in range(PREDICTION_STEPS + 1)
    ]

    return PredictionResponse(
        current_gap=CurrentGap(
            gdp_gap_percent=round(gap_pct, 2),
            gdp_gap_trillion_yen=gap_trillion,
        ),
        required_fiscal_spending=RequiredFiscalSpending(
            amount_trillion_yen=round(annual_spending, 1),
            multiplier=FISCAL_MULTIPLIER,
            note=_build_spending_note(annual_spending, effective_gap_fill),
            gap_fill_percent=effective_gap_fill,
        ),
        impact_prediction=ImpactPrediction(
            interest_rate=rate_predictions,
            exchange_rate=fx_predictions,
            gdp_impact=gdp_impact_predictions,
            inflation_prediction=inflation_predictions,
            model=f"VAR({p})",
            engine="var",
            assumptions=Assumptions(
                lag_order=p,
                n_obs=T,
                n_steps=PREDICTION_STEPS,
                variables=VARIABLE_NAMES,
                fiscal_multiplier=FISCAL_MULTIPLIER,
            ),
            irf=irf_points,
        ),
    )


# ---------------------------------------------------------------------------
# Public API: AR(1) ベースライン
# ---------------------------------------------------------------------------


def _fit_ar1(y: np.ndarray) -> tuple[float, float]:
    """y_t = c + phi * y_{t-1} + e_t  を OLS 推定。

    安定化:
      - |phi| が 0.95 を超える場合は 0.95 にクランプ
      - クランプ時はデータ平均を不変にする c に再設定
    """
    n = len(y)
    if n < 3:
        return float(y[-1]) if n else 0.0, 0.0
    y_lag = y[:-1]
    y_now = y[1:]
    X = np.column_stack([np.ones_like(y_lag), y_lag])
    try:
        beta, *_ = np.linalg.lstsq(X, y_now, rcond=None)
        c, phi = float(beta[0]), float(beta[1])
    except np.linalg.LinAlgError:
        c, phi = float(y[-1]), 0.0
    if not np.isfinite(phi):
        phi = 0.0
    if abs(phi) >= 0.95:
        phi = 0.95 * (1.0 if phi > 0 else -1.0)
    # 不偏平均がデータ平均と一致するよう c を再設定（AR(1) の long-run mean = c/(1-phi)）
    mean_y = float(np.mean(y))
    c = (1.0 - phi) * mean_y
    return c, phi


def _forecast_ar1(y0: float, c: float, phi: float, n_steps: int) -> list[float]:
    out = []
    cur = y0
    for _ in range(n_steps):
        cur = c + phi * cur
        out.append(cur)
    return out


async def get_ar1_prediction(
    method: str = "maximum",
    gap_fill_percent: float | None = None,
) -> PredictionResponse:
    """AR(1) ベースライン: 各変数を独立に AR(1) で予測。

    ベンチマーク用途のため、財政支出シナリオは GDPギャップ初期値の調整のみで
    反映する（金利・為替への波及は AR(1) 自身の伝播ではなく、単純な GDP ギャップ
    スプリット効果として表現）。
    gap_fill_percent: GDPギャップの何%を埋める財政政策か (0-150%)
    """
    if method not in VALID_METHODS:
        method = "maximum"

    effective_gap_fill = gap_fill_percent if gap_fill_percent is not None else DEFAULT_GAP_FILL_PERCENT

    quarters, Y = await _build_panel(method)
    T, k = Y.shape

    nominal_gdp = _get_nominal_gdp()
    last_obs = Y[-1].copy()
    gap_pct = float(last_obs[0])
    gap_trillion = round(gap_pct / 100.0 * nominal_gdp, 1)

    # Compute annual spending from gap fill percentage
    annual_spending = -gap_trillion / FISCAL_MULTIPLIER * effective_gap_fill / 100

    # ショック反映: GDPギャップを直接シフト（同時期に乗数効果が及ぶと仮定）
    shock_gap_pct = annual_spending / nominal_gdp * 100.0 * FISCAL_MULTIPLIER
    last_shocked = last_obs.copy()
    last_shocked[0] = last_obs[0] + shock_gap_pct

    # 各変数を AR(1) で個別推定・予測
    # Baseline (no shock) forecast for GDP gap comparison
    fc_baseline = np.zeros((PREDICTION_STEPS, k))
    for j in range(k):
        c, phi = _fit_ar1(Y[:, j])
        fc_baseline[:, j] = _forecast_ar1(float(last_obs[j]), c, phi, PREDICTION_STEPS)

    # Shocked forecast
    fc = np.zeros((PREDICTION_STEPS, k))
    for j in range(k):
        c, phi = _fit_ar1(Y[:, j])
        fc[:, j] = _forecast_ar1(float(last_shocked[j]), c, phi, PREDICTION_STEPS)

    future_q = _build_future_quarters(quarters[-1], PREDICTION_STEPS)
    rate_predictions = [
        InterestRatePrediction(
            date=quarters[-1],
            predicted_jgb_10y=round(float(last_obs[1]), 2),
            type="actual",
        )
    ] + [
        InterestRatePrediction(
            date=future_q[i],
            predicted_jgb_10y=round(float(fc[i, 1]), 2),
            type="prediction",
        )
        for i in range(PREDICTION_STEPS)
    ]
    fx_predictions = [
        ExchangeRatePrediction(
            date=quarters[-1],
            predicted_usdjpy=round(float(last_obs[2]), 1),
            type="actual",
        )
    ] + [
        ExchangeRatePrediction(
            date=future_q[i],
            predicted_usdjpy=round(float(fc[i, 2]), 1),
            type="prediction",
        )
        for i in range(PREDICTION_STEPS)
    ]

    # GDP impact: difference between shocked and baseline GDP gap forecasts
    gdp_impact_predictions = [
        GdpImpactPoint(
            date=quarters[-1],
            predicted_gdp_change_percent=0.0,
            type="actual",
        )
    ] + [
        GdpImpactPoint(
            date=future_q[i],
            predicted_gdp_change_percent=round(
                float(fc[i, 0] - fc_baseline[i, 0]), 4
            ),
            type="prediction",
        )
        for i in range(PREDICTION_STEPS)
    ]

    # Inflation prediction: CPI core-core from shocked forecast
    inflation_predictions = [
        InflationPredictionPoint(
            date=quarters[-1],
            predicted_inflation_percent=round(float(last_obs[3]), 2),
            type="actual",
        )
    ] + [
        InflationPredictionPoint(
            date=future_q[i],
            predicted_inflation_percent=round(float(fc[i, 3]), 2),
            type="prediction",
        )
        for i in range(PREDICTION_STEPS)
    ]

    return PredictionResponse(
        current_gap=CurrentGap(
            gdp_gap_percent=round(gap_pct, 2),
            gdp_gap_trillion_yen=gap_trillion,
        ),
        required_fiscal_spending=RequiredFiscalSpending(
            amount_trillion_yen=round(annual_spending, 1),
            multiplier=FISCAL_MULTIPLIER,
            note=_build_spending_note(annual_spending, effective_gap_fill),
            gap_fill_percent=effective_gap_fill,
        ),
        impact_prediction=ImpactPrediction(
            interest_rate=rate_predictions,
            exchange_rate=fx_predictions,
            gdp_impact=gdp_impact_predictions,
            inflation_prediction=inflation_predictions,
            model="AR(1)",
            engine="ar1",
            assumptions=Assumptions(
                lag_order=1,
                n_obs=T,
                n_steps=PREDICTION_STEPS,
                variables=VARIABLE_NAMES,
                fiscal_multiplier=FISCAL_MULTIPLIER,
            ),
        ),
    )
