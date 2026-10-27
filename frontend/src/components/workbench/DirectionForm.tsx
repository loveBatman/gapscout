import { useState } from "react";
import { CornerDownLeft, Loader2, Search, Sparkles } from "lucide-react";
import { cn } from "../../lib/utils";

const DEFAULT_EXAMPLES = [
  "multimodal large language model inference",
  "retrieval augmented generation",
  "graph neural network for molecules",
  "code generation with large language models",
];

export interface DirectionFormProps {
  onSubmit: (value: string) => void;
  running: boolean;
  disabled?: boolean;
  label?: string;
  placeholder?: string;
  examples?: string[];
  submitLabel?: string;
}

export function DirectionForm({
  onSubmit,
  running,
  disabled,
  label = "细分研究方向",
  placeholder = "例如：multimodal large language model inference",
  examples = DEFAULT_EXAMPLES,
  submitLabel = "开始领域探索",
}: DirectionFormProps) {
  const [value, setValue] = useState("");
  const canSubmit = value.trim().length >= 2 && !running && !disabled;

  function submit() {
    if (!canSubmit) return;
    onSubmit(value.trim());
  }

  return (
    <div className="space-y-4">
      <label className="block">
        <span className="text-micro font-medium text-content-3">{label}</span>
        <div className="mt-2 flex items-center gap-2 rounded-xl border border-line-1 bg-surface-0 px-3.5 py-2.5 transition-colors focus-within:border-content-1">
          <Search size={16} className="shrink-0 text-content-4" />
          <input
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") submit();
            }}
            disabled={running || disabled}
            placeholder={placeholder}
            className="w-full border-0 bg-transparent text-body text-content-1 placeholder:text-content-4 focus:outline-none disabled:cursor-not-allowed"
          />
          {value ? (
            <span className="hidden items-center gap-1 text-micro text-content-4 sm:flex">
              <CornerDownLeft size={12} />
              回车
            </span>
          ) : null}
        </div>
      </label>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-micro font-medium text-content-4">示例方向</span>
        {examples.map((example) => (
          <button
            key={example}
            type="button"
            disabled={running}
            onClick={() => setValue(example)}
            className="rounded-full border border-line-1 bg-surface-0 px-3 py-1 text-caption text-content-3 transition-colors hover:border-content-1 hover:text-content-1 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {example}
          </button>
        ))}
      </div>

      <button
        type="button"
        onClick={submit}
        disabled={!canSubmit}
        className={cn(
          // 胶囊形：主操作与次级按钮（圆角矩形）、Chip（小圆角）形成形状语言上的重要性区分
          "group flex w-full items-center justify-center gap-2 rounded-full px-4 py-3 text-body font-medium transition-colors",
          canSubmit
            ? "bg-accent-600 text-white hover:bg-accent-700 active:bg-accent-600"
            : "cursor-not-allowed bg-surface-2 text-content-4",
        )}
      >
        {running ? (
          <>
            <Loader2 size={16} className="animate-spin" />
            正在分析文献……
          </>
        ) : (
          <>
            <Sparkles size={16} />
            {submitLabel}
          </>
        )}
      </button>
    </div>
  );
}
