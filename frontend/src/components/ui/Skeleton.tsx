import { cn } from "../../lib/utils";

/**
 * 骨架屏：加载态占位。
 *
 * 用于分析运行中、结果尚未到达时替代空白区域——
 * 让用户知道"内容正在准备"而不是"页面出问题了"。
 * 宽度按行递减，模拟真实段落的参差，避免看起来像条纹装饰。
 */
export function Skeleton({ lines = 1, className }: { lines?: number; className?: string }) {
  if (lines <= 1) {
    return <div className={cn("skeleton h-4 w-full", className)} />;
  }
  return (
    <div className={cn("space-y-2.5", className)}>
      {Array.from({ length: lines }).map((_, index) => (
        <div
          key={index}
          className="skeleton h-4"
          style={{ width: `${100 - (index % 3) * 14}%` }}
        />
      ))}
    </div>
  );
}

/** 结果区骨架卡：与 panel 视觉一致，避免加载完成时出现布局跳动 */
export function SkeletonPanel({
  lines = 3,
  className,
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={cn("panel px-5 py-4", className)}>
      <div className="skeleton h-5 w-44" />
      <Skeleton lines={lines} className="mt-4" />
    </div>
  );
}
