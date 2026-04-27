import { useState } from "react";
import { GdpGapChart } from "./GdpGapChart";
import { InflationPanel } from "./InflationPanel";
import { PolicyMatrix } from "./PolicyMatrix";
import { FundDemandChart } from "./FundDemandChart";
import { RatesChart } from "./RatesChart";
import { PredictionChart } from "./PredictionChart";
import type { GdpGapMethod } from "../types/api";

export function Dashboard() {
  // GDPギャップ系統の選択状態を上位（Dashboard）で保持し、
  // GdpGapChart と PolicyMatrix で共有する。
  // 平均概念か最大概念かによって、PolicyMatrix の横軸の意味そのものが
  // 異なる（過熱/不況 vs 完全雇用近接/余地あり）ため、
  // 両者で同一の系統を参照する必要がある。
  const [gapMethod, setGapMethod] = useState<GdpGapMethod>("maximum");

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <GdpGapChart method={gapMethod} onMethodChange={setGapMethod} />
      <InflationPanel />
      <PolicyMatrix method={gapMethod} />
      <FundDemandChart />
      <RatesChart />
      <PredictionChart />
    </div>
  );
}
