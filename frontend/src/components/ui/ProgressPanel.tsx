import { AlertCircle } from "lucide-react";
import type { Stage, StageItem } from "../../types";
import { StageTimeline, type StageLogEntry } from "../workbench/StageTimeline";
import { Panel } from "./primitives";

/** 统一的进度面板：左侧栏各页面共用 */
export function ProgressPanel({
  stage,
  progress,
  logs,
  running,
  failed,
  error,
  sequence,
}: {
  stage: Stage | null;
  progress: number;
  logs: StageLogEntry[];
  running: boolean;
  failed: boolean;
  error: string | null;
  /** 该模块的阶段序列，由页面传入（四类分析的阶段构成不同） */
  sequence: StageItem[];
}) {
  return (
    <>
      <Panel variant="glass">
        <div className="px-5 py-4">
          <StageTimeline
            currentStage={stage}
            progress={progress}
            logs={logs}
            running={running}
            failed={failed}
            sequence={sequence}
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
    </>
  );
}
