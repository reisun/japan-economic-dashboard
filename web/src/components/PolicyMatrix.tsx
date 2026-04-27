import { useApi } from "../hooks/useApi";
import type { GdpGapMethod, GdpGapResponse, InflationResponse } from "../types/api";

/**
 * 「ギャップ × インフレ率」マトリクス（簡易ヒートマップ）。
 *
 * 思想: ギャップだけ見て政策決定するのは危険。インフレ率を制約条件、
 * ギャップを目的関数として運用する。直近値で4象限のどこに位置するかを示す。
 *
 * - 横軸: GDPギャップ（系統に応じて意味が変わる, %）
 * - 縦軸: CPIコアコア（生鮮食品・エネルギー除く, 前年同月比%）— 日銀目標 2% を閾値とする
 *         世界標準 core CPI と同じ概念で、基調インフレを判定する
 *
 * ## 横軸の閾値（完全雇用基準ギャップ）— 系統依存
 *
 * 平均概念（cabinet_office, average）ではギャップが正にも負にもなり得るため、
 * 0% を境界として「過熱 vs 不況」を判定する従来解釈が有効。
 *
 * 一方、最大概念（生産関数アプローチ; maximum, civilian）では潜在GDPを
 * 完全雇用ベースで定義するため、構造的にギャップは常に ≤ 0 となる。
 * 0% を閾値にすると4象限のうち2つしか使われず、マトリクスが破綻する。
 * よって完全雇用近接の目安として、系統ごとに「完全雇用基準ギャップ」を設ける:
 *
 *   - cabinet_office (平均概念・公表):           0%   過熱 vs 不況
 *   - average        (HPフィルター・平均概念):    0%   過熱 vs 不況
 *   - maximum        (CBO生産関数・最大概念):   -1.0% 完全雇用近接 vs 余地あり
 *                       NAIRU=2.5% 前提の CBO methodology で典型的に観測される
 *                       「ほぼ完全雇用」域のギャップ水準を目安とする
 *   - civilian       (在野試算・最大概念寄り):  -2.0% 完全雇用近接 vs 余地大
 *                       高橋洋一・三橋貴明・藤井聡らの試算で、
 *                       インフレ目標到達直前に観測される水準の目安
 *
 * ## 象限の政策スタンス（系統で意味が変わる）
 *
 * 平均概念系は従来通り「過熱/不況」軸での解釈。
 * 最大概念系では「完全雇用近接（≒これ以上は供給制約）/ 余地あり」軸となり、
 * 「余地あり × 低インフレ」が最強の拡張シグナルとなる。
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

interface MatrixSpec {
  /** 完全雇用基準ギャップ（%）。これ以上を「過熱/完全雇用近接」、未満を「不況/余地あり」と判定 */
  gapThreshold: number;
  /** 系統種別ラベル（凡例用） */
  conceptLabel: string;
  /** ギャップ軸の右側（閾値以上）の意味 */
  rightLabel: string;
  /** ギャップ軸の左側（閾値未満）の意味 */
  leftLabel: string;
  /** 4象限の文言 */
  quadrants: QuadrantSpec[];
}

// 平均概念系（cabinet_office, average）— 0% を境に過熱/不況を判定
const AVERAGE_CONCEPT_QUADRANTS: QuadrantSpec[] = [
  {
    key: "Q2",
    title: "不況 × インフレ高",
    axis: "(左上)",
    stance: "スタグフレーション; 供給側政策",
    bg: "bg-amber-50",
    border: "border-amber-300",
  },
  {
    key: "Q1",
    title: "過熱 × インフレ高",
    axis: "(右上)",
    stance: "引き締め必要",
    bg: "bg-rose-50",
    border: "border-rose-300",
  },
  {
    key: "Q3",
    title: "不況 × インフレ低",
    axis: "(左下)",
    stance: "拡張的財政の余地大",
    bg: "bg-emerald-50",
    border: "border-emerald-300",
  },
  {
    key: "Q4",
    title: "過熱 × インフレ低",
    axis: "(右下)",
    stance: "観察継続（指標選択を疑え）",
    bg: "bg-sky-50",
    border: "border-sky-300",
  },
];

// 最大概念系（maximum, civilian）— 完全雇用近接 vs 余地あり
const MAXIMUM_CONCEPT_QUADRANTS: QuadrantSpec[] = [
  {
    key: "Q2",
    title: "余地あり × インフレ高",
    axis: "(左上)",
    stance: "スタグフレーション; 供給側政策",
    bg: "bg-amber-50",
    border: "border-amber-300",
  },
  {
    key: "Q1",
    title: "完全雇用近接 × インフレ高",
    axis: "(右上)",
    stance: "引き締め検討",
    bg: "bg-rose-50",
    border: "border-rose-300",
  },
  {
    key: "Q3",
    title: "余地あり × インフレ低",
    axis: "(左下)",
    stance: "拡張的財政の余地大（最強の拡張シグナル）",
    bg: "bg-emerald-50",
    border: "border-emerald-300",
  },
  {
    key: "Q4",
    title: "完全雇用近接 × インフレ低",
    axis: "(右下)",
    stance: "観察継続。供給側政策（投資・人材）で潜在GDP底上げ",
    bg: "bg-sky-50",
    border: "border-sky-300",
  },
];

