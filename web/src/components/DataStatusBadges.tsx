/**
 * DataStatusBadges: API data_status dict をもとに、各系列の
 * 実データ/モック状態を小さなバッジで表示する共通コンポーネント。
 */

interface DataStatusBadgesProps {
  status: Record<string, string> | undefined;
  /** 系列キー -> 日本語ラベルのマッピング（省略時はキーをそのまま表示） */
  labels?: Record<string, string>;
}

export function DataStatusBadges({ status, labels }: DataStatusBadgesProps) {
  if (!status) return null;

  return (
    <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-gray-500">
      {Object.entries(status).map(([key, value]) => {
        const isReal = value === "real";
        const label = labels?.[key] ?? key;
        return (
          <span key={key} className="inline-flex items-center gap-1">
            <span
              className={
                "inline-block w-1.5 h-1.5 rounded-full " +
                (isReal ? "bg-green-500" : "bg-amber-400")
              }
            />
            <span>{label}</span>
            <span className={isReal ? "text-green-600" : "text-amber-600"}>
              {isReal ? "実データ" : "モック"}
            </span>
          </span>
        );
      })}
    </div>
  );
}
