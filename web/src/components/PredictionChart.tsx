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
import { useApi } from "../hooks/useApi";
import type { PredictionResponse } from "../types/api";

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

export function PredictionChart() {
  const { data, loading, error } = useApi<PredictionResponse>("/prediction");

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold mb-4">予測（IS-LMモデル）</h2>
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
      <p className="text-xs text-gray-500 mb-4">
        モデル: {data.impact_prediction.model} / 乗数:{" "}
        {data.impact_prediction.assumptions.fiscal_multiplier}
      </p>

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
        <div className="bg-green-50 rounded p-3">
          <p className="text-xs text-gray-600">必要財政支出</p>
          <p className="text-lg font-bold text-green-900">
            {data.required_fiscal_spending.amount_trillion_yen}兆円
          </p>
          <p className="text-xs text-gray-500">
            {data.required_fiscal_spending.note}
          </p>
        </div>
      </div>

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
