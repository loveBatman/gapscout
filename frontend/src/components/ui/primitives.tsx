import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

/**
 * 面板。
 *
 * variant="glass" 用于**界面框架层**（侧栏输入卡、进度卡、登录卡），
 * 靠半透明 + 背景模糊 + 边缘高光形成浮起的玻璃层。
 *
 * 内容区（论文列表、正文、表格、图表）必须用默认的 "solid"——
 * 玻璃上的文字会因背景透出而降低对比度，长文阅读尤其明显。
 */
export function Panel({
  children,
  className,
  hoverable = false,
  variant = "solid",
}: {
  children: ReactNode;
  className?: string;
  hoverable?: boolean;
  /** solid 内容卡 / muted 指标卡 / glass 框架卡 */
  variant?: "solid" | "muted" | "glass";
}) {
  return (
    <section
      className={cn(
        variant === "glass" ? "glass rounded-xl" : variant === "muted" ? "panel-muted" : "panel",
        hoverable && "panel-hover",
        className,
      )}
    >
      {children}
    </section>
  );
}

export function PanelHeader({
  title,
  subtitle,
  action,
  icon,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <header className="flex items-start justify-between gap-4 border-b border-line-1 px-5 py-4">
      <div className="flex items-start gap-3">
        {icon ? (
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-content-2">
            {icon}
          </span>
        ) : null}
        <div>
          <h2 className="text-subheading text-content-1">{title}</h2>
          {subtitle ? (
            <p className="mt-1 text-caption text-content-3">{subtitle}</p>
          ) : null}
        </div>
      </div>
      {action}
    </header>
  );
}

export function Chip({
  children,
  tone = "default",
  className,
}: {
  children: ReactNode;
  /** default 中性 / accent 主强调 / cyan 与 violet 用于区分同类标签的不同类别 */
  tone?: "default" | "accent" | "cyan" | "violet" | "ok" | "warn";
  className?: string;
}) {
  const tones: Record<string, string> = {
    default: "border-line-1 bg-surface-1 text-content-3",
    accent: "border-accent-600/25 bg-accent-50 text-accent-700",
    cyan: "border-topic-2/25 bg-topic-2/[0.07] text-topic-2",
    violet: "border-topic-6/25 bg-topic-6/[0.07] text-topic-6",
    ok: "border-ok/30 bg-ok/[0.08] text-ok",
    warn: "border-warn/30 bg-warn/[0.08] text-warn",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-micro font-medium",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function StatCard({
  label,
  value,
  hint,
  tone = "brand",
  icon,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: "brand" | "cyan" | "ok" | "warn";
  icon?: ReactNode;
}) {
  const tones: Record<string, string> = {
    // 数值默认纯黑；只有状态型数值（成功/告警）才用低饱和状态色
    brand: "text-content-1",
    cyan: "text-content-2",
    ok: "text-ok",
    warn: "text-warn",
  };
  return (
    // 指标卡用 panel-muted：浅灰底、无边框，与白底内容卡形成层级；不做悬停位移
    <div className="panel-muted animate-fade-up px-5 py-4 4xl:px-6 4xl:py-5">
      <div className="flex items-center justify-between">
        <span className="text-micro font-normal text-content-4">{label}</span>
        {icon ? <span className={cn("opacity-70", tones[tone])}>{icon}</span> : null}
      </div>
      {/* key 变化触发重挂载，让数值刷新时有一次极轻的上浮过渡 */}
      <div
        key={typeof value === "string" ? value : undefined}
        className={cn(
          "num animate-tick mt-2.5 text-[clamp(24px,1.6vw,34px)] font-semibold leading-none",
          tones[tone],
        )}
      >
        {value}
      </div>
      {hint ? <p className="mt-2 text-micro text-content-4">{hint}</p> : null}
    </div>
  );
}

/**
 * 进度条。
 *
 * active 控制扫光动效，只有「正在执行且进度在进行中」才渲染扫光。
 * 原实现无条件渲染扫光，导致首次进入页面、进度为 0% 时进度条也在流动，
 * 看起来像已经在分析，与真实状态不符；分析完成后也应停止流动。
 */
export function ProgressBar({
  percent,
  active = false,
  className,
}: {
  percent: number;
  active?: boolean;
  className?: string;
}) {
  const safe = Math.max(0, Math.min(100, percent));
  const sweeping = active && safe > 0 && safe < 100;
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-surface-3", className)}>
      <div
        className="relative h-full rounded-full bg-accent-600 transition-[width] duration-500 ease-out"
        style={{ width: `${safe}%` }}
      >
        {sweeping ? (
          <span className="absolute inset-y-0 right-0 w-8 animate-sweep bg-gradient-to-r from-transparent to-white/40" />
        ) : null}
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  icon,
}: {
  title: string;
  description?: string;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      {icon ? (
        <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-surface-2 text-content-4">
          {icon}
        </span>
      ) : null}
      <p className="text-body font-medium text-content-2">{title}</p>
      {description ? (
        <p className="max-w-md text-caption text-content-3">{description}</p>
      ) : null}
    </div>
  );
}
