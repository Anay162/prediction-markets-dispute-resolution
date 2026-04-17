// src/components/RCSGauge.tsx
// Circular gauge showing the Resolution Clarity Score.
// Uses an SVG arc to display the score visually.

interface RCSGaugeProps {
  score: number; // 0-100
  size?: number; // px
}

function scoreColor(score: number): string {
  if (score >= 85) return "#16a34a"; // green-600
  if (score >= 70) return "#ca8a04"; // yellow-600
  if (score >= 50) return "#ea580c"; // orange-600
  return "#dc2626";                  // red-600
}

export default function RCSGauge({ score, size = 80 }: RCSGaugeProps) {
  const radius = (size - 8) / 2;
  const circumference = 2 * Math.PI * radius;
  const clampedScore = Math.max(0, Math.min(100, score));
  const dashOffset = circumference * (1 - clampedScore / 100);
  const color = scoreColor(clampedScore);
  const cx = size / 2;
  const cy = size / 2;

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        {/* Track */}
        <circle
          cx={cx}
          cy={cy}
          r={radius}
          fill="none"
          stroke="#e5e7eb"
          strokeWidth={6}
        />
        {/* Progress */}
        <circle
          cx={cx}
          cy={cy}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={6}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          style={{ transition: "stroke-dashoffset 0.6s ease" }}
        />
      </svg>
      <div
        className="absolute inset-0 flex flex-col items-center justify-center"
        style={{ color }}
      >
        <span className="text-lg font-bold leading-none">{clampedScore}</span>
        <span className="text-xs text-gray-400 leading-none mt-0.5">RCS</span>
      </div>
    </div>
  );
}
