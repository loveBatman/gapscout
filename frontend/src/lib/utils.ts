import { twMerge } from "tailwind-merge";

/** 合并 Tailwind 类名，后写的同类样式覆盖先写的 */
export function cn(...classes: (string | false | null | undefined)[]): string {
  return twMerge(classes.filter(Boolean).join(" "));
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  if (value >= 10000) return `${(value / 10000).toFixed(1)}w`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
}

export function formatSeconds(value: unknown): string {
  const seconds = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(seconds)) return "-";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

/** arXiv / OpenAlex / S2 的来源展示名 */
export const SOURCE_LABELS: Record<string, string> = {
  arxiv: "arXiv",
  openalex: "OpenAlex",
  s2: "Semantic Scholar",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

/**
 * 主题标记的「颜色 + 形状」双重编码。
 *
 * 颜色承担主要辨识（8 个分散色相，一眼分清研究方向），
 * 形状作为第二重编码——既照顾色觉障碍用户，
 * 也让「同一张卡片」与「散点图上的点」即使颜色接近也能对上。
 *
 * 这是功能性编码（区分数据），不是装饰性色彩。
 */
export type TopicShape = "circle" | "square" | "triangle" | "diamond";

/** 8 色分类板，色相分散，取 600 阶左右的深度以保证白底上的可读性 */
const TOPIC_COLORS = [
  "#2563EB", // 蓝
  "#0891B2", // 青
  "#059669", // 绿
  "#D97706", // 琥珀
  "#E11D48", // 玫红
  "#7C3AED", // 紫
  "#4F46E5", // 靛
  "#64748B", // 石板灰
];

const TOPIC_SHAPES: TopicShape[] = ["circle", "square", "triangle", "diamond"];

/** 主题颜色：按编号稳定分配，保证图表与卡片中同一主题颜色一致 */
export function topicColor(index: number): string {
  return TOPIC_COLORS[index % TOPIC_COLORS.length];
}

/** 主题形状：与颜色组合使用，编号 0-3 为圆形、4-7 为方形，以此类推 */
export function topicShape(index: number): TopicShape {
  return TOPIC_SHAPES[Math.floor(index / TOPIC_COLORS.length) % TOPIC_SHAPES.length];
}
