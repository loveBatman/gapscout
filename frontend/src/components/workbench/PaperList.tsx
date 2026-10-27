import { ExternalLink, Quote } from "lucide-react";
import type { PaperBrief } from "../../types";
import { cn, formatNumber, sourceLabel } from "../../lib/utils";

export function PaperList({
  papers,
  activeTopicId,
  limit = 60,
}: {
  papers: PaperBrief[];
  activeTopicId: number | null;
  limit?: number;
}) {
  const visible =
    activeTopicId === null
      ? papers.slice(0, limit)
      : papers.filter((paper) => paper.topic_id === activeTopicId).slice(0, limit);

  if (visible.length === 0) {
    return (
      <p className="px-5 py-8 text-center text-caption text-content-3">
        当前筛选条件下没有文献
      </p>
    );
  }

  return (
    <ul className="divide-y divide-line-1">
      {visible.map((paper) => (
        <li key={paper.uid} className="px-5 py-3 transition-colors hover:bg-surface-1">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <a
                href={paper.url}
                target="_blank"
                rel="noreferrer"
                className="group flex items-start gap-1.5 text-caption font-medium leading-snug text-content-2 transition-colors hover:text-accent-600"
              >
                <span className="line-clamp-2">{paper.title}</span>
                <ExternalLink
                  size={11}
                  className="mt-1 shrink-0 text-content-4 group-hover:text-accent-600"
                />
              </a>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-micro text-content-3">
                <span className="num font-medium text-content-1">{paper.year ?? "-"}</span>
                <span>{paper.venue ?? "未标注来源"}</span>
                <span className="rounded bg-surface-2 px-1.5 py-0.5">
                  {sourceLabel(paper.source)}
                </span>
                {paper.authors.length > 0 ? (
                  <span className="truncate">
                    {paper.authors.slice(0, 3).join(", ")}
                    {paper.authors.length > 3 ? " 等" : ""}
                  </span>
                ) : null}
              </div>
              {paper.abstract ? (
                <p className="mt-1.5 line-clamp-2 text-micro leading-relaxed text-content-3">
                  {paper.abstract}
                </p>
              ) : null}
            </div>
            <div className="shrink-0 text-right">
              <div className={cn("num text-caption font-semibold", "text-content-2")}>
                {formatNumber(paper.citation_count)}
              </div>
              <div className="mt-0.5 flex items-center gap-1 text-micro text-content-4">
                <Quote size={9} />
                引用
              </div>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}
