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
import type { GdpGapResponse } from "../types/api";

interface MergedDataPoint {
  date: string;
  cabinet_office: number | null;
  estimated: number | null;
}

function mergeData(data: GdpGapResponse): MergedDataPoint[] {
  const map = new Map<string, MergedDataPoint>();

  for (const point of data.cabinet_office.data) {
    map.set(point.date, {
      date: point.date,
      cabinet_office: point.gdp_gap_percent,
      estimated: null,
    });
  }

  for (const point of data.estimated.data) {
    const existing = map.get(point.date);
    if (existing) {
      existing.estimated = point.gdp_gap_percent;
    } else {
      map.set(point.date, {
        date: point.date,
        cabinet_office: null,
        estimated: point.gdp_gap_percent,
      });
    }
  }

  return Array.from(map.values()).sort((a, b) =>
    a.date.localeCompare(b.date)
  );
}

export function GdpGapChart() {
  const { data, loading, error } = useApi<GdpGapResponse>("/gdp-gap");

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold mb-4">GDPギャップ</h2>
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
        <div className="h-64 flex items-center justify-center text-red-500">
          {error || "データの取得に失敗しました"}
        </div>
      </div>
    );
  }

  const merged = mergeData(data);

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h2 className="text-lg font-semibold mb-1">GDPギャップ</h2>
      <p className="text-xs text-gray-500 mb-4">
        出典: {data.cabinet_office.source} / 自前推計（{data.estimated.method}）
      </p>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={merged}>
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
          <ReferenceLine y={0} stroke="#999" strokeDasharray="3 3" />
          <Line
            type="monotone"
            dataKey="cabinet_office"
            name="内閣府推計"
            stroke="#2563eb"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="estimated"
            name="自前推計"
            stroke="#dc2626"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
