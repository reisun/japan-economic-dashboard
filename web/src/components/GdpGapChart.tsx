import { useState } from "react";
import type { Dispatch, SetStateAction } from "react";
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
  civilian: "在野試算",
};

const METHOD_DESC: Record<GdpGapMethod, string> = {
  cabinet_office: "内閣府公表のGDPギャップ%",
  average: "HPフィルターによる平均概念（旧 estimated）",
  maximum: "Cobb-Douglas（CBO methodology: 完全雇用労働投入 × capital services × TFP_max, α=0.33, NAIRU=2.5%）",
  civilian: "在野試算（高橋洋一・三橋貴明・藤井聡らの代表的試算レンジに基づく合成系列）",
};

const METHOD_COLOR: Record<GdpGapMethod, string> = {
  cabinet_office: "#2563eb",
  average: "#dc2626",
  maximum: "#059669",
  civilian: "#9333ea",
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
    method === "average"
      ? data.estimated_average
      : method === "maximum"
      ? data.estimated_maximum
      : data.estimated_civilian;
  return block.data.map((p) => ({ date: p.date, value: p.gdp_gap_percent }));
}

interface GdpGapChartProps {
  /**
   * 選択中のギャップ系統。Dashboard 側で保持して PolicyMatrix と共有する。
   * 未指定の場合は内部 state で `maximum` をデフォルトとする（後方互換）。
   */
  method?: GdpGapMethod;
  onMethodChange?: Dispatch<SetStateAction<GdpGapMethod>>;
}

export function GdpGapChart({ method: methodProp, onMethodChange }: GdpGapChartProps = {}) {
  const [internalMethod, setInternalMethod] = useState<GdpGapMethod>("maximum");
  const method = methodProp ?? internalMethod;
  const setMethod: Dispatch<SetStateAction<GdpGapMethod>> =
    onMethodChange ?? setInternalMethod;
  const { data, loading, error } = useApi<GdpGapResponse>("/gdp-gap");

  // タブ表示順: 内閣府公表 / 平均概念 / 最大概念 / 在野試算
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
      : method === "maximum"
      ? `推計: ${data.estimated_maximum.method}`
      : `推計: ${data.estimated_civilian.method}`;

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
            stroke={METHOD_COLOR[method]}
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