const MATRIX_SPECS: Record<GdpGapMethod, MatrixSpec> = {
  cabinet_office: {
    gapThreshold: 0,
    conceptLabel: "平均概念（内閣府公表）",
    rightLabel: "過熱（ギャップ>0%）",
    leftLabel: "不況（ギャップ<0%）",
    quadrants: AVERAGE_CONCEPT_QUADRANTS,
  },
  average: {
    gapThreshold: 0,
    conceptLabel: "平均概念（HPフィルター）",
    rightLabel: "過熱（ギャップ>0%）",
    leftLabel: "不況（ギャップ<0%）",
    quadrants: AVERAGE_CONCEPT_QUADRANTS,
  },
  maximum: {
    // CBO methodology: 完全雇用ベースの労働投入で計算するため、ギャップは構造的に ≤ 0。
    // NAIRU=2.5% 前提下で「ほぼ完全雇用」域のギャップ水準を -1.0% を目安とする。
    gapThreshold: -1.0,
    conceptLabel: "最大概念（CBO生産関数）",
    rightLabel: "完全雇用近接（ギャップ>-1.0%）",
    leftLabel: "余地あり（ギャップ<-1.0%）",
    quadrants: MAXIMUM_CONCEPT_QUADRANTS,
  },
  civilian: {
    // 在野試算（高橋洋一・三橋貴明・藤井聡 等）はより大きいデフレギャップを示す傾向。
    // インフレ目標到達直前の水準を -2.0% を目安とする。
    gapThreshold: -2.0,
    conceptLabel: "最大概念（在野試算）",
    rightLabel: "完全雇用近接（ギャップ>-2.0%）",
    leftLabel: "余地大（ギャップ<-2.0%）",
    quadrants: MAXIMUM_CONCEPT_QUADRANTS,
  },
};

function classifyQuadrant(
  gap: number,
  inflation: number,
  inflThreshold: number,
  gapThreshold: number,
): Quadrant {
  const high = inflation >= inflThreshold;
  const rightSide = gap >= gapThreshold;
  if (high && rightSide) return "Q1";
  if (high && !rightSide) return "Q2";
  if (!high && !rightSide) return "Q3";
  return "Q4";
}

function pickGapSeries(data: GdpGapResponse, method: GdpGapMethod) {
  switch (method) {
    case "cabinet_office":
      return data.cabinet_office.data;
    case "average":
      return data.estimated_average.data;
    case "maximum":
      return data.estimated_maximum.data;
    case "civilian":
      return data.estimated_civilian.data;
  }
}

interface PolicyMatrixProps {
  /** Dashboard で選択中のギャップ系統。GdpGapChart と必ず一致させる。 */
  method: GdpGapMethod;
}

export function PolicyMatrix({ method }: PolicyMatrixProps) {
  const gdpState = useApi<GdpGapResponse>("/gdp-gap");
  const inflState = useApi<InflationResponse>("/inflation");

  const spec = MATRIX_SPECS[method];

  const wrap = (children: React.ReactNode) => (
    <div className="bg-white rounded-lg shadow p-6">
      <h2 className="text-lg font-semibold mb-1">
        ギャップ × インフレ率 マトリクス
      </h2>
      <p className="text-xs text-gray-500 mb-3">
        ギャップだけで政策判断するのは危険。インフレ率を制約条件、
        ギャップを目的関数として運用する。
        <br />
        <span className="text-gray-400">
          ※ 平均概念か最大概念かによって、横軸の意味そのものが異なる。
        </span>
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

  // 直近値: 選択中の系統のギャップと CPIコアコア
  const series = pickGapSeries(gdpData, method);
  const lastGap = series[series.length - 1];
  const lastInfl = inflData.data[inflData.data.length - 1];
  const gapPct = lastGap?.gdp_gap_percent ?? 0;
  const cpi = lastInfl?.cpi_core_core ?? 0;
  const inflThreshold = inflData.boj_target;

  const active = classifyQuadrant(gapPct, cpi, inflThreshold, spec.gapThreshold);

  return wrap(
    <>
      <div className="flex flex-wrap gap-3 mb-4 text-sm">
        <div>
          <span className="text-gray-500">直近ギャップ（{spec.conceptLabel}）: </span>
          <span className="font-semibold">
            {gapPct >= 0 ? "+" : ""}
            {gapPct.toFixed(2)}%
          </span>
        </div>
        <div>
          <span className="text-gray-500">直近 CPIコアコア: </span>
          <span className="font-semibold">
            {cpi >= 0 ? "+" : ""}
            {cpi.toFixed(2)}%
          </span>
        </div>
        <div>
          <span className="text-gray-500">インフレ閾値: </span>
          <span className="font-semibold">{inflThreshold.toFixed(1)}%</span>
        </div>
        <div>
          <span className="text-gray-500">完全雇用基準ギャップ: </span>
          <span className="font-semibold">
            {spec.gapThreshold >= 0 ? "+" : ""}
            {spec.gapThreshold.toFixed(1)}%
          </span>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {spec.quadrants.map((q) => {
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
        <div>← {spec.leftLabel}</div>
        <div className="text-right">{spec.rightLabel} →</div>
      </div>
    </>,
  );
}
