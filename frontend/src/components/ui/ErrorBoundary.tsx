import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

/**
 * 渲染错误边界。
 *
 * 必要性：React 在渲染阶段抛错且无人捕获时会卸载整棵组件树——表现为整页白屏，
 * 连顶栏都消失，只能刷新恢复。本项目的增量渲染链路（SSE partial → 直接上屏）
 * 天然存在「数据形态与预期不符」的风险，一旦某个字段缺失就会触发这种故障。
 *
 * 这里把故障限制在单个页面内：
 * - resetKey（当前页面标识）变化时自动清除错误状态，因此切到别的页面再回来即可恢复
 * - 降级界面不展示原始异常信息，技术细节只进 console.error，
 *   既不把堆栈暴露给用户，也避免真正的恢复路径被技术噪音淹没
 * - onRetry 由上层提供：重试时重置该模块的运行状态，避免在坏数据上反复崩溃
 */
interface ErrorBoundaryProps {
  children: ReactNode;
  /** 变化时自动清除错误状态，通常传入当前页面标识 */
  resetKey?: string;
  /** 点击重试时调用，用于清理导致崩溃的运行状态 */
  onRetry?: () => void;
  /** 出错区域名称，用于文案 */
  label?: string;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidUpdate(prevProps: ErrorBoundaryProps) {
    // 切换页面即自动恢复：用户不必刷新，也不必理解发生了什么
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[render]", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    const label = this.props.label ?? "此页面";
    return (
      <main className="mx-auto w-full max-w-[2200px] px-6 pb-10 pt-24 3xl:px-10 4xl:px-14">
        <div className="panel animate-fade-up px-6 py-14 text-center">
          <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-danger/[0.08] text-danger">
            <AlertTriangle size={20} />
          </span>
          <p className="mt-4 text-body font-medium text-content-1">{label}渲染出错</p>
          <p className="mx-auto mt-2 max-w-md text-caption leading-relaxed text-content-3">
            其余功能不受影响，可以切换到其他页面继续使用，也可以直接重试当前操作。
          </p>
          <button
            type="button"
            onClick={() => {
              this.props.onRetry?.();
              this.setState({ error: null });
            }}
            className="mt-6 inline-flex items-center gap-2 rounded-xl bg-content-1 px-4 py-2.5 text-caption font-medium text-surface-0 transition-colors hover:bg-[#333333]"
          >
            <RotateCcw size={14} />
            重试
          </button>
        </div>
      </main>
    );
  }
}
