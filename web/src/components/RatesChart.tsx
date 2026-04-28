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
import type { RatesResponse } from "../types/api";
import { DataStatusBadges } from "./DataStatusBadges";

interface MergedRatePoint {
  date: string;
  jgb_10y_yield: number | null;
  us_10y_yield: number | null;
  policy_rate: number | null;
}

interface MergedFxPoint {
  date: string;
  usdjpy: number | null;
}

function mergeRateData(data: RatesResponse): MergedRatePoint[] {
  const map = new Map<string, MergedRatePoint>();

  for (const point of data.interest_rates.boj) {
    map.set(point.date, {
      date: point.date,
      jgb_10y_yield: point.jgb_10y_yield,
      policy_rate: point.policy_rate,
      us_10y_yield: null,
    });
  }

  for (const point of data.interest_rates.fred) {
    const existing = map.get(point.date);
    if (existing) {
      existing.us_10y_yield = point.us_10y_yield;
    } else {
      map.set(point.date, {
        date: point.date,
        jgb_10y_yield: null,
        policy_rate: null,
        us_10y_yield: point.us_10y_yield,
      });
    }
  }

  return Array.from(map.values()).sort((a, b) =>
    a.date.localeCompare(b.date)
  );
}

function mergeFxData(data: RatesResponse): MergedFxPoint[] {
  const map = new Map<string, MergedFxPoint>();

  const sources = [
    ...data.exchange_rates.yahoo_finance,
    ...data.exchange_rates.fred,
  ];

  for (const point of sources) {
    if (!map.has(point.date)) {
      map.set(point.date, { date: point.date, usdjpy: point.usdjpy });
    }
  }

  return Array.from(map.values()).sort((a, b) =>
    a.date.localeCompare(b.date)
  );
}

export function RatesChart() {
  const { data, loading, error } = useApi<RatesResponse>("/rates");

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold mb-4">金利・為替</h2>
        <div className="h-64 flex items-center justify-center text-gray-400">
          読み込み中...
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold mb-4">金利・為替</h2>
        <div className="h-64 flex items-center justify-center text-red-500">
          {error || "データの取得に失敗しました"}
        </div>
      </div>
    );
  }

  const rateData = mergeRateData(data);
  const fxData = mergeFxData(data);

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h2 className="text-lg font-semibold mb-1">金利・為替</h2>
      <p className="text-xs text-gray-500 mb-1">
        出典: FRED / 日銀 / Yahoo Finance
      </p>
      <div className="mb-3">
        <DataStatusBadges
          status={data.data_status}
          labels={{
            fred_rates: "米金利(FRED)",
            boj_rates: "日本金利",
            yahoo_fx: "為替(Yahoo)",
            fred_fx: "為替(FRED)",
          }}
        />
      </div>

      <div className="mb-4">
        <h3 className="text-sm font-medium text-gray-700 mb-2">金利</h3>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={rateData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v: number) => `${v}%`} />
            <Tooltip formatter={(value: number) => [`${value.toFixed(2)}%`]} />
            <Legend />
            <Line
              type="monotone"
              dataKey="jgb_10y_yield"
              name="JGB 10年"
              stroke="#2563eb"
              strokeWidth={2}
              dot={false}
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="us_10y_yield"
              name="米国債 10年"
              stroke="#dc2626"
              strokeWidth={2}
              dot={false}
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="policy_rate"
              name="日銀政策金利"
              stroke="#16a34a"
              strokeWidth={1}
              strokeDasharray="5 5"
              dot={false}
              connectNulls
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div>
        <h3 className="text-sm font-medium text-gray-700 mb-2">為替（USD/JPY）</h3>
        <ResponsiveContainer width="100%" height={160}>
          <LineChart data={fxData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
            <Tooltip formatter={(value: number) => [`${value.toFixed(1)}円`]} />
            <Legend />
            <Line
              type="monotone"
              dataKey="usdjpy"
              name="USD/JPY"
              stroke="#d97706"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
