import { useState } from "react";
import {
  ChevronDown,
  ExternalLink,
  Gauge,
  Lightbulb,
  Link2,
  ShieldAlert,
  TrendingUp,
} from "lucide-react";
import type { GapOut } from "../../types";
import { cn } from "../../lib/utils";
import { Chip } from "../ui/primitives";

// 三路信号用三个不同色相区分：卡片上常并排出现，同色会让「证据来自哪一路」难以一眼分辨
const SIGNAL_LABELS: Record<string, { text: string; tone: "accent" | "cyan" | "violet" }> = {
  A: { text: "文献自述", tone: "accent" },
  B: { text: "方法迁移", tone: "cyan" },
  C: { text: "图谱结构", tone: "violet" },
};

export function OpportunityCard({
  gap,
  index,
  delay = 0,
}: {
  gap: GapOut;
  index: number;
  /** 入场动画延迟（毫秒），用于列表错峰出现 */
  delay?: number;
}) {
  const [expanded, setExpanded] = useState(index === 0);

  return (
    <article
      style={delay ? { animationDelay: `${delay}ms` } : undefined}
      className="panel panel-hover animate-fade-up overflow-hidden"
    >
      <header className="flex items-start gap-3 px-5 py-4">
        <span className="num mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-caption font-medium text-content-2">
          {String(index + 1).padStart(2, "0")}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-body font-medium leading-snug text-content-1">{gap.title}</h3>
          <p className="mt-2 text-caption leading-relaxed text-content-3">{gap.description}</p>

          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            {(gap.signals ?? []).map((signal) => {
              const meta = SIGNAL_LABELS[signal] ?? { text: signal, tone: "default" as const };
              return (
                <Chip key={signal} tone={meta.tone}>
                  {meta.text}
                </Chip>
              );
            })}
            {gap.confidence !== null && gap.confidence !== undefined ? (
              <Chip tone="ok">
                <TrendingUp size={10} />
                置信 {Math.round(gap.confidence * 100)}%
              </Chip>
            ) : null}
            {gap.novelty !== null && gap.novelty !== undefined ? (
              <Chip>
                <Gauge size={10} />
                新颖度 {gap.novelty.toFixed(2)}
              </Chip>
            ) : null}
            <Chip>
              <Link2 size={10} />
              {(gap.evidence ?? []).length} 条证据
            </Chip>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          aria-expanded={expanded}
          aria-label={expanded ? "收起详情" : "展开详情"}
          className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-content-3 transition-colors hover:bg-surface-2 hover:text-content-1"
        >
          <ChevronDown size={15} className={cn("transition-transform", expanded && "rotate-180")} />
        </button>
      </header>

      {expanded ? (
        <div className="animate-fade-up space-y-4 border-t border-line-1 px-5 py-4">
          {gap.value_note || gap.feasibility || gap.risk ? (
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
              <InsightBlock
                icon={<Lightbulb size={13} />}
                label="价值判断"
                text={gap.value_note}
                tone="brand"
              />
              <InsightBlock
                icon={<Gauge size={13} />}
                label="可行性"
                text={gap.feasibility}
                tone="cyan"
              />
              <InsightBlock
                icon={<ShieldAlert size={13} />}
                label="风险与反驳"
                text={gap.risk}
                tone="warn"
              />
            </div>
          ) : null}

          <div>
            <p className="text-micro font-medium text-content-4">支撑证据（可跳转原文）</p>
            <ul className="mt-2 space-y-2.5">
              {(gap.evidence ?? []).map((item) => (
                <li
                  key={`${item.uid}-${item.quote?.slice(0, 24) ?? ""}`}
                  className="rounded-lg border border-line-1 bg-surface-1 px-3.5 py-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                      className="group flex items-start gap-1.5 text-caption font-medium leading-snug text-content-2 transition-colors hover:text-accent-600"
                    >
                      <span className="line-clamp-2">{item.title}</span>
                      <ExternalLink
                        size={11}
                        className="mt-1 shrink-0 text-content-4 group-hover:text-accent-600"
                      />
                    </a>
                    <div className="flex shrink-0 items-center gap-1.5">
                      {item.level ? <Chip tone="ok">{item.level}</Chip> : null}
                      <span className="num text-micro text-content-4">{item.year ?? "-"}</span>
                    </div>
                  </div>
                  {item.quote ? (
                    <p className="mt-2 border-l-2 border-line-2 pl-3 text-micro italic leading-relaxed text-content-3">
                      {item.quote}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}
    </article>
  );
}

function InsightBlock({
  icon,
  label,
  text,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  text?: string | null;
  tone: "brand" | "cyan" | "warn";
}) {
  const tones: Record<string, string> = {
    // 三块是三类不同性质的信息，用色相区分：主色 / 青色 / 告警色
    brand: "text-accent-700",
    cyan: "text-topic-2",
    warn: "text-warn",
  };
  return (
    <div className="rounded-lg border border-line-1 bg-surface-1 px-3.5 py-3">
      <p className={cn("flex items-center gap-1.5 text-micro font-medium", tones[tone])}>
        {icon}
        {label}
      </p>
      <p className="mt-1.5 text-micro leading-relaxed text-content-3">
        {text ?? "未配置语言模型，此项需要模型分析后生成。"}
      </p>
    </div>
  );
}
