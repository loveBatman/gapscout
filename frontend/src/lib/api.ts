import type {
  ExploreResult,
  FeasibilityResult,
  GapResult,
  HealthStatus,
  PaperBrief,
  ReviewResult,
  TaskStatus,
} from "../types";

const API_BASE = "/api/v1";

export interface TaskCreated {
  task_id: string;
  status: string;
  stream_url: string;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    return response
      .json()
      .catch(() => ({ detail: `请求失败（HTTP ${response.status}）` }))
      .then((body: { detail?: string }) => {
        throw new Error(body?.detail ?? `请求失败（HTTP ${response.status}）`);
      });
  }
  return response.json() as Promise<T>;
}

export function getHealth(): Promise<HealthStatus> {
  return requestJson<HealthStatus>("/health");
}

export function createExplore(direction: string): Promise<TaskCreated> {
  return requestJson("/explore", {
    method: "POST",
    body: JSON.stringify({ direction }),
  });
}

export function getTask(taskId: string): Promise<TaskStatus> {
  return requestJson<TaskStatus>(`/tasks/${taskId}`);
}

export function listTasks(limit = 12): Promise<TaskStatus[]> {
  return requestJson<TaskStatus[]>(`/tasks?limit=${limit}`);
}

export function createGapAnalysis(direction: string): Promise<TaskCreated> {
  return requestJson("/gaps", { method: "POST", body: JSON.stringify({ direction }) });
}

export function createFeasibility(idea: string): Promise<TaskCreated> {
  return requestJson("/feasibility", { method: "POST", body: JSON.stringify({ idea }) });
}

export function createReview(direction: string): Promise<TaskCreated> {
  return requestJson("/review", { method: "POST", body: JSON.stringify({ direction }) });
}

export function asExploreResult(value: unknown): ExploreResult | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<ExploreResult>;
  if (!Array.isArray(candidate.topics)) return null;
  return candidate as ExploreResult;
}

export function asGapResult(value: unknown): GapResult | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<GapResult>;
  if (!Array.isArray(candidate.gaps)) return null;
  return candidate as GapResult;
}

export function asFeasibilityResult(value: unknown): FeasibilityResult | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<FeasibilityResult>;
  if (!Array.isArray(candidate.similar_works)) return null;
  return candidate as FeasibilityResult;
}

export function asReviewResult(value: unknown): ReviewResult | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<ReviewResult>;
  if (!Array.isArray(candidate.sections)) return null;
  return candidate as ReviewResult;
}

export function sortPapersByCitations(papers: PaperBrief[]): PaperBrief[] {
  return [...papers].sort((a, b) => (b.citation_count ?? 0) - (a.citation_count ?? 0));
}
