import { useMemo } from "react";
import type { MatrixView } from "../../types";
import { cn } from "../../lib/utils";

/**
 * 方法-任务矩阵热力图（信号 B 的可视化）。
 *
 * 空格用虚线描边高亮：空格代表"该组合尚无工作"，而邻域活跃的空格
 * 就是具备迁移价值的机会点，这一点必须在视觉上一眼可见。
 *
 * 配色：单色系（强调蓝）深浅表达密度——密度是连续量，用同一色相的透明度
 * 叠加即可，避免引入多色干扰；格内文字色随背景深浅自动切换以保证对比度。
 */
export function MatrixHeatmap({ matrix }: { matrix: MatrixView }) {
  const stats = useMemo(() => {
    const flat = matrix.matrix.flat();
    const max = flat.length > 0 ? Math.max(...flat) : 0;
    const gapKeys = new Set(
      matrix.gap_cells.map((cell) => `${cell.task}::${cell.method}`),
    );
    return { max: Math.max(1, max), gapKeys };
  }, [matrix]);

  if (matrix.tasks.length === 0 || matrix.methods.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-line-2 text-caption text-content-3">
        当前语料不足以构建方法-任务矩阵
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-[3px] text-micro">
        <thead>
          <tr>
            <th className="w-20 text-left font-medium text-content-4" />
            {matrix.methods.map((method) => (
              <th
                key={method}
                className="min-w-[62px] px-1 pb-1 text-center font-medium text-content-3"
                title={method}
              >
                <span className="block truncate">{method}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.tasks.map((task, rowIndex) => (
            <tr key={task}>
              <th
                className="max-w-[76px] truncate pr-2 text-right font-medium text-content-3"
                title={task}
              >
                {task}
              </th>
              {matrix.methods.map((method, columnIndex) => {
                const count = matrix.matrix[rowIndex]?.[columnIndex] ?? 0;
                const isGap = count === 0 && stats.gapKeys.has(`${task}::${method}`);
                const intensity = count / stats.max;
                // 密度映射到强调蓝的透明度：空白接近白，最密为饱和蓝
                const alpha = 0.1 + intensity * 0.85;
                // 背景越深文字越白；浅底上用深蓝而非黑，保持同一色相
                const textColor = alpha > 0.5 ? "#FFFFFF" : "#1D4ED8";

                return (
                  <td key={method} className="p-0">
                    <div
                      title={
                        isGap
                          ? `${task} × ${method}：尚无工作，但邻域活跃`
                          : `${task} × ${method}：${count} 篇`
                      }
                      className={cn(
                        "num flex h-8 items-center justify-center rounded text-micro font-medium transition-transform hover:scale-105",
                        count === 0 && "text-content-4",
                        // 空格且邻域活跃：虚线框标记，是待迁移的机会点
                        isGap && "border border-dashed border-accent-600 bg-accent-50 text-accent-700",
                      )}
                      style={
                        count > 0
                          ? { backgroundColor: `rgba(37, 99, 235, ${alpha})`, color: textColor }
                          : undefined
                      }
                    >
                      {count > 0 ? count : isGap ? "空" : "·"}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      <div className="mt-3 flex flex-wrap items-center gap-4 px-1 text-micro text-content-3">
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-6 rounded bg-accent-600/60" />
          已有工作（颜色越深越多）
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-6 rounded border border-dashed border-accent-600 bg-accent-50" />
          空格且邻域活跃（潜在机会）
        </span>
      </div>
    </div>
  );
}
