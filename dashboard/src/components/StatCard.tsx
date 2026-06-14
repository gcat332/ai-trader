// dashboard/src/components/StatCard.tsx
export function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-sm font-bold text-gray-900 mt-1">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}
