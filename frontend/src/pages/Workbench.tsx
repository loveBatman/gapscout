import { useMemo, useState } from "react";
import { AlertCircle, BarChart3, Compass, Layers, ScrollText, Timer, TrendingUp } from "lucide-react";
import {
  STAGE_SEQUENCE_EXPLORE,
  type ExploreResult,
  type HealthStatus,
  type TopicOut,
} from "../types";
import { useTaskRunner } from "../lib/useTaskRunner";
import { cn, formatSeconds } from "../lib/utils";
import { PageHeader } from "../components/layout/PageHeader";
import { EmptyState, Panel, PanelHeader, StatCard } from "../components/ui/primitives";
import { SkeletonPanel } from "../components/ui/Skeleton";
import { DirectionForm } from "../components/workbench/DirectionForm";
import { StageTimeline } from "../components/workbench/StageTimeline";
import { TopicCard } from "../components/workbench/TopicCard";
import { TrendChart, TopicScatter } from "../components/workbench/Charts";
import { PaperList } from "../components/workbench/PaperList";

export function Workbench({ health }: { health: HealthStatus | null }) {
  const [activeTopicId, setActiveTopicId] = useState<number | null>(null);
  // 运行状态与 SSE 连接由 RunStoreProvider 持有：切换分页面时本组件会卸载，
  // 但任务继续在后台执行完毕，切回即可看到结果（此前是整页清空）。
  const runner = useTaskRunner<ExploreResult>("workbench");

  const { status, stage, progress, logs, error } = runner;
  const start = runner.run;
  const result = runner.result;
  // 分析未完成时用 SSE 增量推送的主题即时渲染，让过程可见
  const topics = result?.topics ?? ((runner.partials as TopicOut[]) || []);
  const stats = useMemo(() => buildStatCards(result), [result]);
  const running = status === "running";

  return (
    <main className="mx-auto w-full max-w-[2200px] px-6 pb-10 pt-24 3xl:px-10 4xl:px-14">
        <PageHeader
          title="领域全景探索"
          description="检索真实文献并归纳主题簇，给出该方向的研究全景与代表工作"
        />
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-[clamp(360px,27%,460px)_minmax(0,1fr)]">
          {/* ---------- 左栏：输入与过程 ---------- */}
          <div className="space-y-5 xl:sticky xl:top-24 xl:space-y-6 xl:self-start 3xl:space-y-7">
            <Panel variant="glass">
              <PanelHeader title="输入方向" icon={<Compass size={16} />} />
              <div className="px-5 py-4">
                <DirectionForm onSubmit={start} running={running} />
              </div>
            </Panel>

            <Panel variant="glass">
              <div className="px-5 py-4">
                <StageTimeline
                  currentStage={stage}
                  progress={progress}
                  logs={logs}
                  running={running}
                  sequence={STAGE_SEQUENCE_EXPLORE}
                  failed={status === "failed"}
                />
              </div>
            </Panel>

            {error ? (
              <div className="animate-fade-up rounded-xl border border-danger/30 bg-danger/[0.05] px-4 py-3">
                <div className="flex items-start gap-2">
                  <AlertCircle size={15} className="mt-0.5 shrink-0 text-danger" />
                  <div>
                    <p className="text-caption font-semibold text-danger">分析失败</p>
                    <p className="mt-1 break-all text-micro text-content-2">{error}</p>
                  </div>
                </div>
              </div>
            ) : null}
          </div>

          {/* ---------- 右栏：结果 ---------- */}
          <div className="space-y-5 xl:space-y-6 3xl:space-y-7">
            {stats.length > 0 ? (
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4 3xl:gap-5">
                {stats.map((item) => (
                  <StatCard
                    key={item.label}
                    label={item.label}
                    value={item.value}
                    hint={item.hint}
                    tone={item.tone}
                    icon={item.icon}
                  />
                ))}
              </div>
            ) : null}

            {status === "idle" && !result ? (
              <Panel>
                <EmptyState
                  icon={<ScrollText size={20} />}
                  title="用真实文献回答「这个方向我该做什么」"
                  description="系统会从 arXiv、OpenAlex、Semantic Scholar 检索真实论文，经三级去重、质量分层、语义聚类后给出主题全景，全部结论均可溯源到原文。"
                />
              </Panel>
            ) : null}

            {/* 分析进行中且尚无结果时用骨架屏占位，避免空白等待 */}
            {running && !result && topics.length === 0 ? <SkeletonPanel lines={4} /> : null}

            {topics.length > 0 ? (
              <Panel>
                <PanelHeader
                  title="领域全景"
                  subtitle="每篇论文在语义空间中的位置，灰阶深浅与形状代表主题簇，距离越近越相似"
                  icon={<Layers size={16} />}
                  action={
                    topics.length > 0 ? (
                      <span className="text-micro text-content-4">
                        {result ? `${result.papers.length} 篇参与投影` : "增量生成中"}
                      </span>
                    ) : null
                  }
                />
                <div className="px-4 py-4">
                  <TopicScatter papers={result?.papers ?? []} topics={topics} />
                </div>
              </Panel>
            ) : null}

            {topics.length > 0 ? (
              <div>
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="flex items-center gap-2 text-subheading text-content-1">
                    <BarChart3 size={16} className="text-content-1" />
                    主题簇
                    <span className="num text-caption font-normal text-content-4">
                      {topics.length} 个
                    </span>
                  </h2>
                  <button
                    type="button"
                    onClick={() => setActiveTopicId(null)}
                    className={cn(
                      "rounded-lg px-2.5 py-1 text-micro font-medium transition-colors",
                      activeTopicId === null
                        ? "bg-accent-50 text-accent-700"
                        : "text-content-3 hover:text-content-1",
                    )}
                  >
                    全部文献
                  </button>
                </div>
                <div className="grid grid-cols-1 gap-4 2xl:grid-cols-2 3xl:gap-5 4xl:grid-cols-3">
                  {topics.map((topic, index) => (
                    <TopicCard
                      key={`${topic.id}-${topic.label}`}
                      topic={topic}
                      index={index}
                      delay={Math.min(index, 7) * 45}
                      active={activeTopicId === topic.id}
                      onSelect={() =>
                        setActiveTopicId((prev) => (prev === topic.id ? null : (topic.id ?? null)))
                      }
                    />
                  ))}
                </div>
              </div>
            ) : null}

            {result && result.trend.length > 0 ? (
              <Panel>
                <PanelHeader
                  title="研究热度趋势"
                  subtitle="按年份统计的文献产出量，用于判断领域是否处于上升期"
                  icon={<TrendingUp size={16} />}
                />
                <div className="px-4 py-4">
                  <TrendChart data={result.trend} />
                </div>
              </Panel>
            ) : null}

            {result && result.papers.length > 0 ? (
              <Panel>
                <PanelHeader
                  title="文献列表"
                  subtitle={
                    activeTopicId === null
                      ? "按质量分排序的代表文献，点击标题跳转原文"
                      : "当前主题下的文献，点击标题跳转原文"
                  }
                  icon={<ScrollText size={16} />}
                />
                <PaperList papers={result.papers} activeTopicId={activeTopicId} />
              </Panel>
            ) : null}
        </div>
      </div>
    </main>
  );
}

