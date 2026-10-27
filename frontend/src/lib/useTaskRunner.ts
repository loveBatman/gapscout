import type { Stage } from "../types";
import { useModuleRunner, type ModuleKey, type RunStatus } from "./runStore";
import type { StageLogEntry } from "../components/workbench/StageTimeline";

export type { RunStatus };

export interface TaskRunnerState<T> {
  status: RunStatus;
  stage: Stage | null;
  progress: number;
  logs: StageLogEntry[];
  partials: unknown[];
  /** 章节标题列表（仅综述模块会填充），用于在正文撰写开始前先渲染大纲骨架 */
  outline: string[];
  result: T | null;
  error: string | null;
  run: (input: string) => void;
  reset: () => void;
}

/**
 * 任务运行器的类型友好封装。
 *
 * 状态本身存放在 RunStoreProvider（跨页面保留），这里只负责把
 * 「模块槽位」映射为该模块的结果类型，使页面调用处不必做类型断言。
 */
export function useTaskRunner<T>(moduleKey: ModuleKey): TaskRunnerState<T> {
  return useModuleRunner<T>(moduleKey);
}
