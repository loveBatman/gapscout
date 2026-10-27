import animate from "tailwindcss-animate";

/**
 * 设计系统：浅色极简 + 材质分层
 *
 * 参照：OpenAI 的克制、Apple 的通透、Vercel 的精确。
 *
 * 界面分三个物理层次，这是「高级感」的结构基础：
 *   背景层 —— 灰阶 mesh 渐变 + 噪点纹理，为毛玻璃提供可被模糊的内容
 *   结构层 —— 玻璃材质：半透明 + 背景模糊 + 边缘高光 + 多层阴影
 *   内容层 —— 纯白不透明，保证长文阅读舒适度
 *
 * 配色仍严格黑白灰、无强调色。玻璃只用于界面框架层，内容区一律不透明。
 *
 * 上一阶段（纯浅色版）已备份至 _backup_20261013_light/
 */

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      /**
       * 断点。
       *
       * Tailwind 默认最大只到 2xl（1536px），而 27 寸显示器普遍是 2560px——
       * 越过 1536px 后布局完全冻结，于是「元素尺寸不变 + 画布变大」，
       * 看起来就是内容缩在屏幕中间一小块。
       * 这里向上补两档，让大屏有专属的列数、画布与内边距。
       */
      screens: {
        "3xl": "1920px",
        "4xl": "2560px",
      },
      fontFamily: {
        // Inter 优先，断网时自动降级到系统无衬线（Segoe UI / SF Pro）
        sans: ['"Inter"', "system-ui", "-apple-system", '"Segoe UI"', "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
      colors: {
        /**
         * 表面层级：靠极浅的灰度差分层。
         *
         * surface-1 由 #FAFAFA 调整为 #F7F7F8：前者与纯白的差异仅 1.6%，
         * 用作「指标卡底色」时在白色页面上无法辨识；后者差异约 3%，
         * 刚刚可辨但不刺眼——指标卡靠底色而非边框分层，差值必须够用。
         */
        surface: {
          0: "#FFFFFF",
          1: "#F7F7F8",
          2: "#F1F1F1",
          3: "#E8E8E8",
        },
        /**
         * 文字层级。
         * content-1 用近黑而非纯黑：纯黑在纯白上对比度达 21:1，
         * 边缘过锐会显生硬、有"塑料感"。近黑保留层次余量。
         */
        content: {
          1: "#0A0A0B",
          2: "#3D3D3D",
          3: "#767881",
          4: "#A0A0A6",
        },
        /** 边框层级：常规浅灰，强调用近黑 */
        line: {
          1: "#E8E8E8",
          2: "#DDDEE1",
          strong: "#0A0A0B",
        },
        /**
         * 主强调色：学术蓝。
         *
         * 用于链接、选中态、主操作按钮、主数据图表。
         * 使用纪律：只出现在**承载信息或可交互**的位置（链接、选中、主操作、主图表），
         * 不用于装饰——顶栏、页头、面板背景、正文、边框一律保持灰白。
         */
        accent: {
          50: "#EFF6FF",
          100: "#DBEAFE",
          200: "#BFDBFE",
          300: "#93C5FD",
          500: "#3B82F6",
          600: "#2563EB",
          700: "#1D4ED8",
        },
        /**
         * 主题簇分类色板：8 个分散色相，用于区分领域内的研究方向。
         *
         * 取 600 阶左右的深度，保证在白色画布上醒目但不刺眼。
         * 与形状编码配合——颜色承担主要辨识，形状作为第二重编码，
         * 既照顾色觉障碍用户，也避免散点图与卡片之间因色差产生误读。
         */
        topic: {
          1: "#2563EB",
          2: "#0891B2",
          3: "#059669",
          4: "#D97706",
          5: "#E11D48",
          6: "#7C3AED",
          7: "#4F46E5",
          8: "#64748B",
        },
        /** 状态色：低饱和深色，配合图标与文字表达 */
        ok: "#1A7F37",
        warn: "#9A6700",
        danger: "#CF222E",
        info: "#0969DA",
      },
      fontSize: {
        /**
         * 大字号收紧字距——字号越大越需要收紧，这是"精密感"的主要来源。
         * 正文与说明类保持正常字距，避免长时间阅读疲劳。
         */
        display: ["32px", { lineHeight: "1.2", fontWeight: "600", letterSpacing: "-0.022em" }],
        heading: ["24px", { lineHeight: "1.3", fontWeight: "600", letterSpacing: "-0.016em" }],
        subheading: ["18px", { lineHeight: "1.45", fontWeight: "500", letterSpacing: "-0.008em" }],
        body: ["15px", { lineHeight: "1.7" }],
        caption: ["13px", { lineHeight: "1.55" }],
        micro: ["11px", { lineHeight: "1.45" }],
      },
      boxShadow: {
        /** 全部阴影透明度控制在 0.02-0.16 之间——重了就俗 */
        subtle: "0 1px 2px rgba(0,0,0,0.04), 0 1px 3px rgba(0,0,0,0.06)",
        /** 静态卡片：仅 1px 级，几乎看不见，只用来定义浮起 */
        raise: "0 1px 2px rgba(0,0,0,0.03)",
        /** 卡片常态：1px 定义 + 6px 缓升 */
        card: "0 1px 2px rgba(0,0,0,0.03), 0 4px 12px -6px rgba(0,0,0,0.08)",
        /** 卡片悬停与浮层：大扩散、低透明度 */
        float: "0 2px 4px rgba(0,0,0,0.04), 0 12px 32px -12px rgba(0,0,0,0.16)",
        /** 玻璃材质：内高光（模拟受光边缘）+ 1px 定义 + 30px 投影 */
        glass:
          "inset 0 1px 0 rgba(255,255,255,0.85), 0 1px 2px rgba(0,0,0,0.03), 0 10px 30px -14px rgba(0,0,0,0.14)",
        /** 细长玻璃（顶栏、徽标） */
        "glass-sm": "inset 0 1px 0 rgba(255,255,255,0.8), 0 1px 2px rgba(0,0,0,0.02)",
      },
      backgroundImage: {
        /**
         * 氛围背景：灰阶 mesh 渐变，深浅差仅 3-6%，几乎看不见。
         *
         * 它存在的唯一理由是让毛玻璃有"可被模糊的内容"——
         * backdrop-filter 模糊的是元素背后的东西，纯白背景上它完全无效。
         */
        "ambient-mesh":
          "radial-gradient(1100px 620px at 12% -8%, rgba(0,0,0,0.045), transparent 62%), radial-gradient(900px 520px at 92% 4%, rgba(0,0,0,0.032), transparent 60%), radial-gradient(760px 760px at 50% 108%, rgba(0,0,0,0.026), transparent 64%)",
        /**
         * 噪点纹理：消除大面积纯白带来的塑料感。
         * 用内联 SVG feTurbulence 生成，零依赖、无额外请求。
         */
        noise:
          "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='180' height='180' filter='url(%23n)'/%3E%3C/svg%3E\")",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        sweep: {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(220%)" },
        },
        /** 骨架屏扫光 */
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        /** 指标数值刷新：只做极轻的上浮，避免数字跳动干扰阅读 */
        tick: {
          "0%": { opacity: "0", transform: "translateY(3px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-up": "fade-up 220ms cubic-bezier(0,0,1,1) both",
        /** 进度条运行指示：仅由 ProgressBar 的 active 状态驱动，未运行时静止 */
        sweep: "sweep 1.6s ease-in-out infinite",
        shimmer: "shimmer 1.8s ease-in-out infinite",
        tick: "tick 260ms cubic-bezier(0,0,1,1) both",
      },
    },
  },
  plugins: [animate],
};