interface StatCardModel {
  label: string;
  value: string;
  hint: string;
  tone: "brand" | "cyan" | "ok" | "warn";
  icon: React.ReactNode;
}

function buildStatCards(result: ExploreResult | null): StatCardModel[] {
  if (!result) return [];
  const stats = result.stats as Record<string, unknown>;
  const dedup = (stats.dedup ?? {}) as Record<string, number>;
  const cluster = (stats.cluster ?? {}) as Record<string, unknown>;

  return [
    {
      label: "主题簇",
      value: String(result.topics.length),
      hint: `聚类 ${String(cluster.reducer ?? "-")} · 噪声 ${String(cluster.noise ?? 0)}`,
      tone: "brand",
      icon: <Layers size={14} />,
    },
    {
      label: "有效文献",
      value: String(result.papers.length),
      hint: `去重移除 ${dedup.removed ?? 0} 篇`,
      tone: "cyan",
      icon: <ScrollText size={14} />,
    },
    {
      label: "总耗时",
      value: formatSeconds(stats.elapsed_seconds),
      hint: `嵌入后端 ${String(stats.embed_backend ?? "-")}`,
      tone: "ok",
      icon: <Timer size={14} />,
    },
    {
      label: "数据源",
      value: String(Object.keys((stats.per_source ?? {}) as Record<string, number>).length),
      hint: Object.entries((stats.per_source ?? {}) as Record<string, number>)
        .map(([key, value]) => `${key} ${value}`)
        .join(" · ") || "单源模式",
      tone: "warn",
      icon: <Compass size={14} />,
    },
  ];
}
