import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { Stage } from "../types";
import {
  asExploreResult,
  asFeasibilityResult,
  asGapResult,
  asReviewResult,
  createExplore,
  createFeasibility,
  createGapAnalysis,
  createReview,
  getTask,
  type TaskCreated,
} from "./api";
import { openTaskStream } from "./sse";
import type { StageLogEntry } from "../components/workbench/StageTimeline";

export type ModuleKey = "workbench" | "opportunities" | "feasibility" | "review";
export type RunStatus = "idle" | "running" | "done" | "failed";

export interface ModuleState {
  status: RunStatus;
  stage: Stage | null;
  progress: number;
  logs: StageLogEntry[];
  partials: unknown[];
  /**
   * 章节标题列表，仅综述模块使用。
   *
   * 与 partials 分开存放的原因：大纲与逐节正文是**两种不同的消费品**——
   * 前者用于在生成早期渲染章节骨架，后者用于渲染正文。曾经两者共用同一事件类型
   * 混进同一个数组，渲染层读到大纲对象上不存在的 content 字段即抛错，整页白屏。
   */
  outline: string[];
  result: unknown;
  error: string | null;
}

const MODULE_KEYS: ModuleKey[] = ["workbench", "opportunities", "feasibility", "review"];
const MAX_LOGS = 40;

interface ModuleConfig {
  create: (input: string) => Promise<TaskCreated>;
  parse: (value: unknown) => unknown;
  /** 需要增量收集进 partials 的事件类型（渲染正文/卡片） */
  partialType?: string;
  /** 需要增量收集进 outline 的事件类型，载荷为章节标题列表 */
  outlineType?: string;
}

const MODULE_CONFIG: Record<ModuleKey, ModuleConfig> = {
  workbench: { create: createExplore, parse: asExploreResult, partialType: "topic" },
  opportunities: { create: createGapAnalysis, parse: asGapResult, partialType: "opportunity" },
  feasibility: { create: createFeasibility, parse: asFeasibilityResult },
  review: {
    create: createReview,
    parse: asReviewResult,
    partialType: "section",
    outlineType: "outline",
  },
};

function emptyState(): ModuleState {
  return {
    status: "idle",
    stage: null,
    progress: 0,
    logs: [],
    partials: [],
    outline: [],
    result: null,
    error: null,
  };
}

function emptyStates(): Record<ModuleKey, ModuleState> {
  return {
    workbench: emptyState(),
    opportunities: emptyState(),
    feasibility: emptyState(),
    review: emptyState(),
  };
}

interface RunStoreValue {
  states: Record<ModuleKey, ModuleState>;
  run: (key: ModuleKey, input: string) => void;
  reset: (key: ModuleKey) => void;
  clearAll: () => void;
}

const RunStoreContext = createContext<RunStoreValue | null>(null);

/**
 * 跨页面运行状态层。
 *
 * 解决的问题：原先页面用条件渲染维护，切走即卸载，useState 全部销毁，
 * 于是「探索工作台做完分析 -> 切到机会点 -> 切回来」内容就没了。
 *
 * 设计要点：
 * - 四个模块各自一个槽位，状态提到 Provider，页面组件卸载不再影响数据
 * - **SSE 取消函数由 Provider 持有**，页面卸载不关闭连接，
 *   因此切换分页面时任务继续在后台跑完，切回即可看到结果
 * - clearAll 供登录/登出调用，满足「只有重新登录时才清空」的要求
 */
export function RunStoreProvider({ children }: { children: ReactNode }) {
  const [states, setStates] = useState<Record<ModuleKey, ModuleState>>(emptyStates);
  const cancels = useRef<Partial<Record<ModuleKey, (() => void) | null>>>({});

  const patch = useCallback((key: ModuleKey, changes: Partial<ModuleState>) => {
    setStates((prev) => ({ ...prev, [key]: { ...prev[key], ...changes } }));
  }, []);

  const finish = useCallback(
    async (key: ModuleKey, taskId: string) => {
      const task = await getTask(taskId).catch((error: Error) => {
        console.error("[task]", error);
        return null;
      });
      if (!task) return;
      if (task.status === "failed") {
        patch(key, { status: "failed", error: task.error ?? "分析过程发生未知错误" });
        return;
      }
      patch(key, {
        result: MODULE_CONFIG[key].parse(task.result),
        partials: [],
        status: "done",
        stage: "done",
        progress: 100,
      });
    },
    [patch],
  );

  const run = useCallback(
    (key: ModuleKey, input: string) => {
      cancels.current[key]?.();
      patch(key, {
        status: "running",
        stage: "understanding",
        progress: 0,
        logs: [],
        partials: [],
        outline: [],
        result: null,
        error: null,
      });

      const config = MODULE_CONFIG[key];
      config
        .create(input)
        .then((created) => {
          cancels.current[key] = openTaskStream(created.task_id, {
            onProgress: (payload) => {
              setStates((prev) => {
                const current = prev[key];
                return {
                  ...prev,
                  [key]: {
                    ...current,
                    stage: payload.stage,
                    progress: payload.percent,
                    logs: [
                      ...current.logs,
                      {
                        stage: payload.stage,
                        message: payload.message,
                        percent: payload.percent,
                        at: Date.now(),
                      },
                    ].slice(-MAX_LOGS),
                  },
                };
              });
            },
            onPartial: (payload) => {
              // 大纲走独立字段：它的载荷是标题列表，与正文章节结构不同，
              // 混入同一数组会让渲染层读到缺失字段
              if (config.outlineType && payload.type === config.outlineType) {
                const titles = (payload.payload as { titles?: unknown } | null)?.titles;
                if (!Array.isArray(titles)) return;
                setStates((prev) => ({
                  ...prev,
                  [key]: {
                    ...prev[key],
                    outline: titles.filter((title): title is string => typeof title === "string"),
                  },
                }));
                return;
              }
              if (config.partialType && payload.type !== config.partialType) return;
              setStates((prev) => ({
                ...prev,
                [key]: { ...prev[key], partials: [...prev[key].partials, payload.payload] },
              }));
            },
            onDone: () => {
              void finish(key, created.task_id);
            },
            onFailed: (payload) => {
              patch(key, { status: "failed", error: payload.message ?? "分析失败" });
            },
          });
        })
        .catch((error: Error) => {
          console.error("[create task]", error);
          patch(key, { status: "failed", error: error.message });
        });
    },
    [finish, patch],
  );

  const reset = useCallback((key: ModuleKey) => {
    cancels.current[key]?.();
    cancels.current[key] = null;
    setStates((prev) => ({ ...prev, [key]: emptyState() }));
  }, []);

  const clearAll = useCallback(() => {
    for (const key of MODULE_KEYS) {
      cancels.current[key]?.();
      cancels.current[key] = null;
    }
    setStates(emptyStates());
  }, []);

  const value = useMemo<RunStoreValue>(
    () => ({ states, run, reset, clearAll }),
    [states, run, reset, clearAll],
  );

  return <RunStoreContext.Provider value={value}>{children}</RunStoreContext.Provider>;
}

export function useRunStore(): RunStoreValue {
  const context = useContext(RunStoreContext);
  if (!context) {
    throw new Error("useRunStore 必须在 RunStoreProvider 内部使用");
  }
  return context;
}

/** 读取单个模块的运行状态与操作入口 */
export function useModuleRunner<T>(key: ModuleKey) {
  const store = useRunStore();
  const state = store.states[key];

  return useMemo(
    () => ({
      ...state,
      result: state.result as T | null,
      run: (input: string) => store.run(key, input),
      reset: () => store.reset(key),
    }),
    [state, store, key],
  );
}
