import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { useApi } from "../hooks/useApi";
import type { InflationResponse } from "../types/api";

/**
 * インフレ率パネル: CPIコア / GDPデフレータ / 賃金上昇率（前年同期比%）。
 * 「ギャップは目的関数、インフレ率は制約条件」の運用思想を可視化する。
 * 日銀インフレ目標 2% を破線で表示。
 */
export function InflationPanel() {
  const { data, loading, error } =
    useApi<InflationResponse>("/inflation");

  const wrap = (children: React.ReactNode) => (
    <div className="bg-white rounded-lg shadow p-6">
      <h2 className="text-lg font-semibold mb-1">インフレ率</h2>
      <p className="text-xs text-gray-500 mb-3">
        CPIコア / GDPデフレータ / 名目賃金（前年同期比%）。日銀目標 2% を破線で表示。
      </p>
      {children}
    </div>
  );

  if (loading) {
    return wrap(
      <div className="h-64 flex items-center justify-center text-gray-400">
        読み込み中...
      </div>,
    );
  }
  if (error || !data) {
    return wrap(
      <div className="h-64 flex items-center justify-center text-red-500">
        {error || "データの取得に失敗しました"}
      </div>,
    );
  }

  const latest = data.data[data.data.length - 1];

  const card = (label: string, value: number | null, color: string) => (
    <div className="flex-1 min-w-[110px] rounded-md border border-gray-200 p-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div
        className="text-2xl font-semibold mt-1"
        style={{ color }}
      >
        {value === null || value === undefined
          ? "—"
          : `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`}
      </div>
    </div>
  );

  return wrap(
    <>
      <p className="text-xs text-gray-500 mb-2">出典: {data.source}</p>
      <div className="flex flex-wrap gap-2 mb-3">
        {card("CPIコア", latest.cpi_core, "#dc2626")}
        {card("GDPデフレータ", latest.gdp_deflator, "#2563eb")}
        {card("賃金上昇率", latest.wage_growth, "#059669")}
      </div>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data.data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} />
          <YAxis
            tick={{ fontSize: 11 }}
            tickFormatter={(v: number) => `${v}%`}
          />
          <Tooltip
            formatter={(value: number) => [`${value.toFixed(2)}%`]}
          />
          <Legend />
          <ReferenceLine
            y={data.boj_target}
            stroke="#9ca3af"
            strokeDasharray="4 4"
            label={{
              value: `日銀目標 ${data.boj_target}%`,
              position: "right",
              fontSize: 10,
              fill: "#6b7280",
            }}
          />
          <Line
            type="monotone"
            dataKey="cpi_core"
            name="CPIコア"
            stroke="#dc2626"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="gdp_deflator"
            name="GDPデフレータ"
            stroke="#2563eb"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="wage_growth"
            name="賃金上昇率"
            stroke="#059669"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </>,
  );
}
