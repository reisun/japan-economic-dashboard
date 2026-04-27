import { GdpGapChart } from "./GdpGapChart";
import { InflationPanel } from "./InflationPanel";
import { PolicyMatrix } from "./PolicyMatrix";
import { FundDemandChart } from "./FundDemandChart";
import { RatesChart } from "./RatesChart";
import { PredictionChart } from "./PredictionChart";

export function Dashboard() {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <GdpGapChart />
      <InflationPanel />
      <PolicyMatrix />
      <FundDemandChart />
      <RatesChart />
      <PredictionChart />
    </div>
  );
}
