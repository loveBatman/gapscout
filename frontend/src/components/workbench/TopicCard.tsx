import { ExternalLink, FileText, TrendingUp } from "lucide-react";
import type { TopicOut } from "../../types";
import { cn, topicColor, topicShape } from "../../lib/utils";
import { Chip } from "../ui/primitives";
import { TopicMarker } from "./TopicMarker";

export function TopicCard({
  topic,
  index,
  active,
  onSelect,
  delay = 0,
}: {
  topic: TopicOut;
  index: number;
  active: boolean;
  onSelect: () => void;
  /** 入场动画延迟（毫秒），用于列表错峰出现 */
  delay?: number;
}) {
  const color = topicColor(index);
  const shape = topicShape(index);
  const rising = (topic.trend_slope ?? 0) > 0;

  return (
    <article
      style={delay ? { animationDelay: `${delay}ms` } : undefined}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
      role="button"
      tabIndex={0}
      aria-pressed={active}
      className={cn(
        "panel panel-hover animate-fade-up cursor-pointer p-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-600/30",
        active && "border-accent-600",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <TopicMarker shape={shape} color={color} size={11} className="mt-1 shrink-0" />
          <div className="min-w-0">
            <h3 className="truncate text-subheading leading-snug text-content-1">
              {topic.label}
            </h3>
            {/* 主题标记的颜色与散点图一致，卡片与图上可互相对照 */}
            {topic.core_problem ? (
              <p className="mt-1.5 line-clamp-3 text-caption leading-relaxed text-content-3">
                {topic.core_problem}
              </p>
            ) : null}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="num text-xl font-semibold leading-none text-content-1">
            {topic.size}
          </div>
          <div className="mt-1 text-micro text-content-4">篇文献</div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {topic.year_from && topic.year_to ? (
          <Chip>
            {topic.year_from} - {topic.year_to}
          </Chip>
        ) : null}
        {rising ? (
          <Chip tone="ok">
            <TrendingUp size={10} />
            升温
          </Chip>
        ) : null}
        {(topic.methods ?? []).slice(0, 3).map((method) => (
          <Chip key={method}>
            {method}
          </Chip>
        ))}
      </div>

      {(topic.keywords ?? []).length > 0 ? (
        <div className="mt-3 border-t border-line-1 pt-3">
          <p className="text-micro text-content-4">高频关键词</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {(topic.keywords ?? []).slice(0, 6).map((keyword) => (
              <span
                key={keyword}
                className="rounded-md bg-surface-2 px-2 py-0.5 text-micro text-content-3"
              >
                {keyword}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {(topic.top_papers ?? []).length > 0 ? (
        <div className="mt-3 border-t border-line-1 pt-3">
          <p className="flex items-center gap-1.5 text-micro text-content-4">
            <FileText size={11} />
            代表论文
          </p>
          <ul className="mt-1.5 space-y-1.5">
            {(topic.top_papers ?? []).slice(0, 3).map((paper) => (
              <li key={paper.uid}>
                <a
                  href={paper.url}
                  target="_blank"
                  rel="noreferrer"
                  onClick={(event) => event.stopPropagation()}
                  className="group flex items-start justify-between gap-2 text-caption leading-snug text-content-2 transition-colors hover:text-accent-600"
                >
                  <span className="line-clamp-2">{paper.title}</span>
                  <ExternalLink
                    size={11}
                    className="mt-1 shrink-0 text-content-4 transition-colors group-hover:text-accent-600"
                  />
                </a>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </article>
  );
}
