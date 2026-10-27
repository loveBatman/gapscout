import type { TopicShape } from "../../lib/utils";

/**
 * 主题标记：用「灰阶深浅 × 形状」编码一个主题。
 *
 * 设计说明：界面严格黑白灰、无强调色，但聚类结果需要区分多个主题，
 * 纯灰阶在散点图上不足以两两辨识，因此叠加形状编码（圆 / 方 / 三角 / 菱形）。
 * 这是功能性编码（区分数据），不属于装饰性色彩。
 *
 * 卡片与散点图共用同一套编码，用户看到卡片上的标记即可在图上找到对应主题。
 */
export function TopicMarker({
  shape,
  color,
  size = 12,
  className,
}: {
  shape: TopicShape;
  color: string;
  size?: number;
  className?: string;
}) {
  const c = size / 2;
  const inset = size * 0.08;
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      {shape === "circle" ? <circle cx={c} cy={c} r={c - inset} fill={color} /> : null}
      {shape === "square" ? (
        <rect
          x={inset}
          y={inset}
          width={size - inset * 2}
          height={size - inset * 2}
          fill={color}
        />
      ) : null}
      {shape === "triangle" ? (
        <polygon
          points={`${c},${inset} ${size - inset},${size - inset} ${inset},${size - inset}`}
          fill={color}
        />
      ) : null}
      {shape === "diamond" ? (
        <polygon
          points={`${c},${inset} ${size - inset},${c} ${c},${size - inset} ${inset},${c}`}
          fill={color}
        />
      ) : null}
    </svg>
  );
}
