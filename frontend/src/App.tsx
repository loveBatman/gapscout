import { useEffect, useState } from "react";
import type { HealthStatus, ViewKey } from "./types";
import { getHealth } from "./lib/api";
import { AuthProvider, useAuth } from "./lib/auth";
import { RunStoreProvider, useRunStore } from "./lib/runStore";
import { ErrorBoundary } from "./components/ui/ErrorBoundary";
import { TopNav } from "./components/layout/TopNav";
import { Login } from "./pages/Login";
import { Workbench } from "./pages/Workbench";
import { Opportunities } from "./pages/Opportunities";
import { Feasibility } from "./pages/Feasibility";
import { Review } from "./pages/Review";

function Shell() {
  const { user, sessionId } = useAuth();
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [view, setView] = useState<ViewKey>("workbench");

  useEffect(() => {
    // 未登录时不做任何服务探测
    if (!user) return undefined;

    let active = true;

    function refresh() {
      getHealth()
        .then((data) => {
          if (active) setHealth(data);
        })
        .catch((error: Error) => console.error("[health]", error));
    }

    refresh();
    // 定期刷新服务状态，确认后端与向量库就绪
    const timer = window.setInterval(refresh, 15000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [user]);

  if (!user) return <Login />;

  return (
    // sessionId 作为 key：每次重新登录都会重建状态层，
    // 从而实现「只有重新登录时才清空页面内容」。
    <RunStoreProvider key={sessionId}>
      <TopNav health={health} view={view} onViewChange={setView} />
      <PageArea view={view} health={health} />
    </RunStoreProvider>
  );
}

/**
 * 页面区域。
 *
 * 单独抽成组件是为了能放进 RunStoreProvider 内部——错误边界的重试需要重置
 * 当前模块的运行状态，因此必须能访问状态层。
 *
 * 边界只包住页面内容、不包顶栏：任一页面渲染异常时，顶栏与页面切换仍然可用，
 * 用户可以自己切到别的页面恢复，而不是面对整页白屏被迫刷新。
 */
function PageArea({ view, health }: { view: ViewKey; health: HealthStatus | null }) {
  const store = useRunStore();

  return (
    <ErrorBoundary resetKey={view} label="此页面" onRetry={() => store.reset(view)}>
      {view === "workbench" ? <Workbench health={health} /> : null}
      {view === "opportunities" ? <Opportunities /> : null}
      {view === "feasibility" ? <Feasibility /> : null}
      {view === "review" ? <Review /> : null}
    </ErrorBoundary>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  );
}
