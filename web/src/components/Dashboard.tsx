import { GdpGapChart } from "./GdpGapChart";
import { FundDemandChart } from "./FundDemandChart";
import { RatesChart } from "./RatesChart";
import { PredictionChart } from "./PredictionChart";

export function Dashboard() {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <GdpGapChart />
      <FundDemandChart />
      <RatesChart />
      <PredictionChart />
    </div>
  );
}
