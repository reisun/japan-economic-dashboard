import { useApi } from "../hooks/useApi";
import type { GdpGapResponse, InflationResponse } from "../types/api";

/**
 * 「ギャップ × インフレ率」マトリクス（簡易ヒートマップ）。
 *
 * 思想: ギャップだけ見て政策決定するのは危険。インフレ率を制約条件、
 * ギャップを目的関数として運用する。直近値で4象限のどこに位置するかを示す。
 *
 * - 横軸: GDPギャップ（最大概念, %）
 * - 縦軸: CPIコア（前年同月比%）— 日銀目標 2% を閾値とする
 *
 * 各象限の推奨スタンス:
 *   ギャップ負 × インフレ低 → 拡張的財政の余地大
 *   ギャップ正 × インフレ高 → 引き締め必要
 *   ギャップ負 × インフレ高 → スタグフレーション; 供給側政策
 *   ギャップ正 × インフレ低 → 観察継続（指標選択を疑え）
 */

type Quadrant = "Q1" | "Q2" | "Q3" | "Q4";

interface QuadrantSpec {
  key: Quadrant;
  title: string;
  axis: string;
  stance: string;
  bg: string;
  border: string;
}

// 配置: 上段=インフレ高, 下段=インフレ低 / 左列=ギャップ負, 右列=ギャップ正
const QUADRANTS: QuadrantSpec[] = [
  {
    key: "Q2",
    title: "ギャップ負 × インフレ高",
    axis: "(左上)",
    stance: "スタグフレーション; 供給側政策",
    bg: "bg-amber-50",
    border: "border-amber-300",
  },
  {
    key: "Q1",
    title: "ギャップ正 × インフレ高",
    axis: "(右上)",
    stance: "引き締め必要",
    bg: "bg-rose-50",
    border: "border-rose-300",
  },
  {
    key: "Q3",
    title: "ギャップ負 × インフレ低",
    axis: "(左下)",
    stance: "拡張的財政の余地大",
    bg: "bg-emerald-50",
    border: "border-emerald-300",
  },
  {
    key: "Q4",
    title: "ギャップ正 × インフレ低",
    axis: "(右下)",
    stance: "観察継続（指標選択を疑え）",
    bg: "bg-sky-50",
    border: "border-sky-300",
  },
];

function classifyQuadrant(
  gap: number,
  inflation: number,
  inflThreshold: number,
): Quadrant {
  const high = inflation >= inflThreshold;
  const positiveGap = gap >= 0;
  if (high && positiveGap) return "Q1";
  if (high && !positiveGap) return "Q2";
  if (!high && !positiveGap) return "Q3";
  return "Q4";
}

export function PolicyMatrix() {
  const gdpState = useApi<GdpGapResponse>("/gdp-gap");
  const inflState = useApi<InflationResponse>("/inflation");

  const wrap = (children: React.ReactNode) => (
    <div className="bg-white rounded-lg shadow p-6">
      <h2 className="text-lg font-semibold mb-1">
        ギャップ × インフレ率 マトリクス
      </h2>
      <p className="text-xs text-gray-500 mb-3">
        ギャップだけで政策判断するのは危険。インフレ率を制約条件、
        ギャップを目的関数として運用する。
      </p>
      {children}
    </div>
  );

  if (gdpState.loading || inflState.loading) {
    return wrap(
      <div className="h-64 flex items-center justify-center text-gray-400">
        読み込み中...
      </div>,
    );
  }
  if (gdpState.error || !gdpState.data || inflState.error || !inflState.data) {
    return wrap(
      <div className="h-64 flex items-center justify-center text-red-500">
        {gdpState.error || inflState.error || "データの取得に失敗しました"}
      </div>,
    );
  }

  const gdpData = gdpState.data;
  const inflData = inflState.data;

  // 直近値: 最大概念ギャップ（生産関数ベース）と CPIコア
  const lastGap =
    gdpData.estimated_maximum.data[gdpData.estimated_maximum.data.length - 1];
  const lastInfl = inflData.data[inflData.data.length - 1];
  const gapPct = lastGap?.gdp_gap_percent ?? 0;
  const cpi = lastInfl?.cpi_core ?? 0;
  const threshold = inflData.boj_target;

  const active = classifyQuadrant(gapPct, cpi, threshold);

  return wrap(
    <>
      <div className="flex flex-wrap gap-3 mb-4 text-sm">
        <div>
          <span className="text-gray-500">直近ギャップ（最大概念）: </span>
          <span className="font-semibold">
            {gapPct >= 0 ? "+" : ""}
            {gapPct.toFixed(2)}%
          </span>
        </div>
        <div>
          <span className="text-gray-500">直近 CPIコア: </span>
          <span className="font-semibold">
            {cpi >= 0 ? "+" : ""}
            {cpi.toFixed(2)}%
          </span>
        </div>
        <div>
          <span className="text-gray-500">インフレ閾値: </span>
          <span className="font-semibold">{threshold.toFixed(1)}%</span>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {QUADRANTS.map((q) => {
          const isActive = q.key === active;
          return (
            <div
              key={q.key}
              className={
                "rounded-md border-2 p-3 transition-all " +
                q.bg +
                " " +
                (isActive
                  ? "border-gray-900 shadow-md scale-[1.01]"
                  : `${q.border} opacity-60`)
              }
            >
              <div className="flex items-baseline justify-between gap-2">
                <div className="text-sm font-semibold text-gray-800">
                  {q.title}
                </div>
                <div className="text-[10px] text-gray-400">{q.axis}</div>
              </div>
              <div className="mt-1 text-sm text-gray-700">{q.stance}</div>
              {isActive && (
                <div className="mt-2 text-[11px] font-semibold text-gray-900">
                  ← 現在地
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-[10px] text-gray-400">
        <div>← ギャップ負（デフレ）</div>
        <div className="text-right">ギャップ正（インフレ）→</div>
      </div>
    </>,
  );
}
