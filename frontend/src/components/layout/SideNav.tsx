import {
  Activity,
  Compass,
  Database,
  LogOut,
  Scale,
  ScrollText,
  Sparkles,
} from "lucide-react";
import type { HealthStatus, ViewKey } from "../../types";
import { useAuth } from "../../lib/auth";
import { cn } from "../../lib/utils";

const NAV_ITEMS: { key: ViewKey; label: string; hint: string; icon: React.ReactNode }[] = [
  { key: "workbench", label: "探索工作台", hint: "领域全景与主题聚类", icon: <Compass size={16} /> },
  { key: "opportunities", label: "机会点", hint: "三路信号识别研究空白", icon: <Sparkles size={16} /> },
  { key: "feasibility", label: "开题评估", hint: "新颖性与撞车风险", icon: <Scale size={16} /> },
  { key: "review", label: "综述编辑", hint: "带引用校验的综述草稿", icon: <ScrollText size={16} /> },
];

/**
 * 左侧固定导航栏（**当前未启用**）。
 *
 * 背景：曾作为「结构重组」的一部分替代顶部导航，但实际观感不佳——
 * 本项目只有四个功能入口，侧栏内容过少显得空，且与内容区形成横向割裂感。
 * 已回退为 TopNav，此文件保留以备后续需要（例如功能扩展到六个以上入口时）。
 *
 * 重新启用需同时改三处：
 *   1. App.tsx 壳层：加回 <SideNav />，并给内容列加 `lg:pl-60`
 *   2. TopNav.tsx：加回 `lg:hidden`（避免两套导航同时出现）
 *   3. 四个页面的 main：`pt-24` 改为 `lg:pt-8`，左栏 `xl:top-24` 改为 `xl:top-8`
 *
 * 设计说明：宽度固定 240px 不随断点变化——导航项是「图标 + 文字」的短标签，
 * 固定偏移量能让内容列的留白计算保持简单。
 */
export function SideNav({
  health,
  view,
  onViewChange,
}: {
  health: HealthStatus | null;
  view: ViewKey;
  onViewChange: (view: ViewKey) => void;
}) {
  const { user, logout } = useAuth();
  const online = health?.status === "ok";
  const dbUp = health?.database === "up";
  const llmReady = health?.llm_configured === true;

  return (
    <aside className="glass fixed inset-y-0 left-0 z-40 hidden w-60 flex-col lg:flex">
      <div className="flex h-16 shrink-0 items-center gap-3 px-5">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-content-1">
          <Compass size={18} className="text-surface-0" />
        </span>
        <span className="leading-tight">
          <span className="block text-body font-semibold tracking-tight text-content-1">
            空白侦察
          </span>
          <span className="block text-micro text-content-4">GapScout</span>
        </span>
      </div>

      <nav className="mt-3 min-h-0 flex-1 overflow-y-auto px-3">
        <ul className="space-y-1">
          {NAV_ITEMS.map((item) => (
            <li key={item.key}>
              <button
                type="button"
                title={item.hint}
                onClick={() => onViewChange(item.key)}
                aria-current={view === item.key ? "page" : undefined}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-caption transition-colors",
                  view === item.key
                    ? "bg-surface-2 font-medium text-content-1"
                    : "font-normal text-content-3 hover:bg-surface-1 hover:text-content-1",
                )}
              >
                <span className="shrink-0">{item.icon}</span>
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <div className="space-y-1.5 px-4 pb-3.5">
        <SideStatus
          icon={<Activity size={12} />}
          label={online ? "服务在线" : "服务离线"}
          tone={online ? "ok" : "danger"}
        />
        <SideStatus
          icon={<Database size={12} />}
          label={dbUp ? "向量库就绪" : "内存模式"}
          tone={dbUp ? "ok" : "warn"}
        />
        <SideStatus
          icon={<Sparkles size={12} />}
          label={llmReady ? "AI 增强已启用" : "规则模式"}
          tone={llmReady ? "brand" : "muted"}
        />
      </div>

      {user ? (
        <div className="flex items-center gap-2.5 border-t border-line-1 px-4 py-3.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-content-1 text-micro font-medium text-surface-0">
            {user.displayName.slice(0, 1)}
          </span>
          <span className="min-w-0 flex-1 leading-tight">
            <span className="block truncate text-micro font-medium text-content-2">
              {user.displayName}
            </span>
            <span className="block truncate text-micro text-content-4">{user.role}</span>
          </span>
          <button
            type="button"
            onClick={logout}
            title="退出登录"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-content-3 transition-colors hover:bg-surface-2 hover:text-content-1"
          >
            <LogOut size={14} />
          </button>
        </div>
      ) : null}
    </aside>
  );
}

/** 侧栏底部的服务状态：纵向紧凑排列，只用颜色与文字区分，不加底色 */
function SideStatus({
  icon,
  label,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  tone: "ok" | "warn" | "danger" | "brand" | "muted";
}) {
  const tones: Record<string, string> = {
    ok: "text-ok",
    warn: "text-warn",
    danger: "text-danger",
    brand: "text-content-2",
    muted: "text-content-4",
  };
  return (
    <span className={cn("flex items-center gap-2 text-micro", tones[tone])}>
      {icon}
      {label}
    </span>
  );
}
