import type { PartialPayload, ProgressPayload } from "../types";

const API_BASE = "/api/v1";

export interface StreamHandlers {
  onProgress?: (payload: ProgressPayload) => void;
  onPartial?: (payload: PartialPayload) => void;
  onDone?: (payload: Record<string, unknown>) => void;
  onFailed?: (payload: { message?: string }) => void;
}

/**
 * 打开任务事件流。
 *
 * 后端按 SSE 协议推送 progress / partial / done / failed 四类事件，
 * 其中 partial 用于增量渲染（主题卡片随分析进度逐个出现）。
 * 返回一个取消函数，组件卸载时调用以释放连接。
 */
export function openTaskStream(taskId: string, handlers: StreamHandlers): () => void {
  const source = new EventSource(`${API_BASE}/tasks/${taskId}/stream`);

  source.addEventListener("progress", (event) => {
    handlers.onProgress?.(JSON.parse((event as MessageEvent).data) as ProgressPayload);
  });

  source.addEventListener("partial", (event) => {
    handlers.onPartial?.(JSON.parse((event as MessageEvent).data) as PartialPayload);
  });

  source.addEventListener("done", (event) => {
    handlers.onDone?.(JSON.parse((event as MessageEvent).data) as Record<string, unknown>);
    source.close();
  });

  source.addEventListener("failed", (event) => {
    handlers.onFailed?.(JSON.parse((event as MessageEvent).data) as { message?: string });
    source.close();
  });

  source.onerror = () => {
    // 服务端主动结束或网络中断都会触发；由调用方通过任务状态接口兜底刷新
    console.error("[sse] 事件流中断，请检查后端服务是否可用");
    source.close();
  };

  return () => source.close();
}
