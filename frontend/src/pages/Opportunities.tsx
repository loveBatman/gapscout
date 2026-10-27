import { useMemo } from "react";
import {
  Compass,
  GitBranch,
  Layers,
  ScrollText,
  Search,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { STAGE_SEQUENCE_GAP, type GapResult, type GapOut } from "../types";
import { useTaskRunner } from "../lib/useTaskRunner";
import { cn, formatSeconds } from "../lib/utils";
import { DirectionForm } from "../components/workbench/DirectionForm";
import { OpportunityCard } from "../components/opportunity/OpportunityCard";
import { MatrixHeatmap } from "../components/opportunity/MatrixHeatmap";
import { PageHeader } from "../components/layout/PageHeader";
import { EmptyState, Panel, PanelHeader, StatCard } from "../components/ui/primitives";
import { ProgressPanel } from "../components/ui/ProgressPanel";
import { SkeletonPanel } from "../components/ui/Skeleton";

const EXAMPLES = [
  "multimodal large language model inference",
  "retrieval augmented generation",
  "code generation with large language models",
];

const SIGNAL_TITLES: Record<string, string> = {
  A: "信号 A · 文献自述（证据最硬）",
  B: "信号 B · 方法迁移",
  C: "信号 C · 图谱结构",
};

export function Opportunities() {
  const runner = useTaskRunner<GapResult>("opportunities");

  const result = runner.result;
  // 分析未完成时用 SSE 增量推送的机会点即时渲染，让过程可见
  const liveGaps = runner.partials as GapOut[];
  const gaps = result?.gaps ?? liveGaps;
  const running = runner.status === "running";

  const signals = (result?.signals ?? {}) as Record<string, Record<string, unknown>>;
  const stats = useMemo(() => buildStats(result), [result]);

  return (
    <main className="mx-auto w-full max-w-[2200px] px-6 pb-10 pt-24 3xl:px-10 4xl:px-14">
      <PageHeader
        title="研究空白识别"
        description="三路信号交叉验证，找出被反复提及但尚无对应工作的方向"
      />
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[clamp(360px,27%,460px)_minmax(0,1fr)]">
        <div className="space-y-5 xl:sticky xl:top-24 xl:space-y-6 xl:self-start 3xl:space-y-7">
          <Panel variant="glass">
            <PanelHeader title="输入方向" icon={<Compass size={16} />} />
            <div className="px-5 py-4">
              <DirectionForm
                onSubmit={runner.run}
                running={running}
                label="研究方向"
                placeholder="例如：multimodal large language model inference"
                examples={EXAMPLES}
                submitLabel="识别研究空白"
              />
            </div>
          </Panel>

          <ProgressPanel
            stage={runner.stage}
            progress={runner.progress}
            logs={runner.logs}
            running={running}
            sequence={STAGE_SEQUENCE_GAP}
            failed={runner.status === "failed"}
            error={runner.error}
          />

          {result ? (
            <Panel variant="glass">
              <PanelHeader title="三路信号" subtitle="各自独立产出候选后交叉验证" icon={<GitBranch size={16} />} />
              <div className="space-y-3 px-5 py-4">
                <SignalRow
                  label={SIGNAL_TITLES.A}
                  detail={describeFutureWork(signals.future_work)}
                />
                <SignalRow label={SIGNAL_TITLES.B} detail={describeMatrix(signals.matrix)} />
                <SignalRow label={SIGNAL_TITLES.C} detail={describeGraph(signals.graph)} />
              </div>
            </Panel>
          ) : null}
        </div>

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

          {runner.status === "idle" ? (
            <Panel>
              <EmptyState
                icon={<Sparkles size={20} />}
                title="从真实文献中找「没人做过但值得做」的方向"
                description="系统会抓取论文全文，抽取作者自述的局限与未来工作；构建方法-任务矩阵寻找空格；分析引用图谱的结构洞。三路信号交叉验证后才给出机会点，每条都附带原文证据。"
              />
            </Panel>
          ) : null}

          {/* 抓全文与三路信号计算耗时较长，用骨架屏占位 */}
          {running && !result && gaps.length === 0 ? <SkeletonPanel lines={5} /> : null}

          {gaps.length > 0 ? (
            <div>
              <div className="mb-3 flex items-center justify-between">
                <h2 className="flex items-center gap-2 text-subheading text-content-1">
                  <Sparkles size={16} className="text-content-1" />
                  机会点
                  <span className="num text-caption font-normal text-content-4">{gaps.length} 个</span>
                </h2>
                {!result && running ? (
                  <span className="text-micro text-content-4">增量生成中……</span>
                ) : null}
              </div>
              <div className="grid grid-cols-1 items-start gap-4 2xl:grid-cols-2 3xl:gap-5">
                {gaps.map((gap, index) => (
                  <OpportunityCard
                    key={`${gap.title}-${index}`}
                    gap={gap}
                    index={index}
                    delay={Math.min(index, 5) * 55}
                  />
                ))}
              </div>
            </div>
          ) : null}

          {result?.matrix ? (
            <Panel>
              <PanelHeader
                title="方法-任务矩阵"
                subtitle="空格代表该组合尚无工作；邻域活跃的空格代表存在迁移价值"
                icon={<Layers size={16} />}
              />
              <div className="px-5 py-4">
                <MatrixHeatmap matrix={result.matrix} />
              </div>
            </Panel>
          ) : null}

          {result?.topics && result.topics.length > 0 ? (
            <Panel>
              <PanelHeader
                title="相关主题"
                subtitle="本次分析识别出的研究主题，机会点即从中推导"
                icon={<ScrollText size={16} />}
              />
              <div className="flex flex-wrap gap-2 px-5 py-4">
                {result.topics.map((topic, index) => (
                  <span
                    key={`${topic.id}-${topic.label}`}
                    className={cn(
                      "rounded-lg border border-line-1 bg-surface-1 px-3 py-2 text-caption text-content-2",
                      index === 0 && "border-accent-600/40 bg-accent-50 text-accent-700",
                    )}
                  >
                    {topic.label}
                    <span className="num ml-2 text-micro text-content-4">{topic.size}</span>
                  </span>
                ))}
              </div>
            </Panel>
          ) : null}
        </div>
      </div>
    </main>
  );
}

function SignalRow({ label, detail }: { label: string; detail: string }) {
  return (
    <div className="rounded-lg border border-line-1 bg-surface-1 px-3.5 py-2.5">
      <p className="text-micro font-medium text-content-1">{label}</p>
      <p className="mt-1 text-micro leading-relaxed text-content-3">{detail}</p>
    </div>
  );
}

function describeFutureWork(signal?: Record<string, unknown>): string {
  if (!signal) return "尚未产出";
  const clusters = Array.isArray(signal.clusters) ? signal.clusters.length : 0;
  const statements = signal.statements_total ?? 0;
  const levels = (signal.fulltext_levels ?? {}) as Record<string, number>;
  const levelText = Object.entries(levels)
    .map(([key, value]) => `${key} ${value} 篇`)
    .join(" / ");
  return `扫描 ${signal.papers_scanned ?? 0} 篇全文（${levelText || "无"}），抽取 ${statements} 条未来工作陈述，聚出 ${clusters} 个方向簇`;
}

function describeMatrix(signal?: Record<string, unknown>): string {
  if (!signal) return "尚未产出";
  const gaps = Array.isArray(signal.gap_cells) ? signal.gap_cells.length : 0;
  const tasks = Array.isArray(signal.tasks) ? signal.tasks.length : 0;
  const methods = Array.isArray(signal.methods) ? signal.methods.length : 0;
  const coverage = Number(signal.extraction_coverage ?? 0);
  return `${tasks} 个任务 × ${methods} 个方法，抽取覆盖率 ${(coverage * 100).toFixed(1)}%，检出 ${gaps} 个潜在空格`;
}

function describeGraph(signal?: Record<string, unknown>): string {
  if (!signal) return "尚未产出";
  const holes = Array.isArray(signal.structural_holes) ? signal.structural_holes.length : 0;
  const emerging = Array.isArray(signal.emerging_communities)
    ? signal.emerging_communities.length
    : 0;
  return `引用图 ${signal.n_nodes ?? 0} 节点 / ${signal.n_edges ?? 0} 边，${signal.n_communities ?? 0} 个社区，检出 ${holes} 个结构洞、${emerging} 个新兴簇`;
}

function buildStats(result: GapResult | null) {
  if (!result) return [];
  const stats = result.stats;
  const cluster = (stats.cluster ?? {}) as Record<string, unknown>;
  const futureWork = (stats.fulltext_levels ?? {}) as Record<string, number>;

  return [
    {
      label: "机会点",
      value: String(result.gaps.length),
      hint: `候选 ${stats.candidates ?? 0} 个经批判后保留`,
      tone: "brand" as const,
      icon: <Sparkles size={14} />,
    },
    {
      label: "语料规模",
      value: String(stats.corpus_size ?? 0),
      hint: `主题 ${cluster.n_clusters ?? 0} 个`,
      tone: "cyan" as const,
      icon: <ScrollText size={14} />,
    },
    {
      label: "全文证据",
      value: String(futureWork.L1 ?? 0),
      hint: `L1 结构化全文，共扫描 ${futureWork.L1 ?? 0} 篇`,
      tone: "ok" as const,
      icon: <Search size={14} />,
    },
    {
      label: "总耗时",
      value: formatSeconds(stats.elapsed_seconds),
      hint: `嵌入后端 ${String(stats.embed_backend ?? "-")}`,
      tone: "warn" as const,
      icon: <TrendingUp size={14} />,
    },
  ];
}
