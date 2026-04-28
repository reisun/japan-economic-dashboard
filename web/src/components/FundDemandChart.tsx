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
import type { FundDemandResponse } from "../types/api";
import { DataStatusBadges } from "./DataStatusBadges";

const SECTOR_LABELS: Record<string, string> = {
  households: "家計",
  corporations: "企業",
  government: "政府",
};

const SECTOR_COLORS: Record<string, string> = {
  households: "#2563eb",
  corporations: "#dc2626",
  government: "#16a34a",
};

interface MergedFlowPoint {
  date: string;
  [sector: string]: number | string | null;
}

function mergeFlowData(data: FundDemandResponse): MergedFlowPoint[] {
  const map = new Map<string, MergedFlowPoint>();

  for (const point of data.flow_of_funds.data) {
    const existing = map.get(point.date);
    if (existing) {
      existing[point.sector] = point.net_lending;
    } else {
      map.set(point.date, {
        date: point.date,
        [point.sector]: point.net_lending,
      });
    }
  }

  return Array.from(map.values()).sort((a, b) =>
    a.date.localeCompare(b.date)
  );
}

export function FundDemandChart() {
  const { data, loading, error } = useApi<FundDemandResponse>("/fund-demand");

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold mb-4">資金需要</h2>
        <div className="h-64 flex items-center justify-center text-gray-400">
          読み込み中...
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold mb-4">資金需要</h2>
        <div className="h-64 flex items-center justify-center text-red-500">
          {error || "データの取得に失敗しました"}
        </div>
      </div>
    );
  }

  const flowData = mergeFlowData(data);
  const sectors = [...new Set(data.flow_of_funds.data.map((d) => d.sector))];

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h2 className="text-lg font-semibold mb-1">資金需要</h2>
      <p className="text-xs text-gray-500 mb-1">
        出典: {data.flow_of_funds.source} / {data.bank_lending.source}
        （単位: {data.flow_of_funds.unit}）
      </p>
      <div className="mb-3">
        <DataStatusBadges
          status={data.data_status}
          labels={{
            flow_of_funds: "資金循環",
            bank_lending: "銀行貸出",
          }}
        />
      </div>

      <div className="mb-4">
        <h3 className="text-sm font-medium text-gray-700 mb-2">
          セクター別 資金過不足
        </h3>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={flowData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis
              tick={{ fontSize: 11 }}
              tickFormatter={(v: number) => `${v}兆円`}
            />
            <Tooltip
              formatter={(value: number) => [`${value.toFixed(1)}兆円`]}
            />
            <Legend />
            <ReferenceLine y={0} stroke="#999" strokeDasharray="3 3" />
            {sectors.map((sector) => (
              <Line
                key={sector}
                type="monotone"
                dataKey={sector}
                name={SECTOR_LABELS[sector] || sector}
                stroke={SECTOR_COLORS[sector] || "#6b7280"}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div>
        <h3 className="text-sm font-medium text-gray-700 mb-2">
          銀行貸出残高（前年比）
        </h3>
        <ResponsiveContainer width="100%" height={160}>
          <LineChart data={data.bank_lending.data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis
              tick={{ fontSize: 11 }}
              tickFormatter={(v: number) => `${v}%`}
            />
            <Tooltip
              formatter={(value: number) => [`${value.toFixed(1)}%`]}
            />
            <Legend />
            <Line
              type="monotone"
              dataKey="yoy_change_percent"
              name="前年比"
              stroke="#7c3aed"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
