import { Check, Loader2, Minus, X } from "lucide-react";
import { STAGE_SEQUENCE_EXPLORE, type Stage, type StageItem } from "../../types";
import { cn } from "../../lib/utils";
import { ProgressBar } from "../ui/primitives";

export interface StageLogEntry {
  stage: Stage;
  message: string;
  percent: number;
  at: number;
}

/**
 * 阶段时间线：把"AI 正在做什么"完整暴露给用户。
 *
 * 这是过程可视化的核心组件——传统工具只给一个转圈动画，
 * 这里把查询理解、检索、去重、聚类等每一步的产出都实时呈现出来。
 */
export function StageTimeline({
  currentStage,
  progress,
  logs,
  running,
  failed,
  sequence = STAGE_SEQUENCE_EXPLORE,
}: {
  currentStage: Stage | null;
  progress: number;
  logs: StageLogEntry[];
  running: boolean;
  failed: boolean;
  /** 当前模块的阶段序列：四类分析的阶段构成不同，需由调用方显式传入 */
  sequence?: StageItem[];
}) {
  const activeIndex = sequence.findIndex((item) => item.key === currentStage);
  const latest = logs.length > 0 ? logs[logs.length - 1] : null;

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <span className="text-micro font-medium text-content-4">分析进度</span>
        <span className="num text-caption font-semibold text-content-1">{progress}%</span>
      </div>

      <ProgressBar percent={progress} active={running} />

      <ol className="mt-1 space-y-1">
        {sequence.map((item, index) => {
          const state = resolveState(index, activeIndex, running, failed, currentStage);
          const stageLogs = logs.filter((log) => log.stage === item.key);
          const lastLog = stageLogs.length > 0 ? stageLogs[stageLogs.length - 1] : null;

          return (
            <li
              key={item.key}
              className={cn(
                "flex items-start gap-3 rounded-lg px-2 py-2 transition-colors",
                state === "active" && "bg-accent-50",
              )}
            >
              <StageIcon state={state} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "text-caption font-medium",
                      state === "pending" ? "text-content-4" : "text-content-1",
                    )}
                  >
                    {item.label}
                  </span>
                  {lastLog && state !== "pending" ? (
                    <span className="num truncate text-micro text-content-3">
                      {lastLog.message}
                    </span>
                  ) : null}
                </div>
                {state === "pending" ? (
                  <p className="mt-0.5 text-micro text-content-4">{item.hint}</p>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>

      {latest ? (
        <div className="rounded-lg border border-line-1 bg-surface-1 px-3 py-2.5">
          <p className="text-micro font-medium text-content-4">最新事件</p>
          <p className="mt-1 text-caption text-content-2">{latest.message}</p>
        </div>
      ) : null}
    </div>
  );
}

type StageState = "done" | "active" | "pending" | "failed";

function resolveState(
  index: number,
  activeIndex: number,
  running: boolean,
  failed: boolean,
  currentStage: Stage | null,
): StageState {
  if (failed && index === activeIndex) return "failed";
  if (currentStage === "done") return "done";
  if (activeIndex === -1) {
    // 当前 stage 不在该模块的阶段序列内（通常是序列传错）。
    // 这里全部置灰，而不是把第 0 项伪装成"正在执行"——
    // 阶段错配应当能被一眼看出来，而不是显示一个虚假的进行中状态。
    return "pending";
  }
  if (index < activeIndex) return "done";
  if (index === activeIndex) return running ? "active" : "done";
  return "pending";
}

/**
 * 阶段状态图标。
 *
 * 状态用「符号 + 颜色」表达：
 * 完成 = 实心蓝圆白勾（与进度条同色，表示已完成），进行中 = 浅蓝底蓝色转圈，
 * 失败 = 暗红叉，未开始 = 浅灰短横。
 */
function StageIcon({ state }: { state: StageState }) {
  if (state === "done") {
    return (
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-600 text-white">
        <Check size={12} />
      </span>
    );
  }
  if (state === "active") {
    return (
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-100 text-accent-700">
        <Loader2 size={12} className="animate-spin" />
      </span>
    );
  }
  if (state === "failed") {
    return (
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-danger/10 text-danger">
        <X size={12} />
      </span>
    );
  }
  return (
    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-2 text-content-4">
      <Minus size={12} />
    </span>
  );
}
