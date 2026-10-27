import { useState } from "react";
import {
  AlertTriangle,
  Compass,
  Database,
  FileSearch,
  Lightbulb,
  Loader2,
  Scale,
  Sparkles,
} from "lucide-react";
import { STAGE_SEQUENCE_FEASIBILITY, type FeasibilityResult } from "../types";
import { useTaskRunner } from "../lib/useTaskRunner";
import { cn } from "../lib/utils";
import { PageHeader } from "../components/layout/PageHeader";
import { Panel, PanelHeader, Chip, EmptyState } from "../components/ui/primitives";
import { ProgressPanel } from "../components/ui/ProgressPanel";
import { SkeletonPanel } from "../components/ui/Skeleton";

const EXAMPLES = [
  "用扩散模型做多模态大模型的推理加速",
  "面向长文档的检索增强生成幻觉抑制方法",
  "代码大模型的仓库级缺陷定位",
];

const LEVEL_META: Record<string, { label: string; tone: string; ring: string }> = {
  high: { label: "新颖性高", tone: "text-ok", ring: "border-ok/40 bg-ok/[0.05]" },
  medium: { label: "部分重叠", tone: "text-warn", ring: "border-warn/40 bg-warn/[0.05]" },
  low: { label: "撞车风险高", tone: "text-danger", ring: "border-danger/40 bg-danger/[0.05]" },
  unknown: { label: "无法判定", tone: "text-content-3", ring: "border-line-1 bg-surface-1" },
};

