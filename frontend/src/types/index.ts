// 与后端 app/schemas 对齐的类型定义，前端只依赖这里的契约

export type Stage =
  | "queued"
  | "understanding"
  | "retrieving"
  | "dedup"
  | "filtering"
  | "embedding"
  | "clustering"
  | "naming"
  | "extracting"
  | "analyzing"
  | "criticizing"
  | "generating"
  | "verifying"
  | "done"
  | "failed";

export interface EvidenceRef {
  uid: string;
  title: string;
  year?: number | null;
  venue?: string | null;
  url: string;
  quote?: string | null;
  level?: string | null;
  signal?: string | null;
}

export interface TopicOut {
  id?: number | null;
  label: string;
  summary?: string | null;
  core_problem?: string | null;
  keywords: string[];
  methods: string[];
  size: number;
  trend_slope?: number | null;
  year_from?: number | null;
  year_to?: number | null;
  top_papers: EvidenceRef[];
}

export interface PaperBrief {
  uid: string;
  title: string;
  year?: number | null;
  venue?: string | null;
  authors: string[];
  citation_count?: number | null;
  url: string;
  abstract?: string | null;
  source: string;
  topic_id?: number | null;
  /** 2D 投影坐标：用于领域全景散点图 */
  x?: number | null;
  y?: number | null;
}

export interface TimelineNode {
  year: number;
  label: string;
  method?: string | null;
  paper?: EvidenceRef | null;
}

export interface ExploreResult {
  task_id: string;
  query: string;
  terms: string[];
  stats: Record<string, unknown>;
  topics: TopicOut[];
  timeline: TimelineNode[];
  trend: { year: number; count: number }[];
  papers: PaperBrief[];
}

export interface TaskStatus {
  task_id: string;
  kind: string;
  query: string;
  status: "pending" | "running" | "done" | "failed";
  stage?: Stage | null;
  progress: number;
  message?: string | null;
  error?: string | null;
  stats: Record<string, unknown>;
  result?: ExploreResult | GapResult | FeasibilityResult | ReviewResult | null;
}

// ---------- M2 研究空白识别 ----------

export interface GapOut {
  title: string;
  description: string;
  signals: string[];
  evidence: EvidenceRef[];
  value_note?: string | null;
  feasibility?: string | null;
  risk?: string | null;
  novelty?: number | null;
  confidence?: number | null;
}

export interface MatrixView {
  tasks: string[];
  methods: string[];
  matrix: number[][];
  gap_cells: Record<string, unknown>[];
}

export interface GapResult {
  task_id: string;
  query: string;
  terms: string[];
  stats: Record<string, unknown>;
  topics: TopicOut[];
  gaps: GapOut[];
  signals: Record<string, unknown>;
  matrix?: MatrixView | null;
}

// ---------- M3 选题可行性评估 ----------

export interface SimilarWork {
  uid: string;
  title: string;
  year?: number | null;
  venue?: string | null;
  url: string;
  similarity: number;
  difference_hint?: string | null;
}

export interface FeasibilityResult {
  task_id: string;
  idea: string;
  parsed: Record<string, unknown>;
  novelty_score?: number | null;
  novelty_level: string;
  novelty_basis?: string | null;
  similar_works: SimilarWork[];
  competition: Record<string, unknown>;
  resources: Record<string, unknown>;
  risks: string[];
  suggestions: string[];
  verdict?: string | null;
  stats: Record<string, unknown>;
}

// ---------- M5 综述生成 ----------

export interface ReviewSection {
  title: string;
  content: string;
  citations: number[];
  mode: string;
}

export interface ReviewResult {
  task_id: string;
  direction: string;
  title: string;
  sections: ReviewSection[];
  references: {
    index: number;
    title: string;
    year?: number | null;
    venue?: string | null;
    url: string;
    authors?: string[];
  }[];
  bibtex: string;
  verification: Record<string, unknown>;
  stats: Record<string, unknown>;
}

export type ViewKey = "workbench" | "opportunities" | "feasibility" | "review";

export interface HealthStatus {
  status: string;
  app: string;
  version: string;
  database: string;
  llm_configured: boolean;
}

export interface ProgressPayload {
  stage: Stage;
  message: string;
  percent: number;
  source?: string | null;
  count?: number | null;
}

