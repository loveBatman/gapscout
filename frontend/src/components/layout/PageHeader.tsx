import type { ReactNode } from "react";

/**
 * 页面级页头。
 *
 * 作用：在内容之前建立「当前在哪、这一页能做什么」的认知，并给页面一个明确的
 * 视觉起点。此前页面直接进入内容、所有面板平铺，缺少「页」这一层的层级。
 *
 * 与面板标题的分工（去重规则）：
 *   页头说明「这一页是做什么的」，面板标题说明「这个模块要你做什么」。
 *   两者极易写成同一句话，因此引入页头时必须同步清理面板里重复的副标题。
 *
 * 标题字号用 clamp 随视口轻微放大（1.8vw / 24-32px）：它是页面的视觉重心，
 * 在超大屏上跟随画布放大能避免「小标题漂浮在大空白里」。正文与小字保持固定字号，
 * 以免信息密度被稀释。
 */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-7 flex flex-wrap items-end justify-between gap-4 3xl:mb-8">
      <div>
        <h1 className="text-[clamp(24px,1.8vw,32px)] font-semibold leading-tight tracking-tight text-content-1">
          {title}
        </h1>
        {description ? (
          <p className="mt-2 text-caption leading-relaxed text-content-3">{description}</p>
        ) : null}
      </div>
      {actions}
    </header>
  );
}
