import { useMemo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import type { PaperBrief, TopicOut } from "../../types";
import { topicColor, topicShape, type TopicShape } from "../../lib/utils";
import { TopicMarker } from "./TopicMarker";

/** 图表统一的浅色轴线与网格配色 */
const AXIS_LINE = "#DDDEE1";
const GRID_LINE = "#F1F1F1";
const TICK_COLOR = "#767881";

export function TrendChart({ data }: { data: { year: number; count: number }[] }) {
  if (data.length === 0) {
    return <Placeholder text="暂无年份数据" />;
  }
  return (
    // 画布高度随断点放大：固定高度在大屏上会把曲线压扁，浪费横向空间
    <div className="h-[210px] 3xl:h-[260px] 4xl:h-[300px]">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 10, right: 12, bottom: 0, left: -22 }}>
        <defs>
          {/* 主数据用强调蓝的透明渐变表达面积，轴线与网格保持灰阶不与数据争视觉 */}
          <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#2563EB" stopOpacity={0.22} />
            <stop offset="100%" stopColor="#2563EB" stopOpacity={0.01} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={GRID_LINE} vertical={false} />
        <XAxis
          dataKey="year"
          stroke={AXIS_LINE}
          tick={{ fill: TICK_COLOR, fontSize: 11 }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          stroke={AXIS_LINE}
          tick={{ fill: TICK_COLOR, fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          width={46}
        />
        <Tooltip content={<TrendTooltip />} cursor={{ stroke: "rgba(37,99,235,0.28)" }} />
        <Area
          type="monotone"
          dataKey="count"
          stroke="#2563EB"
          strokeWidth={1.6}
          fill="url(#trendFill)"
          dot={{ r: 2.5, fill: "#2563EB", strokeWidth: 0 }}
          activeDot={{ r: 4, fill: "#2563EB" }}
        />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

interface ScatterPoint {
  x: number;
  y: number;
  title: string;
  year?: number | null;
  citations?: number | null;
  /** 该点所属主题的形状编码，由分组序号决定 */
  markerShape?: TopicShape;
}

/**
 * 领域全景散点图：每篇论文在语义空间中的位置。
 * 距离越近代表研究内容越相似。
 *
 * 主题区分方式：**颜色 × 形状**双重编码（8 色分类板 + 圆/方/三角/菱形）。
 * 颜色承担主要辨识，形状作为第二重编码，兼顾色觉障碍并避免与卡片标记产生色差误读。
 * 这是功能性编码（区分数据），不是装饰性色彩。
 */
export function TopicScatter({
  papers,
  topics,
}: {
  papers: PaperBrief[];
  topics: TopicOut[];
}) {
  const grouped = useMemo(() => {
    const map = new Map<number, ScatterPoint[]>();
    for (const paper of papers) {
      // 用 typeof 收窄，同时排除 null 与 undefined
      if (
        typeof paper.x !== "number" ||
        typeof paper.y !== "number" ||
        typeof paper.topic_id !== "number"
      ) {
        continue;
      }
      const bucket = map.get(paper.topic_id) ?? [];
      bucket.push({
        x: paper.x,
        y: paper.y,
        title: paper.title,
        year: paper.year,
        citations: paper.citation_count,
      });
      map.set(paper.topic_id, bucket);
    }
    return map;
  }, [papers]);

  const labels = useMemo(() => {
    const map = new Map<number, string>();
    for (const topic of topics) {
      if (topic.id !== null && topic.id !== undefined) map.set(topic.id, topic.label);
    }
    return map;
  }, [topics]);

  const entries = useMemo(() => [...grouped.entries()], [grouped]);

  if (entries.length === 0) {
    return <Placeholder text="暂无投影坐标数据" />;
  }

  return (
    <div className="space-y-3">
      {/* 散点是二维投影，画布越大点越分散、越可读，因此随断点明显放大 */}
      <div className="h-[330px] 3xl:h-[400px] 4xl:h-[460px]">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 12, right: 16, bottom: 4, left: -24 }}>
          <CartesianGrid stroke={GRID_LINE} />
          <XAxis
            type="number"
            dataKey="x"
            tick={false}
            axisLine={{ stroke: AXIS_LINE }}
            tickLine={false}
          />
          <YAxis
            type="number"
            dataKey="y"
            tick={false}
            axisLine={{ stroke: AXIS_LINE }}
            tickLine={false}
          />
          <ZAxis range={[40, 40]} />
          <Tooltip content={<ScatterTooltip />} cursor={{ strokeDasharray: "3 3" }} />
          {entries.map(([topicId, points], index) => {
            const shape = topicShape(index);
            return (
              <Scatter
                key={topicId}
                name={labels.get(topicId) ?? `主题 ${topicId}`}
                data={points.map((point) => ({ ...point, markerShape: shape }))}
                fill={topicColor(index)}
                fillOpacity={0.85}
                shape={renderTopicPoint}
                isAnimationActive={false}
              />
            );
          })}
          </ScatterChart>
        </ResponsiveContainer>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-2 px-1">
        {entries.map(([topicId], index) => (
          <span key={topicId} className="flex items-center gap-1.5 text-micro text-content-3">
            <TopicMarker shape={topicShape(index)} color={topicColor(index)} size={10} />
            {labels.get(topicId) ?? `主题 ${topicId}`}
          </span>
        ))}
      </div>
    </div>
  );
}

interface TopicPointProps {
  cx?: number;
  cy?: number;
  fill?: string;
  payload?: ScatterPoint;
}

/**
 * 散点形状渲染器。
 *
 * recharts 的 Scatter 通过 shape 属性接受自定义渲染函数，
 * 这里按数据点携带的 markerShape 绘制四种几何形状，
 * 与颜色组合形成主题的双重编码。
 */
function renderTopicPoint(props: TopicPointProps) {
  const { cx, cy, fill } = props;
  const shape = props.payload?.markerShape ?? "circle";
  if (typeof cx !== "number" || typeof cy !== "number") return <g />;

  const r = 4.5;
  const color = fill ?? "#000000";
  const attrs = { fill: color, stroke: "#FFFFFF", strokeWidth: 0.7 };

  if (shape === "square") {
    return <rect x={cx - r} y={cy - r} width={r * 2} height={r * 2} {...attrs} />;
  }
  if (shape === "triangle") {
    return (
      <polygon
        points={`${cx},${cy - r} ${cx + r},${cy + r * 0.75} ${cx - r},${cy + r * 0.75}`}
        {...attrs}
      />
    );
  }
  if (shape === "diamond") {
    return (
      <polygon
        points={`${cx},${cy - r} ${cx + r},${cy} ${cx},${cy + r} ${cx - r},${cy}`}
        {...attrs}
      />
    );
  }
  return <circle cx={cx} cy={cy} r={r} {...attrs} />;
}

function NearRows({ rows }: { rows: { label: string; value: string }[] }) {
  return (
    <div className="space-y-0.5">
      {rows.map((row) => (
        <div key={row.label} className="flex items-baseline justify-between gap-4">
          <span className="text-micro text-content-3">{row.label}</span>
          <span className="num text-caption text-content-1">{row.value}</span>
        </div>
      ))}
    </div>
  );
}

interface TooltipPayloadItem {
  payload?: Record<string, unknown>;
}

function TrendTooltip({ active, payload, label }: { active?: boolean; payload?: TooltipPayloadItem[]; label?: string | number }) {
  if (!active || !payload || payload.length === 0) return null;
  const count = Number(payload[0]?.payload?.count ?? 0);
  return (
    <div className="panel px-3 py-2 shadow-subtle">
      <NearRows rows={[{ label: String(label), value: `${count} 篇` }]} />
    </div>
  );
}

function ScatterTooltip({ active, payload }: { active?: boolean; payload?: TooltipPayloadItem[] }) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0]?.payload as ScatterPoint | undefined;
  if (!point) return null;
  return (
    <div className="panel max-w-xs px-3 py-2 shadow-subtle">
      <p className="text-caption font-medium leading-snug text-content-1">{point.title}</p>
      <div className="mt-1.5">
        <NearRows
          rows={[
            { label: "年份", value: point.year ? String(point.year) : "-" },
            { label: "引用", value: point.citations !== null && point.citations !== undefined ? String(point.citations) : "-" },
          ]}
        />
      </div>
    </div>
  );
}

function Placeholder({ text }: { text: string }) {
  return (
    <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-line-2 text-caption text-content-3">
      {text}
    </div>
  );
}
