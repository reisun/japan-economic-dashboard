import { useEffect, useRef, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { STATIC_MODE, useApi } from "../hooks/useApi";
import type {
  GdpGapMethod,
  GdpImpactPoint,
  InflationPredictionPoint,
  PredictionEngine,
  PredictionResponse,
} from "../types/api";

interface RateChartPoint {
  date: string;
  actual: number | null;
  prediction: number | null;
}

interface FxChartPoint {
  date: string;
  actual: number | null;
  prediction: number | null;
}

interface GdpChartPoint {
  date: string;
  actual: number | null;
  prediction: number | null;
}

interface InflationChartPoint {
  date: string;
  actual: number | null;
  prediction: number | null;
}

const METHOD_LABEL: Record<GdpGapMethod, string> = {
  cabinet_office: "内閣府公表",
  average: "平均概念",
  maximum: "最大概念",
  civilian: "在野試算",
};

const ENGINE_LABEL: Record<PredictionEngine, string> = {
  is_lm: "IS-LM（構造モデル）",
  var: "VAR（統計モデル）",
  bvar: "BVAR（ベイズVAR）",
  ar1: "AR(1)（ベンチマーク）",
  rw: "RW（ランダムウォーク）",
};

const ENGINE_DESCRIPTION: Record<PredictionEngine, string> = {
  is_lm: "マクロ経済理論に基づく構造モデル。財政乗数・流動性選好・UIPの理論式から金利・為替への波及を計算します。",
  var: "Vector Autoregression: 過去データから多変量の動学を推定する統計モデル。実データに観察された関係性を反映します。",
  bvar: "Bayesian VAR: Minnesota prior による正則化を加えた VAR。小サンプルでの過学習を抑制し、安定した予測を提供します。",
  ar1: "AR(1): 各変数を前期値だけで個別に予測するベンチマーク。最も単純なため、他モデルの精度比較の基準になります。",
  rw: "Random Walk with Drift: 各変数を前期値+ドリフトで予測する最も単純なモデル。「明日は今日と同じ」仮説のベンチマーク。",
};

const DEBOUNCE_MS = 500;

// GDPギャップ充足率の範囲
const GAP_FILL_MIN = 0;
const GAP_FILL_MAX = 150;
const GAP_FILL_STEP = 5;
const GAP_FILL_DEFAULT = 100;

// UIP感応度の範囲
const UIP_MIN = 0;
const UIP_MAX = 10;
const UIP_STEP = 0.5;
const UIP_DEFAULT = 2.0;

function buildPredictionPath(
  method: GdpGapMethod,
  gapFill: number,
  engine: PredictionEngine,
  uipSensitivity: number | null = null,
): string {
  if (STATIC_MODE) {
    // 静的モード: prediction-<method>-<engine>.json を返す（IS-LM は後方互換のため
    // engine 指定なしのファイル名にもフォールバック）
    if (engine === "is_lm") {
      return `/prediction-${method}.json`;
    }
    return `/prediction-${method}-${engine}.json`;
  }
  const params = new URLSearchParams();
  params.set("method", method);
  params.set("engine", engine);
  params.append(`gap_fill_percent`, String(gapFill));
  if (uipSensitivity !== null && !Number.isNaN(uipSensitivity)) {
    params.set("uip_sensitivity", String(uipSensitivity));
  }
  return `/prediction?${params.toString()}`;
}

function splitRateData(data: PredictionResponse): RateChartPoint[] {
  return data.impact_prediction.interest_rate.map((point) => ({
    date: point.date,
    actual: point.type === "actual" ? point.predicted_jgb_10y : null,
    prediction: point.type === "prediction" ? point.predicted_jgb_10y : null,
  }));
}

function splitFxData(data: PredictionResponse): FxChartPoint[] {
  return data.impact_prediction.exchange_rate.map((point) => ({
    date: point.date,
    actual: point.type === "actual" ? point.predicted_usdjpy : null,
    prediction: point.type === "prediction" ? point.predicted_usdjpy : null,
  }));
}

function splitGdpData(data: PredictionResponse): GdpChartPoint[] {
  return data.impact_prediction.gdp_impact.map((point: GdpImpactPoint) => ({
    date: point.date,
    actual: point.type === "actual" ? point.predicted_gdp_change_percent : null,
    prediction: point.type === "prediction" ? point.predicted_gdp_change_percent : null,
  }));
}

function splitInflationData(data: PredictionResponse): InflationChartPoint[] {
  return data.impact_prediction.inflation_prediction.map((point: InflationPredictionPoint) => ({
    date: point.date,
    actual: point.type === "actual" ? point.predicted_inflation_percent : null,
    prediction: point.type === "prediction" ? point.predicted_inflation_percent : null,
  }));
}

export function PredictionChart() {
  const [method, setMethod] = useState<GdpGapMethod>("maximum");
  const [engine, setEngine] = useState<PredictionEngine>("is_lm");

  // GDPギャップ充足率
  const [gapFillPercent, setGapFillPercent] = useState(GAP_FILL_DEFAULT);
  const [debouncedGapFill, setDebouncedGapFill] = useState(GAP_FILL_DEFAULT);

  // UIP感応度（null=デフォルト値を使用）
  const [uipInput, setUipInput] = useState<number | null>(null);
  const [debouncedUip, setDebouncedUip] = useState<number | null>(null);

  // debounce: gapFillPercent → debouncedGapFill
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }
    debounceRef.current = setTimeout(() => {
      setDebouncedGapFill(gapFillPercent);
    }, DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [gapFillPercent]);

  // debounce: uipInput → debouncedUip
  const uipDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (uipDebounceRef.current) {
      clearTimeout(uipDebounceRef.current);
    }
    uipDebounceRef.current = setTimeout(() => {
      setDebouncedUip(uipInput);
    }, DEBOUNCE_MS);
    return () => {
      if (uipDebounceRef.current) clearTimeout(uipDebounceRef.current);
    };
  }, [uipInput]);

  // method / engine 切替時はパラメータをデフォルトに戻す
  useEffect(() => {
    setGapFillPercent(GAP_FILL_DEFAULT);
    setDebouncedGapFill(GAP_FILL_DEFAULT);
    setUipInput(null);
    setDebouncedUip(null);
  }, [method, engine]);

  const path = buildPredictionPath(method, debouncedGapFill, engine, debouncedUip);
  const { data, loading, error } = useApi<PredictionResponse>(path);

  const tabs: { key: GdpGapMethod; label: string }[] = [
    { key: "cabinet_office", label: METHOD_LABEL.cabinet_office },
    { key: "average", label: METHOD_LABEL.average },
    { key: "maximum", label: METHOD_LABEL.maximum },
    { key: "civilian", label: METHOD_LABEL.civilian },
  ];

  const renderTabs = () => (
    <div className="flex gap-1 mb-3 border-b border-gray-200">
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => setMethod(t.key)}
          className={
            "px-3 py-1.5 text-xs font-medium border-b-2 -mb-px transition-colors " +
            (method === t.key
              ? "border-blue-600 text-blue-700"
              : "border-transparent text-gray-500 hover:text-gray-800")
          }
        >
          {t.label}
        </button>
      ))}
    </div>
  );

  const engineOptions: { key: PredictionEngine; label: string }[] = [
    { key: "is_lm", label: ENGINE_LABEL.is_lm },
    { key: "var", label: ENGINE_LABEL.var },
    { key: "bvar", label: ENGINE_LABEL.bvar },
    { key: "ar1", label: ENGINE_LABEL.ar1 },
    { key: "rw", label: ENGINE_LABEL.rw },
  ];

  const renderEngineSelector = () => (
    <div className="bg-indigo-50 border border-indigo-200 rounded p-3 mb-3">
      <div className="flex items-baseline justify-between mb-2 gap-2 flex-wrap">
        <h3 className="text-sm font-medium text-indigo-900">予測モデル</h3>
        <span className="text-xs text-indigo-700">
          {data?.impact_prediction.model
            ? `現在: ${data.impact_prediction.model}`
            : ""}
        </span>
      </div>
      <div className="flex flex-wrap gap-2 mb-2">
        {engineOptions.map((o) => (
          <button
            key={o.key}
            onClick={() => setEngine(o.key)}
            className={
              "px-3 py-1 text-xs font-medium rounded border transition-colors " +
              (engine === o.key
                ? "border-indigo-600 bg-indigo-600 text-white"
                : "border-indigo-300 bg-white text-indigo-800 hover:bg-indigo-100")
            }
          >
            {o.label}
          </button>
        ))}
      </div>
      <p className="text-xs text-indigo-800/80">
        {ENGINE_DESCRIPTION[engine]}
      </p>
      <p className="text-xs text-indigo-700/70 mt-1">
        IS-LM はマクロ経済理論に基づく構造モデル。VAR は過去データから推定した統計モデル。
        両者の差異が経済予測の不確実性を示します。
      </p>
    </div>
  );

  const renderGapFillPanel = () => {
    const disabled = STATIC_MODE;
    return (
      <div className="bg-gray-50 border border-gray-200 rounded p-3 mb-4">
        <div className="flex items-baseline justify-between mb-2 gap-2 flex-wrap">
          <h3 className="text-sm font-medium text-gray-800">
            GDPギャップ充足率
          </h3>
          <span className="text-sm font-bold text-gray-800">
            {gapFillPercent}%
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500">{GAP_FILL_MIN}%</span>
          <input
            type="range"
            step={GAP_FILL_STEP}
            min={GAP_FILL_MIN}
            max={GAP_FILL_MAX}
            value={gapFillPercent}
            onChange={(e) => setGapFillPercent(Number(e.target.value))}
            disabled={disabled}
            className="flex-1 min-w-[140px] disabled:opacity-50"
            aria-label="GDPギャップ充足率スライダー"
          />
          <span className="text-xs text-gray-500">{GAP_FILL_MAX}%</span>
        </div>
        <div className="flex gap-4 mt-1 text-xs text-gray-400">
          <span>50%</span>
          <span>100%</span>
          <span>150%</span>
        </div>
        {disabled && (
          <p className="text-xs text-gray-400 mt-2">
            ※ 静的モードでは充足率の変更は利用できません
          </p>
        )}
      </div>
    );
  };

  const handleUipChange = (value: number) => {
    const clamped = Math.max(UIP_MIN, Math.min(UIP_MAX, value));
    setUipInput(clamped);
  };

  const handleUipReset = () => {
    setUipInput(null);
    setDebouncedUip(null);
  };

  const renderUipPanel = () => {
    if (engine !== "is_lm") return null;
    const disabled = STATIC_MODE;
    const displayUip = uipInput ?? UIP_DEFAULT;
    return (
      <div className="bg-gray-50 border border-gray-200 rounded p-3 mb-4">
        <div className="flex items-baseline justify-between mb-2 gap-2 flex-wrap">
          <h3 className="text-sm font-medium text-gray-800">
            UIP感応度（円/pp）
          </h3>
          <span className="text-xs text-gray-500" title="JGB金利 1%p上昇あたりの円高幅（円）">
            JGB金利 1%p上昇あたりの円高幅
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="number"
            step={UIP_STEP}
            min={UIP_MIN}
            max={UIP_MAX}
            value={uipInput !== null ? uipInput : ""}
            placeholder={`${UIP_DEFAULT} (デフォルト)`}
            onChange={(e) => {
              const v = Number(e.target.value);
              if (!Number.isNaN(v)) handleUipChange(v);
            }}
            disabled={disabled}
            className="w-24 px-2 py-1 text-sm border border-gray-300 rounded disabled:bg-gray-100 disabled:text-gray-400"
            aria-label="UIP感応度"
          />
          <span className="text-xs text-gray-500">円/pp</span>
          <input
            type="range"
            step={UIP_STEP}
            min={UIP_MIN}
            max={UIP_MAX}
            value={displayUip}
            onChange={(e) => handleUipChange(Number(e.target.value))}
            disabled={disabled}
            className="flex-1 min-w-[140px] disabled:opacity-50"
            aria-label="UIP感応度スライダー"
          />
          <button
            type="button"
            onClick={handleUipReset}
            disabled={disabled || uipInput === null}
            className="px-3 py-1 text-xs font-medium border border-gray-300 rounded bg-white hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            デフォルト
          </button>
        </div>
      </div>
    );
  };

  if (loading && !data) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold mb-4">予測モデル</h2>
        {renderEngineSelector()}
        {renderTabs()}
        <div className="h-64 flex items-center justify-center text-gray-400">
          読み込み中...
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold mb-4">予測モデル</h2>
        {renderEngineSelector()}
        {renderTabs()}
        <div className="h-64 flex items-center justify-center text-red-500">
          {error || "データの取得に失敗しました"}
        </div>
      </div>
    );
  }

  const rateData = splitRateData(data);
  const fxData = splitFxData(data);
  const gdpData = splitGdpData(data);
  const inflationData = splitInflationData(data);

  // Y軸ドメインをスライダー全範囲（0-150%）に基づいて固定し、
  // スライダー操作時のオートスケールによる視覚的変化の消失を防ぐ。
  const gapAbs = Math.abs(data.current_gap.gdp_gap_percent);
  const assumptions = data.impact_prediction.assumptions;
  const baselineJgb = assumptions.baseline_jgb_10y ?? 2.0;
  const baselineFx = assumptions.baseline_usdjpy ?? 150;
  const baselineInflation = assumptions.baseline_inflation ?? 2.0;

  // GDP影響パス: 150%充足時の最大インパクトを基準に余裕を持たせる
  const gdpMaxImpact = Math.max(gapAbs * 2, 1);
  const gdpDomain: [number, number] = [-0.5, Math.ceil(gdpMaxImpact)];

  // インフレ率: ベースライン周辺に絞り、変化を視認しやすくする
  const maxInflImpact = 0.3 * gdpMaxImpact;  // Phillips curve slope × GDP max impact
  const inflDomain: [number, number] = [
    Math.floor(baselineInflation - maxInflImpact - 0.5),
    Math.ceil(baselineInflation + maxInflImpact + 0.5),
  ];

  // 金利: 0 から ベースライン + 想定最大上昇幅
  const rateDomain: [number, number] = [0, Math.ceil(baselineJgb + gapAbs + 1)];

  // 為替: ベースライン ± 想定最大変動幅
  const fxSwing = Math.max(gapAbs * 3, 10);
  const fxDomain: [number, number] = [
    Math.floor(baselineFx - fxSwing),
    Math.ceil(baselineFx + fxSwing / 2),
  ];

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h2 className="text-lg font-semibold mb-1">予測モデル</h2>
      <p className="text-xs text-gray-500 mb-3">
        ギャップ起点: {METHOD_LABEL[method]} / モデル:{" "}
        {data.impact_prediction.model}
        {data.impact_prediction.assumptions.fiscal_multiplier != null && (
          <> / 乗数: {data.impact_prediction.assumptions.fiscal_multiplier}</>
        )}
        {data.impact_prediction.assumptions.lag_order != null && (
          <>
            {" "}
            / ラグ: {data.impact_prediction.assumptions.lag_order} / 観測数:{" "}
            {data.impact_prediction.assumptions.n_obs ?? "-"}
          </>
        )}
      </p>
      {renderEngineSelector()}
      {renderTabs()}

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div className="bg-blue-50 rounded p-3">
          <p className="text-xs text-gray-600">現在のGDPギャップ</p>
          <p className="text-lg font-bold text-blue-900">
            {data.current_gap.gdp_gap_percent}%
          </p>
          <p className="text-xs text-gray-500">
            ({data.current_gap.gdp_gap_trillion_yen}兆円)
          </p>
        </div>
        <div className="rounded p-3 bg-green-50">
          <p className="text-xs text-gray-600">
            GDPギャップ充足率: {data.required_fiscal_spending.gap_fill_percent}%
          </p>
          <p className="text-lg font-bold text-green-900">
            年間財政支出: {data.required_fiscal_spending.amount_trillion_yen}兆円
          </p>
          <p className="text-xs text-gray-500">
            {data.required_fiscal_spending.note}
          </p>
        </div>
      </div>

      {renderGapFillPanel()}
      {renderUipPanel()}

      {loading && (
        <p className="text-xs text-gray-400 mb-2">更新中...</p>
      )}

      <div className="mb-4">
        <h3 className="text-sm font-medium text-gray-700 mb-2">
          GDP影響パス（ベースライン比）
        </h3>
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={gdpData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} domain={gdpDomain} tickFormatter={(v: number) => `${v}%`} />
            <Tooltip formatter={(value: number) => [`${value.toFixed(4)}%`]} />
            <Legend />
            <ReferenceLine y={0} stroke="#9ca3af" strokeDasharray="3 3" />
            <Line
              type="monotone"
              dataKey="actual"
              name="実績"
              stroke="#059669"
              strokeWidth={2}
              dot={{ r: 4 }}
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="prediction"
              name="予測"
              stroke="#059669"
              strokeWidth={2}
              strokeDasharray="5 5"
              dot={{ r: 4 }}
              connectNulls
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="mb-4">
        <h3 className="text-sm font-medium text-gray-700 mb-2">
          インフレ率予測（フィリップス曲線）
        </h3>
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={inflationData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} domain={inflDomain} tickFormatter={(v: number) => `${v}%`} />
            <Tooltip formatter={(value: number) => [`${value.toFixed(2)}%`]} />
            <Legend />
            <ReferenceLine y={2} stroke="#dc2626" strokeDasharray="3 3" label={{ value: "BOJ目標 2%", position: "right", fontSize: 10, fill: "#dc2626" }} />
            <Line
              type="monotone"
              dataKey="actual"
              name="実績"
              stroke="#7c3aed"
              strokeWidth={2}
              dot={{ r: 4 }}
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="prediction"
              name="予測"
              stroke="#7c3aed"
              strokeWidth={2}
              strokeDasharray="5 5"
              dot={{ r: 4 }}
              connectNulls
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="mb-4">
        <h3 className="text-sm font-medium text-gray-700 mb-2">
          金利予測（JGB 10年）
        </h3>
        {data.impact_prediction.assumptions.zlb_binding && (
          <p className="text-xs text-amber-600 mb-1">
            ※ ゼロ金利制約により金利下限 0% で切断
          </p>
        )}
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={rateData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} domain={rateDomain} tickFormatter={(v: number) => `${v}%`} />
            <Tooltip formatter={(value: number) => [`${value.toFixed(2)}%`]} />
            <Legend />
            <Line
              type="monotone"
              dataKey="actual"
              name="実績"
              stroke="#2563eb"
              strokeWidth={2}
              dot={{ r: 4 }}
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="prediction"
              name="予測"
              stroke="#2563eb"
              strokeWidth={2}
              strokeDasharray="5 5"
              dot={{ r: 4 }}
              connectNulls
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="mb-4">
        <h3 className="text-sm font-medium text-gray-700 mb-2">
          為替予測（USD/JPY）
        </h3>
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={fxData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} domain={fxDomain} />
            <Tooltip formatter={(value: number) => [`${value.toFixed(1)}円`]} />
            <Legend />
            <Line
              type="monotone"
              dataKey="actual"
              name="実績"
              stroke="#d97706"
              strokeWidth={2}
              dot={{ r: 4 }}
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="prediction"
              name="予測"
              stroke="#d97706"
              strokeWidth={2}
              strokeDasharray="5 5"
              dot={{ r: 4 }}
              connectNulls
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* モデル仮定（collapsible） */}
      <details className="mt-4 text-xs">
        <summary className="cursor-pointer text-gray-500 hover:text-gray-700 select-none">
          モデル仮定
        </summary>
        <div className="mt-2 bg-gray-50 border border-gray-200 rounded p-3 space-y-1 text-gray-600">
          {data.impact_prediction.assumptions.fiscal_multiplier != null && (
            <div>財政乗数: {data.impact_prediction.assumptions.fiscal_multiplier}</div>
          )}
          {data.impact_prediction.assumptions.money_demand_elasticity != null && (
            <div>貨幣需要の利子弾力性: {data.impact_prediction.assumptions.money_demand_elasticity}</div>
          )}
          {data.impact_prediction.assumptions.investment_sensitivity != null && (
            <div>投資の利子感応度: {data.impact_prediction.assumptions.investment_sensitivity}</div>
          )}
          {data.impact_prediction.assumptions.uip_sensitivity != null && (
            <div>UIP感応度: {data.impact_prediction.assumptions.uip_sensitivity} 円/pp</div>
          )}
          {data.impact_prediction.assumptions.baseline_jgb_10y != null && (
            <div>ベースライン金利（JGB 10Y）: {data.impact_prediction.assumptions.baseline_jgb_10y}%</div>
          )}
          {data.impact_prediction.assumptions.baseline_usdjpy != null && (
            <div>ベースライン為替（USD/JPY）: {data.impact_prediction.assumptions.baseline_usdjpy}円</div>
          )}
          {data.impact_prediction.assumptions.zlb_binding != null && (
            <div>ゼロ金利制約: {data.impact_prediction.assumptions.zlb_binding ? "有効（流動性の罠）" : "非拘束"}</div>
          )}
          {data.impact_prediction.assumptions.phillips_curve_slope != null && (
            <div>フィリップス曲線の傾き: {data.impact_prediction.assumptions.phillips_curve_slope}
              {data.impact_prediction.assumptions.phillips_r_squared != null && (
                <span> (R²={data.impact_prediction.assumptions.phillips_r_squared}
                  {data.impact_prediction.assumptions.phillips_n_obs != null && `, n=${data.impact_prediction.assumptions.phillips_n_obs}`})</span>
              )}
            </div>
          )}
          {data.impact_prediction.assumptions.baseline_inflation != null && (
            <div>ベースラインインフレ率: {data.impact_prediction.assumptions.baseline_inflation}%</div>
          )}
          {data.impact_prediction.assumptions.multiplier_decay_rate != null && (
            <div>乗数減衰率: {data.impact_prediction.assumptions.multiplier_decay_rate}/四半期</div>
          )}
          {data.impact_prediction.assumptions.lag_order != null && (
            <div>ラグ次数: {data.impact_prediction.assumptions.lag_order}</div>
          )}
          {data.impact_prediction.assumptions.n_obs != null && (
            <div>観測数: {data.impact_prediction.assumptions.n_obs}</div>
          )}
          {data.impact_prediction.assumptions.n_steps != null && (
            <div>予測ステップ数: {data.impact_prediction.assumptions.n_steps}</div>
          )}
          {data.impact_prediction.assumptions.variables && data.impact_prediction.assumptions.variables.length > 0 && (
            <div>変数: {data.impact_prediction.assumptions.variables.join(", ")}</div>
          )}
          {data.impact_prediction.assumptions.lambda_tightness != null && (
            <div>Minnesota prior tightness (lambda): {data.impact_prediction.assumptions.lambda_tightness}</div>
          )}
          {data.current_gap.gdp_gap_trillion_yen != null && (
            <div>名目GDPギャップ: {data.current_gap.gdp_gap_trillion_yen}兆円</div>
          )}
        </div>
      </details>

      {(engine === "var" || engine === "bvar") && data.impact_prediction.irf && (
        <div className="mt-6 pt-4 border-t border-gray-200">
          <h3 className="text-sm font-medium text-gray-700 mb-1">
            インパルス応答（+1兆円財政拡張ショック）
          </h3>
          <p className="text-xs text-gray-500 mb-2">
            {engine === "bvar" ? "BVAR" : "VAR"} から推定したショック応答。0期目に GDPギャップが乗数効果分シフトしたとき、
            その後のホライズンで JGB金利・USD/JPY・コアコアCPI がどう動くか（自由応答）。
          </p>
          <div className="overflow-x-auto">
            <table className="text-xs border border-gray-200 w-full">
              <thead>
                <tr className="bg-gray-50">
                  <th className="px-2 py-1 text-left">ホライズン</th>
                  <th className="px-2 py-1 text-right">GDPギャップ(pp)</th>
                  <th className="px-2 py-1 text-right">JGB10y(pp)</th>
                  <th className="px-2 py-1 text-right">USD/JPY(円)</th>
                  <th className="px-2 py-1 text-right">CPIコアコア(pp)</th>
                </tr>
              </thead>
              <tbody>
                {data.impact_prediction.irf.map((p) => (
                  <tr key={p.horizon} className="border-t border-gray-100">
                    <td className="px-2 py-1">+{p.horizon}Q</td>
                    <td className="px-2 py-1 text-right tabular-nums">
                      {p.gdp_gap?.toFixed(4) ?? "-"}
                    </td>
                    <td className="px-2 py-1 text-right tabular-nums">
                      {p.jgb_10y?.toFixed(4) ?? "-"}
                    </td>
                    <td className="px-2 py-1 text-right tabular-nums">
                      {p.usdjpy?.toFixed(3) ?? "-"}
                    </td>
                    <td className="px-2 py-1 text-right tabular-nums">
                      {p.cpi_core_core?.toFixed(4) ?? "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
