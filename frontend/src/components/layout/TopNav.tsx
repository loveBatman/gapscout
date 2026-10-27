import { Activity, Compass, Database, LogOut, Sparkles } from "lucide-react";
import type { HealthStatus, ViewKey } from "../../types";
import { useAuth } from "../../lib/auth";
import { cn } from "../../lib/utils";

const NAV_ITEMS: { key: ViewKey; label: string; hint: string }[] = [
  { key: "workbench", label: "探索工作台", hint: "领域全景与主题聚类" },
  { key: "opportunities", label: "机会点", hint: "三路信号识别研究空白" },
  { key: "feasibility", label: "开题评估", hint: "新颖性与撞车风险" },
  { key: "review", label: "综述编辑", hint: "带引用校验的综述草稿" },
];

export function TopNav({
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
    <header className="glass-topbar fixed inset-x-0 top-0 z-40 h-16">
      <div className="mx-auto flex h-full max-w-[1680px] items-center gap-5 px-6">
        <button
          type="button"
          onClick={() => onViewChange("workbench")}
          className="flex items-center gap-3"
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-content-1">
            <Compass size={18} className="text-surface-0" />
          </span>
          <span className="text-left leading-tight">
            <span className="block text-body font-semibold tracking-tight text-content-1">
              空白侦察
            </span>
            <span className="block text-micro text-content-4">GapScout</span>
          </span>
        </button>

        <div className="hidden h-6 w-px bg-line-1 lg:block" />

        <nav className="hidden items-center gap-1 lg:flex">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              type="button"
              title={item.hint}
              onClick={() => onViewChange(item.key)}
              aria-current={view === item.key ? "page" : undefined}
              className={cn(
                "relative rounded-lg px-3 py-2 text-caption transition-colors",
                view === item.key
                  ? "bg-surface-2 font-medium text-content-1"
                  : "font-normal text-content-3 hover:bg-surface-1 hover:text-content-1",
              )}
            >
              {item.label}
              {view === item.key ? (
                <span className="absolute inset-x-3 -bottom-px h-px bg-content-1" />
              ) : null}
            </button>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <StatusPill
            icon={<Activity size={12} />}
            label={online ? "服务在线" : "服务离线"}
            tone={online ? "ok" : "danger"}
          />
          <StatusPill
            icon={<Database size={12} />}
            label={dbUp ? "向量库就绪" : "内存模式"}
            tone={dbUp ? "ok" : "warn"}
          />
          <StatusPill
            icon={<Sparkles size={12} />}
            label={llmReady ? "AI 增强已启用" : "规则模式"}
            tone={llmReady ? "brand" : "muted"}
          />

          {user ? (
            <div className="ml-1 flex items-center gap-2 border-l border-line-1 pl-3">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-content-1 text-micro font-medium text-surface-0">
                {user.displayName.slice(0, 1)}
              </span>
              <span className="hidden leading-tight xl:block">
                <span className="block text-micro font-medium text-content-2">
                  {user.displayName}
                </span>
                <span className="block text-micro text-content-4">{user.role}</span>
              </span>
              <button
                type="button"
                onClick={logout}
                title="退出登录"
                className="flex h-7 w-7 items-center justify-center rounded-lg text-content-3 transition-colors hover:bg-surface-2 hover:text-content-1"
              >
                <LogOut size={14} />
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}

function StatusPill({
  icon,
  label,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  tone: "ok" | "warn" | "danger" | "brand" | "muted";
}) {
  const tones: Record<string, string> = {
    ok: "border-ok/25 bg-ok/[0.06] text-ok",
    warn: "border-warn/25 bg-warn/[0.06] text-warn",
    danger: "border-danger/25 bg-danger/[0.06] text-danger",
    // brand / muted：浅色体系下统一为中性描边，靠文字深浅区分主次
    brand: "border-line-1 bg-surface-1 text-content-2",
    muted: "border-line-1 bg-surface-1 text-content-4",
  };
  return (
    <span
      className={cn(
        "hidden items-center gap-1.5 rounded-full border px-2.5 py-1 text-micro font-medium sm:inline-flex",
        tones[tone],
      )}
    >
      {icon}
      {label}
    </span>
  );
}
