import { useMemo, useState } from "react";
import { BookOpen, Download, ExternalLink, FileText, ShieldAlert } from "lucide-react";
import { STAGE_SEQUENCE_REVIEW, type ReviewResult, type ReviewSection } from "../types";
import { useTaskRunner } from "../lib/useTaskRunner";
import { cn } from "../lib/utils";
import { DirectionForm } from "../components/workbench/DirectionForm";
import { PageHeader } from "../components/layout/PageHeader";
import { EmptyState, Panel, PanelHeader } from "../components/ui/primitives";
import { ProgressPanel } from "../components/ui/ProgressPanel";
import { SkeletonPanel } from "../components/ui/Skeleton";

const EXAMPLES = [
  "retrieval augmented generation",
  "multimodal large language model inference",
  "graph neural network for molecules",
];

export function Review() {
  const [activeIndex, setActiveIndex] = useState(0);
  const runner = useTaskRunner<ReviewResult>("review");

  const running = runner.status === "running";
  const result = runner.result;
  const outline = runner.outline;

  /**
   * 章节列表。
   *
   * 增量数据按事件类型分流，但事件类型只能保证「契约」、不能保证载荷真的完整——
   * 这里作为最后一道关卡做形态校验：只接受同时具备 title 与 content 字符串的项。
   * 宁可少渲染一节，也不能让一页崩掉（曾因异构载荷读到 undefined 而整页白屏）。
   */
  const sections = useMemo<ReviewSection[]>(() => {
    const raw = result?.sections ?? runner.partials;
    return raw.filter(isReviewSection);
  }, [result, runner.partials]);

  const references = result?.references ?? [];
  const verification = result?.verification ?? {};
  const generationMode = result?.stats?.generation_mode ?? "structured";
  const active = sections[Math.min(activeIndex, Math.max(0, sections.length - 1))];

  return (
    <main className="mx-auto w-full max-w-[2200px] px-6 pb-10 pt-24 3xl:px-10 4xl:px-14">
      <PageHeader
        title="综述生成与校验"
        description="自动梳理主题脉络，逐句标注引用来源并校验引用是否成立"
      />
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[clamp(340px,26%,440px)_minmax(0,1fr)]">
        <div className="space-y-5 xl:sticky xl:top-24 xl:space-y-6 xl:self-start 3xl:space-y-7">
          <Panel variant="glass">
            <PanelHeader title="输入方向" icon={<BookOpen size={16} />} />
            <div className="px-5 py-4">
              <DirectionForm
                onSubmit={runner.run}
                running={running}
                label="综述方向"
                placeholder="例如：retrieval augmented generation"
                examples={EXAMPLES}
                submitLabel="生成综述草稿"
              />
            </div>
          </Panel>

          <ProgressPanel
            stage={runner.stage}
            progress={runner.progress}
            logs={runner.logs}
            running={running}
            sequence={STAGE_SEQUENCE_REVIEW}
            failed={runner.status === "failed"}
            error={runner.error}
          />

          {result ? (
            <Panel variant="glass">
              <PanelHeader title="引用校验" subtitle="防幻觉的最后一道闸门" icon={<ShieldAlert size={16} />} />
              <div className="space-y-2.5 px-5 py-4">
                <VerifyRow label="总句数" value={String(verification.total_sentences ?? 0)} />
                <VerifyRow label="带引用" value={String(verification.cited_sentences ?? 0)} />
                <VerifyRow label="已核查" value={String(verification.checked ?? 0)} />
                <VerifyRow
                  label="通过率"
                  value={
                    verification.semantic_check_skipped
                      ? "未执行语义校验"
                      : `${Math.round(Number(verification.pass_rate ?? 0) * 100)}%`
                  }
                  tone={verification.semantic_check_skipped ? "warn" : "ok"}
                />
                {verification.semantic_check_skipped ? (
                  <p className="rounded-lg border border-warn/25 bg-warn/[0.05] px-3 py-2 text-micro leading-relaxed text-warn">
                    当前未配置语言模型，仅完成引用编号与覆盖检查。配置模型后将逐句判断所引论文是否真的支持该论断。
                  </p>
                ) : null}
                {Array.isArray(verification.unresolved) && verification.unresolved.length > 0 ? (
                  <div>
                    <p className="text-micro text-content-4">待核实断言</p>
                    <ul className="mt-1.5 space-y-1.5">
                      {(verification.unresolved as Record<string, string>[]).slice(0, 3).map((item, index) => (
                        <li
                          key={index}
                          className="rounded-md border-l-2 border-warn/40 bg-surface-1 py-1.5 pl-2.5 text-micro leading-relaxed text-content-3"
                        >
                          {item.text?.slice(0, 110)}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            </Panel>
          ) : null}
        </div>

        <div className="space-y-5 xl:space-y-6 3xl:space-y-7">
          {runner.status === "idle" ? (
            <Panel>
              <EmptyState
                icon={<BookOpen size={20} />}
                title="把检索到的文献整理成可用的综述草稿"
                description="系统会规划大纲、分节撰写，并为每一句断言标注来源、校验引用是否成立。未配置模型时退化为结构化文献梳理，只做原文摘录，不生成无法溯源的自由行文。"
              />
            </Panel>
          ) : null}

          {running && sections.length === 0 && outline.length === 0 ? (
            <SkeletonPanel lines={6} />
          ) : null}

          {/* 大纲先于正文就绪：先展示章节骨架，让"正在写第几节"可见 */}
          {outline.length > 0 && sections.length === 0 ? (
            <Panel>
              <PanelHeader
                title="章节大纲"
                subtitle="大纲已规划完成，正文撰写中，将逐节填充"
                icon={<FileText size={16} />}
              />
              <ol className="space-y-1 px-5 py-4">
                {outline.map((title, index) => (
                  <li key={`${title}-${index}`} className="flex items-start gap-3 text-caption">
                    <span className="num mt-0.5 text-micro text-content-4">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <span className="text-content-2">{title}</span>
                  </li>
                ))}
              </ol>
            </Panel>
          ) : null}

          {sections.length > 0 ? (
            <>
              <Panel>
                <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
                  <div>
                    <h2 className="text-subheading text-content-1">
                      {result?.title ?? "综述草稿（生成中）"}
                    </h2>
                    <p className="mt-1 text-micro text-content-4">
                      {sections.length} 节 · {references.length} 篇参考文献 · 生成模式{" "}
                      {generationMode === "generated" ? "AI 撰写" : "结构化梳理"}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <ExportButton
                      label="Markdown"
                      disabled={!result}
                      onClick={() =>
                        result && download(`${result.title}.md`, toMarkdown(result))
                      }
                    />
                    <ExportButton
                      label="BibTeX"
                      disabled={!result}
                      onClick={() => result && download("references.bib", result.bibtex)}
                    />
                  </div>
                </div>
              </Panel>

              <div className="grid grid-cols-1 gap-5 lg:grid-cols-[clamp(180px,14%,240px)_minmax(0,1fr)] 2xl:grid-cols-[clamp(180px,14%,240px)_minmax(0,1fr)_clamp(240px,18%,340px)]">
                <Panel className="lg:self-start">
                  <PanelHeader title="大纲" />
                  <nav className="py-2">
                    {sections.map((section, index) => (
                      <button
                        key={`${section.title}-${index}`}
                        type="button"
                        onClick={() => setActiveIndex(index)}
                        className={cn(
                          "flex w-full items-start gap-2 px-4 py-2.5 text-left text-caption transition-colors",
                          index === activeIndex
                            ? "bg-accent-50 font-medium text-accent-700"
                            : "text-content-3 hover:bg-surface-1 hover:text-content-1",
                        )}
                      >
                        <span className="num mt-0.5 text-micro text-content-4">
                          {String(index + 1).padStart(2, "0")}
                        </span>
                        <span className="line-clamp-2 leading-snug">{section.title}</span>
                      </button>
                    ))}
                  </nav>
                </Panel>

                <Panel className="lg:self-start">
                  {active ? (
                    <>
                      <PanelHeader
                        title={active.title}
                        subtitle={
                          active.mode === "structured"
                            ? "结构化文献梳理（未启用自由行文）"
                            : "AI 撰写正文"
                        }
                        icon={<FileText size={15} />}
                      />
                      <div className="px-6 py-5">
                        <div className="space-y-3.5 text-body leading-[1.9] text-content-2">
                          {renderWithCitations(active.content)}
                        </div>
                      </div>
                    </>
                  ) : null}
                </Panel>

                {result ? (
                  <Panel className="hidden 2xl:block 2xl:self-start">
                    <PanelHeader
                      title="参考文献"
                      subtitle={`${references.length} 篇`}
                      icon={<BookOpen size={15} />}
                    />
                    <ul className="max-h-[560px] overflow-y-auto py-2">
                      {references.slice(0, 40).map((reference) => (
                        <li key={reference.index} className="px-4 py-2">
                          <a
                            href={reference.url}
                            target="_blank"
                            rel="noreferrer"
                            className="group flex items-start gap-2 text-micro leading-snug text-content-3 transition-colors hover:text-accent-600"
                          >
                            <span className="num shrink-0 text-content-4">
                              [{reference.index}]
                            </span>
                            <span className="line-clamp-2">{reference.title}</span>
                            <ExternalLink
                              size={10}
                              className="mt-0.5 shrink-0 text-content-4 group-hover:text-accent-600"
                            />
                          </a>
                        </li>
                      ))}
                    </ul>
                  </Panel>
                ) : null}
              </div>
            </>
          ) : null}
        </div>
      </div>
    </main>
  );
}

/**
 * 章节形态校验。
 *
 * 只接受同时具备 title 与 content 字符串的对象。
 * 这是增量数据进入渲染层前的关卡——后端若再次在同一事件类型下推送异构载荷，
 * 不完整的项会被丢弃而不是让整页崩溃。
 */
function isReviewSection(value: unknown): value is ReviewSection {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<ReviewSection>;
  return typeof candidate.title === "string" && typeof candidate.content === "string";
}

function VerifyRow({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "ok" | "warn";
}) {
  const tones: Record<string, string> = {
    default: "text-content-1",
    ok: "text-ok",
    warn: "text-warn",
  };
  return (
    <div className="flex items-center justify-between">
      <span className="text-caption text-content-3">{label}</span>
      <span className={cn("num text-caption font-semibold", tones[tone])}>{value}</span>
    </div>
  );
}

function ExportButton({
  label,
  onClick,
  disabled,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex items-center gap-1.5 rounded-lg border border-line-1 px-3 py-1.5 text-micro font-medium transition-colors",
        disabled
          ? "cursor-not-allowed text-content-4"
          : "text-content-2 hover:border-content-1 hover:text-content-1",
      )}
    >
      <Download size={12} />
      {label}
    </button>
  );
}

/**
 * 把正文里的 [n] 渲染成可辨识的引用角标。
 *
 * 参数声明为 unknown 并在内部收敛：正文来自增量数据，无法保证一定是字符串，
 * 早期版本直接对可能为 undefined 的值调用 split 导致整页崩溃。
 */
function renderWithCitations(content: unknown) {
  const text = typeof content === "string" ? content : "";
  const parts = text.split(/(\[\d+(?:\s*,\s*\d+)*\])/g);
  return parts.map((part, index) => {
    const match = /^\[(\d+(?:\s*,\s*\d+)*)\]$/.exec(part);
    if (!match) return <span key={index}>{part}</span>;
    return (
      <sup
        key={index}
        className="mx-0.5 rounded bg-surface-2 px-1 py-0.5 font-mono text-[10px] font-semibold text-content-1"
      >
        {match[1]}
      </sup>
    );
  });
}

function toMarkdown(result: ReviewResult): string {
  const lines = [`# ${result.title}`, ""];
  for (const section of result.sections) {
    lines.push(`## ${section.title}`, "", section.content, "");
  }
  lines.push("## 参考文献", "");
  for (const reference of result.references) {
    lines.push(`[${reference.index}] ${reference.title}. ${reference.year ?? ""} ${reference.url}`);
  }
  lines.push("", "```bibtex", result.bibtex, "```");
  return lines.join("\n");
}

function download(filename: string, content: string) {
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
