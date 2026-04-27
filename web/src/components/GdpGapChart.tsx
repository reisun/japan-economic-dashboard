import { useState } from "react";
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
import type { GdpGapMethod, GdpGapResponse } from "../types/api";

interface ChartPoint {
  date: string;
  value: number | null;
}

const METHOD_LABEL: Record<GdpGapMethod, string> = {
  cabinet_office: "内閣府公表",
  average: "平均概念",
  maximum: "最大概念",
};

const METHOD_DESC: Record<GdpGapMethod, string> = {
  cabinet_office: "内閣府公表のGDPギャップ%",
  average: "HPフィルターによる平均概念（旧 estimated）",
  maximum: "Cobb-Douglas 生産関数（TFPトレンド × 完全雇用労働投入 × 資本ストック, α=0.33, NAIRU=2.5%）",
};

function buildSeries(
  data: GdpGapResponse,
  method: GdpGapMethod,
): ChartPoint[] {
  if (method === "cabinet_office") {
    return data.cabinet_office.data.map((p) => ({
      date: p.date,
      value: p.gdp_gap_percent,
    }));
  }
  const block =
    method === "average" ? data.estimated_average : data.estimated_maximum;
  return block.data.map((p) => ({ date: p.date, value: p.gdp_gap_percent }));
}

export function GdpGapChart() {
  const [method, setMethod] = useState<GdpGapMethod>("maximum");
  const { data, loading, error } = useApi<GdpGapResponse>("/gdp-gap");

  const tabs: { key: GdpGapMethod; label: string }[] = [
    { key: "cabinet_office", label: METHOD_LABEL.cabinet_office },
    { key: "average", label: METHOD_LABEL.average },
    { key: "maximum", label: METHOD_LABEL.maximum },
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

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold mb-4">GDPギャップ</h2>
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
        <h2 className="text-lg font-semibold mb-4">GDPギャップ</h2>
        {renderTabs()}
        <div className="h-64 flex items-center justify-center text-red-500">
          {error || "データの取得に失敗しました"}
        </div>
      </div>
    );
  }

  const series = buildSeries(data, method);

  const sourceLabel =
    method === "cabinet_office"
      ? `出典: ${data.cabinet_office.source}`
      : method === "average"
      ? `推計: ${data.estimated_average.method}`
      : `推計: ${data.estimated_maximum.method}`;

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h2 className="text-lg font-semibold mb-1">GDPギャップ</h2>
      <p className="text-xs text-gray-500 mb-3">{METHOD_DESC[method]}</p>
      {renderTabs()}
      <p className="text-xs text-gray-500 mb-2">{sourceLabel}</p>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={series}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} />
          <YAxis
            tick={{ fontSize: 11 }}
            tickFormatter={(v: number) => `${v}%`}
          />
          <Tooltip formatter={(value: number) => [`${value.toFixed(2)}%`]} />
          <Legend />
          <ReferenceLine y={0} stroke="#999" strokeDasharray="3 3" />
          <Line
            type="monotone"
            dataKey="value"
            name={METHOD_LABEL[method]}
            stroke={
              method === "cabinet_office"
                ? "#2563eb"
                : method === "average"
                ? "#dc2626"
                : "#059669"
            }
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
