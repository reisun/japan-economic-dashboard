import { useEffect, useRef, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { STATIC_MODE, useApi } from "../hooks/useApi";
import type { GdpGapMethod, PredictionResponse } from "../types/api";

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

const METHOD_LABEL: Record<GdpGapMethod, string> = {
  cabinet_office: "内閣府公表",
  average: "平均概念",
  maximum: "最大概念",
  civilian: "在野試算",
};

// シナリオ入力の範囲（API 側と揃える）
const SCENARIO_MIN = -200;
const SCENARIO_MAX = 200;
const SCENARIO_STEP = 0.5;
const DEBOUNCE_MS = 500;

function buildPredictionPath(
  method: GdpGapMethod,
  scenario: number | null,
): string {
  if (STATIC_MODE) {
    // 静的モードではシナリオ入力に対応できないため固定 JSON を返す
    return `/prediction-${method}.json`;
  }
  if (scenario === null || Number.isNaN(scenario)) {
    return `/prediction?method=${method}`;
  }
  return `/prediction?method=${method}&fiscal_spending_trillion=${scenario}`;
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

function clampScenario(v: number): number {
  if (Number.isNaN(v)) return 0;
  return Math.max(SCENARIO_MIN, Math.min(SCENARIO_MAX, v));
}

export function PredictionChart() {
  const [method, setMethod] = useState<GdpGapMethod>("maximum");

  // シナリオ入力（ユーザー操作中のローカル値, null=自動）
  const [scenarioInput, setScenarioInput] = useState<number | null>(null);
  // API に投げるための debounce 済み値
  const [debouncedScenario, setDebouncedScenario] = useState<number | null>(
    null,
  );
  // <input> のテキスト表現（途中入力で "" や "-" を許容するため文字列を別管理）
  const [scenarioText, setScenarioText] = useState<string>("");

  // debounce: scenarioInput → debouncedScenario
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }
    debounceRef.current = setTimeout(() => {
      setDebouncedScenario(scenarioInput);
    }, DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [scenarioInput]);

  // method 切替時はシナリオを自動に戻す
  useEffect(() => {
    setScenarioInput(null);
    setScenarioText("");
    setDebouncedScenario(null);
  }, [method]);

  const path = buildPredictionPath(method, debouncedScenario);
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

  const handleScenarioChange = (value: number) => {
    const clamped = clampScenario(value);
    setScenarioInput(clamped);
    setScenarioText(String(clamped));
  };

  const handleTextChange = (text: string) => {
    setScenarioText(text);
    if (text === "" || text === "-" || text === "+") {
      // 入力途中: API は呼ばない（自動状態にも戻さない）
      return;
    }
    const parsed = Number(text);
    if (!Number.isNaN(parsed)) {
      setScenarioInput(clampScenario(parsed));
    }
  };

  const handleAutoReset = () => {
    setScenarioInput(null);
    setScenarioText("");
    setDebouncedScenario(null);
  };

  // サマリーから自動算出値（auto モード時のフォールバック含む）
  const autoAmount =
    data?.required_fiscal_spending.auto_amount_trillion_yen ??
    (data?.required_fiscal_spending.scenario_mode === "auto"
      ? data?.required_fiscal_spending.amount_trillion_yen
      : undefined);

  const isUserScenario =
    !STATIC_MODE && data?.required_fiscal_spending.scenario_mode === "user";

  // 入力値（スライダー / 数値入力で表示する値）。null のときは自動算出値を表示。
  const displayScenarioValue =
    scenarioInput !== null
      ? scenarioInput
      : (autoAmount ?? 0);

  const renderScenarioPanel = () => {
    const disabled = STATIC_MODE;
    const tooltip = disabled
      ? "静的モードでは利用不可"
      : undefined;
    return (
      <div className="bg-gray-50 border border-gray-200 rounded p-3 mb-4">
        <div className="flex items-baseline justify-between mb-2 gap-2 flex-wrap">
          <h3 className="text-sm font-medium text-gray-800">
            シナリオ入力（任意の財政支出額）
          </h3>
          {isUserScenario && autoAmount !== undefined && (
            <span className="text-xs text-gray-500">
              自動算出値: {autoAmount.toFixed(1)}兆円
            </span>
          )}
        </div>
        <p className="text-xs text-gray-500 mb-3">
          任意の財政支出額（兆円）を入力すると、IS-LM
          モデルで金利・為替への影響を再計算します。
          <br />
          正値: 拡張的財政支出 / 負値: 引き締め
        </p>
        <div
          className="flex flex-wrap items-center gap-3"
          title={tooltip}
        >
          <input
            type="number"
            step={SCENARIO_STEP}
            min={SCENARIO_MIN}
            max={SCENARIO_MAX}
            value={scenarioText !== "" ? scenarioText : (scenarioInput !== null ? String(scenarioInput) : "")}
            placeholder={
              autoAmount !== undefined
                ? `${autoAmount.toFixed(1)} (自動)`
                : "自動"
            }
            onChange={(e) => handleTextChange(e.target.value)}
            disabled={disabled}
            className="w-28 px-2 py-1 text-sm border border-gray-300 rounded disabled:bg-gray-100 disabled:text-gray-400"
            aria-label="財政支出額（兆円）"
          />
          <span className="text-xs text-gray-500">兆円</span>
          <input
            type="range"
            step={SCENARIO_STEP}
            min={SCENARIO_MIN}
            max={SCENARIO_MAX}
            value={displayScenarioValue}
            onChange={(e) => handleScenarioChange(Number(e.target.value))}
            disabled={disabled}
            className="flex-1 min-w-[140px] disabled:opacity-50"
            aria-label="財政支出額スライダー"
          />
          <button
            type="button"
            onClick={handleAutoReset}
            disabled={disabled || scenarioInput === null}
            className="px-3 py-1 text-xs font-medium border border-gray-300 rounded bg-white hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            自動
          </button>
        </div>
        {disabled && (
          <p className="text-xs text-gray-400 mt-2">
            ※ 静的モードではシナリオ入力は利用できません
          </p>
        )}
      </div>
    );
  };

  if (loading && !data) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold mb-4">予測（IS-LMモデル）</h2>
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
        <h2 className="text-lg font-semibold mb-4">予測（IS-LMモデル）</h2>
        {renderTabs()}
        <div className="h-64 flex items-center justify-center text-red-500">
          {error || "データの取得に失敗しました"}
        </div>
      </div>
    );
  }

  const rateData = splitRateData(data);
  const fxData = splitFxData(data);

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h2 className="text-lg font-semibold mb-1">予測（IS-LMモデル）</h2>
      <p className="text-xs text-gray-500 mb-3">
        ギャップ起点: {METHOD_LABEL[method]} / モデル:{" "}
        {data.impact_prediction.model} / 乗数:{" "}
        {data.impact_prediction.assumptions.fiscal_multiplier}
      </p>
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
        <div
          className={
            "rounded p-3 " +
            (isUserScenario ? "bg-amber-50" : "bg-green-50")
          }
        >
          <p className="text-xs text-gray-600">
            {isUserScenario ? "シナリオ財政支出" : "必要財政支出"}
          </p>
          <p
            className={
              "text-lg font-bold " +
              (isUserScenario ? "text-amber-900" : "text-green-900")
            }
          >
            {data.required_fiscal_spending.amount_trillion_yen}兆円
          </p>
          <p className="text-xs text-gray-500">
            {data.required_fiscal_spending.note}
          </p>
        </div>
      </div>

      {renderScenarioPanel()}

      {loading && (
        <p className="text-xs text-gray-400 mb-2">更新中...</p>
      )}

      <div className="mb-4">
        <h3 className="text-sm font-medium text-gray-700 mb-2">
          金利予測（JGB 10年）
        </h3>
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={rateData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v: number) => `${v}%`} />
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

      <div>
        <h3 className="text-sm font-medium text-gray-700 mb-2">
          為替予測（USD/JPY）
        </h3>
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={fxData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
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
    </div>
  );
}