export function Feasibility() {
  const [idea, setIdea] = useState("");
  const runner = useTaskRunner<FeasibilityResult>("feasibility");

  const running = runner.status === "running";
  const result = runner.result;
  const canSubmit = idea.trim().length >= 4 && !running;
  const meta = LEVEL_META[result?.novelty_level ?? "unknown"] ?? LEVEL_META.unknown;

  return (
    <main className="mx-auto w-full max-w-[2200px] px-6 pb-10 pt-24 3xl:px-10 4xl:px-14">
      <PageHeader
        title="选题可行性评估"
        description="在动手之前确认这个方向有没有人做过，以及你的差异点在哪里"
      />
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[clamp(360px,27%,460px)_minmax(0,1fr)]">
        <div className="space-y-5 xl:sticky xl:top-24 xl:space-y-6 xl:self-start 3xl:space-y-7">
          <Panel variant="glass">
            <PanelHeader title="描述你的想法" icon={<Scale size={16} />} />
            <div className="space-y-3 px-5 py-4">
              <label className="block">
                <span className="text-micro font-medium text-content-3">研究想法</span>
                <textarea
                  value={idea}
                  onChange={(event) => setIdea(event.target.value)}
                  disabled={running}
                  rows={4}
                  placeholder="用一句话描述你想做什么，例如：用扩散模型做多模态大模型的推理加速"
                  className="mt-2 w-full resize-none rounded-xl border border-line-1 bg-surface-0 px-3.5 py-3 text-body leading-relaxed text-content-1 placeholder:text-content-4 transition-colors focus:border-content-1 focus:outline-none disabled:cursor-not-allowed"
                />
              </label>

              <div className="flex flex-wrap gap-1.5">
                <span className="text-micro text-content-4">示例</span>
                {EXAMPLES.map((example) => (
                  <button
                    key={example}
                    type="button"
                    disabled={running}
                    onClick={() => setIdea(example)}
                    className="rounded-full border border-line-1 bg-surface-0 px-2.5 py-1 text-micro text-content-3 transition-colors hover:border-content-1 hover:text-content-1 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {example}
                  </button>
                ))}
              </div>

              <button
                type="button"
                onClick={() => canSubmit && runner.run(idea.trim())}
                disabled={!canSubmit}
                className={cn(
                  // 胶囊形：与次级按钮、Chip 形成形状语言上的重要性区分
                  "flex w-full items-center justify-center gap-2 rounded-full px-4 py-3 text-body font-medium transition-colors",
                  canSubmit
                    ? "bg-accent-600 text-white hover:bg-accent-700"
                    : "cursor-not-allowed bg-surface-2 text-content-4",
                )}
              >
                {running ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    正在评估……
                  </>
                ) : (
                  <>
                    <FileSearch size={16} />
                    评估这个选题
                  </>
                )}
              </button>
            </div>
          </Panel>

          <ProgressPanel
            stage={runner.stage}
            progress={runner.progress}
            logs={runner.logs}
            running={running}
            sequence={STAGE_SEQUENCE_FEASIBILITY}
            failed={runner.status === "failed"}
            error={runner.error}
          />
        </div>

        <div className="space-y-5 xl:space-y-6 3xl:space-y-7">
          {runner.status === "idle" ? (
            <Panel>
              <EmptyState
                icon={<Scale size={20} />}
                title="在动手之前，先确认这个方向有没有人做过"
                description="开题阶段最常见的风险是投入数月后发现有高度相似的已发表工作。本功能会检索真实文献、计算语义相似度分布、列出最相似的工作及差异点，并给出切入角度建议。"
              />
            </Panel>
          ) : null}

          {running && !result ? <SkeletonPanel lines={4} /> : null}

          {result ? (
            <>
              <Panel className={cn("border", meta.ring)}>
                <div className="flex flex-col gap-4 px-5 py-5 lg:flex-row lg:items-center">
                  <div className="flex items-center gap-5">
                    <div className="text-center">
                      <div className={cn("num text-4xl font-semibold leading-none", meta.tone)}>
                        {result.novelty_score !== null && result.novelty_score !== undefined
                          ? result.novelty_score.toFixed(2)
                          : "--"}
                      </div>
                      <div className="mt-1.5 text-micro text-content-4">新颖性评分</div>
                    </div>
                    <div className="h-14 w-px bg-line-1" />
                    <div>
                      <p className={cn("text-heading", meta.tone)}>{meta.label}</p>
                      <p className="mt-1 text-caption text-content-3">
                        基于 {String((result.stats.pool_size as number) ?? 0)} 篇对比文献
                      </p>
                    </div>
                  </div>
                  <p className="flex-1 text-caption leading-relaxed text-content-3">
                    {result.novelty_basis}
                  </p>
                </div>
                {result.verdict ? (
                  <div className="border-t border-line-1 px-5 py-4">
                    <p className="flex items-start gap-2 text-caption leading-relaxed text-content-2">
                      <Sparkles size={14} className="mt-0.5 shrink-0 text-content-1" />
                      {result.verdict}
                    </p>
                  </div>
                ) : null}
              </Panel>

              <Panel>
                <PanelHeader
                  title="最相似的已有工作"
                  subtitle="逐条比对，明确写出你的差异点——这是开题论证的核心"
                  icon={<FileSearch size={16} />}
                />
                <ul className="divide-y divide-line-1">
                  {result.similar_works.map((work) => (
                    <li key={work.uid} className="px-5 py-3.5">
                      <div className="flex items-start gap-4">
                        <div className="w-20 shrink-0">
                          <div className="num text-caption font-semibold text-content-1">
                            {(work.similarity * 100).toFixed(1)}%
                          </div>
                          <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-3">
                            <div
                              className="h-full rounded-full bg-accent-600"
                              style={{ width: `${Math.min(100, work.similarity * 100)}%` }}
                            />
                          </div>
                        </div>
                        <div className="min-w-0 flex-1">
                          <a
                            href={work.url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-caption font-medium leading-snug text-content-2 transition-colors hover:text-accent-600"
                          >
                            {work.title}
                          </a>
                          <div className="mt-1 flex flex-wrap items-center gap-x-3 text-micro text-content-3">
                            <span className="num font-medium text-content-1">{work.year ?? "-"}</span>
                            <span>{work.venue ?? "未标注来源"}</span>
                          </div>
                          {work.difference_hint ? (
                            <p className="mt-1.5 rounded-md border-l-2 border-line-2 bg-surface-1 py-1.5 pl-3 text-micro leading-relaxed text-content-3">
                              差异：{work.difference_hint}
                            </p>
                          ) : null}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </Panel>

              <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
                <Panel>
                  <PanelHeader title="竞争态势" subtitle="看该方向的活跃程度" icon={<Compass size={16} />} />
                  <div className="space-y-3 px-5 py-4">
                    <MetricRow label="相关文献总量" value={String(result.competition.total ?? 0)} />
                    <MetricRow label="近一年新增" value={String(result.competition.recent_works ?? 0)} />
                    <MetricRow
                      label="平均相似度"
                      value={String(result.competition.mean_similarity ?? "-")}
                    />
                    <MetricRow
                      label="年份跨度"
                      value={`${result.competition.year_from ?? "-"} ~ ${result.competition.year_to ?? "-"}`}
                    />
                    <div className="divide-line" />
                    <p className="text-micro text-content-4">主要发表渠道</p>
                    <div className="flex flex-wrap gap-1.5">
                      {((result.competition.top_venues as { name: string; count: number }[]) ?? [])
                        .slice(0, 4)
                        .map((venue) => (
                          <Chip key={venue.name}>
                            <span className="max-w-[180px] truncate">{venue.name}</span>
                            <span className="num text-content-4">{venue.count}</span>
                          </Chip>
                        ))}
                    </div>
                  </div>
                </Panel>

                <Panel>
                  <PanelHeader
                    title="资源线索"
                    subtitle="做出来能不能验证，取决于数据集与基线是否可得"
                    icon={<Database size={16} />}
                  />
                  <div className="space-y-3 px-5 py-4">
                    <ResourceGroup label="数据集" items={result.resources.datasets_found as string[]} />
                    <ResourceGroup label="开源实现" items={result.resources.open_source_found as string[]} />
                    <ResourceGroup label="评测基准" items={result.resources.benchmarks_found as string[]} />
                    <p className="text-micro text-content-3">{String(result.resources.note ?? "")}</p>
                  </div>
                </Panel>
              </div>

              <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
                <Panel>
                  <PanelHeader title="风险提示" icon={<AlertTriangle size={16} />} />
                  <ul className="space-y-2 px-5 py-4">
                    {result.risks.map((risk) => (
                      <li key={risk} className="flex items-start gap-2 text-caption leading-relaxed text-content-3">
                        <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-warn" />
                        {risk}
                      </li>
                    ))}
                  </ul>
                </Panel>

                <Panel>
                  <PanelHeader title="切入建议" icon={<Lightbulb size={16} />} />
                  <ul className="space-y-2 px-5 py-4">
                    {result.suggestions.map((suggestion) => (
                      <li
                        key={suggestion}
                        className="flex items-start gap-2 text-caption leading-relaxed text-content-3"
                      >
                        <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-content-1" />
                        {suggestion}
                      </li>
                    ))}
                  </ul>
                </Panel>
              </div>
            </>
          ) : null}
        </div>
      </div>
    </main>
  );
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-caption text-content-3">{label}</span>
      <span className="num text-caption font-semibold text-content-1">{value}</span>
    </div>
  );
}

function ResourceGroup({ label, items }: { label: string; items?: string[] }) {
  const list = items ?? [];
  return (
    <div>
      <p className="text-micro text-content-4">
        {label}
        <span className="num ml-2 text-content-4">{list.length}</span>
      </p>
      {list.length === 0 ? (
        <p className="mt-1 text-micro text-content-4">未在摘要中发现相关线索</p>
      ) : (
        <ul className="mt-1 space-y-1">
          {list.slice(0, 3).map((item) => (
            <li key={item} className="truncate text-micro text-content-3" title={item}>
              {item}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