export interface PartialPayload {
  /**
   * 增量事件的类型。每种类型必须对应**唯一一种**载荷结构——
   * 同一类型下混推异构数据会让按类型分流的渲染层读到缺失字段而抛错。
   * outline（章节标题列表）与 section（逐节正文）就是因此必须分开的。
   */
  type: "terms" | "topic" | "relevance" | "paper" | "opportunity" | "section" | "outline";
  payload: unknown;
}

export interface StageItem {
  key: Stage;
  label: string;
  hint: string;
}

/**
 * 分析阶段的中文文案与顺序，驱动进度时间线渲染。
 *
 * 四类分析的阶段构成**各不相同**（后端各 service 推送的 stage 值独立定义）：
 * 探索链路有「三级去重 / 质量过滤」，空白识别有「证据抽取 / 信号计算 / 价值批判」，
 * 综述生成有「大纲规划 / 分节撰写 / 引用校验」。
 *
 * 因此必须由各页面显式传入自己的序列——若共用一套，遇到列表外的 stage 值会使
 * 匹配下标恒为 -1，阶段列表就会卡在第一项不动（详见 StageTimeline 的兜底分支）。
 */

/** M1 领域探索 */
export const STAGE_SEQUENCE_EXPLORE: StageItem[] = [
  { key: "understanding", label: "查询理解", hint: "解析方向并生成检索术语" },
  { key: "retrieving", label: "多源检索", hint: "arXiv / OpenAlex / Semantic Scholar" },
  { key: "dedup", label: "三级去重", hint: "标题 / DOI / 模糊匹配" },
  { key: "filtering", label: "质量过滤", hint: "年份分层与引用密度" },
  { key: "embedding", label: "语义嵌入", hint: "生成论文向量" },
  { key: "clustering", label: "主题聚类", hint: "UMAP 降维 + HDBSCAN" },
  { key: "naming", label: "主题命名", hint: "c-TF-IDF + 语义润色" },
  { key: "done", label: "分析完成", hint: "生成领域全景" },
];

/** M2 研究空白识别 */
export const STAGE_SEQUENCE_GAP: StageItem[] = [
  { key: "understanding", label: "查询理解", hint: "解析方向并生成检索术语" },
  { key: "retrieving", label: "多源检索", hint: "并发抓取真实文献" },
  { key: "embedding", label: "语义嵌入", hint: "生成论文向量并过滤噪声" },
  { key: "clustering", label: "主题聚类", hint: "确定领域内的研究方向" },
  { key: "extracting", label: "证据抽取", hint: "全文、未来工作陈述与引用关系" },
  { key: "analyzing", label: "信号计算", hint: "方法-任务矩阵与引用图谱" },
  { key: "criticizing", label: "价值批判", hint: "剔除没价值所以没人做的伪机会" },
  { key: "done", label: "分析完成", hint: "生成机会点卡片" },
];

/** M3 选题可行性评估 */
export const STAGE_SEQUENCE_FEASIBILITY: StageItem[] = [
  { key: "understanding", label: "想法解析", hint: "拆解任务、方法与场景" },
  { key: "retrieving", label: "定向检索", hint: "检索最相似的已有工作" },
  { key: "embedding", label: "语义比对", hint: "计算与已有工作的相似度分布" },
  { key: "analyzing", label: "新颖性评估", hint: "撞车风险与竞争态势" },
  { key: "generating", label: "报告生成", hint: "差异点分析与切入建议" },
  { key: "done", label: "评估完成", hint: "生成开题决策报告" },
];

/** M5 综述生成 */
export const STAGE_SEQUENCE_REVIEW: StageItem[] = [
  { key: "understanding", label: "查询理解", hint: "解析综述主题" },
  { key: "retrieving", label: "文献检索", hint: "构建参考文献池" },
  { key: "embedding", label: "语义嵌入", hint: "生成论文向量" },
  { key: "clustering", label: "主题聚类", hint: "确定综述的章节维度" },
  { key: "analyzing", label: "大纲规划", hint: "设计逻辑递进的章节结构" },
  { key: "generating", label: "分节撰写", hint: "基于文献证据撰写正文" },
  { key: "verifying", label: "引用校验", hint: "逐句核查引用是否成立" },
  { key: "done", label: "生成完成", hint: "导出综述与参考文献" },
];

/** M1 序列的别名，供默认值使用 */
export const STAGE_SEQUENCE = STAGE_SEQUENCE_EXPLORE;
