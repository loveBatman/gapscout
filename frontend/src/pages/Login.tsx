import { useState, type FormEvent } from "react";
import { Compass, GitBranch, Lock, Scale, Search, ShieldCheck, User } from "lucide-react";
import { ACCOUNT_HINT } from "../lib/accounts";
import { useAuth } from "../lib/auth";
import { cn } from "../lib/utils";

/** 左侧门面的能力点：全部来自系统的真实能力，不用泛化描述 */
const FEATURES: { icon: React.ReactNode; title: string; detail: string }[] = [
  {
    icon: <Search size={15} />,
    title: "真实文献检索与四级去重",
    detail:
      "并发抓取 arXiv、OpenAlex 与 Semantic Scholar，按 DOI、arXiv ID、标题归一化与 MinHash 模糊匹配逐级判重。",
  },
  {
    icon: <GitBranch size={15} />,
    title: "三路信号交叉验证研究空白",
    detail:
      "文献自述的局限、方法-任务矩阵的空格、引用图谱的结构洞，三路独立产出后交叉验证，每条结论附带可跳转的原文证据。",
  },
  {
    icon: <Scale size={15} />,
    title: "开题撞车风险量化",
    detail:
      "计算想法与已有工作的语义相似度分布，列出最相似的工作并逐条给出差异点，在投入之前先确认有没有人做过。",
  },
  {
    icon: <ShieldCheck size={15} />,
    title: "逐句引用校验",
    detail:
      "每句断言标注来源，规则层拦编号与覆盖、模型层判语义蕴含，未通过的句子会明确标出而不是隐去。",
  },
];

const STACK = ["arXiv", "OpenAlex", "Semantic Scholar", "Sentence-Transformers", "UMAP", "HDBSCAN"];

export function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const canSubmit = username.trim().length > 0 && password.length > 0;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    if (!login(username, password)) {
      setError("用户名或密码错误，请检查后重试");
      return;
    }
    setError(null);
  }

  const fieldClass =
    "w-full border-0 bg-transparent text-body text-content-1 placeholder:text-content-4 focus:outline-none";
  const boxClass =
    "mt-2 flex items-center gap-2.5 rounded-xl border border-line-1 bg-surface-0/70 px-3.5 py-2.5 transition-colors focus-within:border-content-1";

  return (
    <main className="grid min-h-screen lg:grid-cols-[minmax(0,1fr)_clamp(420px,32%,520px)]">
      {/* ---------- 左：产品门面 ---------- */}
      <section className="flex flex-col justify-between px-7 py-9 lg:px-14 lg:py-14 3xl:px-20 4xl:px-24">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-content-1">
            <Compass size={19} className="text-surface-0" />
          </span>
          <span className="leading-tight">
            <span className="block text-body font-semibold tracking-tight text-content-1">
              空白侦察
            </span>
            <span className="block text-micro text-content-4">GapScout</span>
          </span>
        </div>

        <div className="max-w-[560px] py-12 lg:py-0 3xl:max-w-[620px]">
          <p className="text-micro font-medium tracking-[0.16em] text-content-4">
            RESEARCH DISCOVERY
          </p>
          <h1 className="mt-4 text-[clamp(28px,2.4vw,40px)] font-semibold leading-[1.15] tracking-[-0.022em] text-content-1">
            从真实文献出发，
            <br />
            找到值得做的那一个问题
          </h1>
          <p className="mt-5 max-w-lg text-body leading-relaxed text-content-3">
            不做凭空的"灵感生成"。系统检索真实论文、抽取作者自述的局限、计算方法迁移的空格，
            所有结论都能回溯到具体文献。
          </p>

          <ul className="mt-10 hidden space-y-5 lg:block">
            {FEATURES.map((feature) => (
              <li key={feature.title} className="flex items-start gap-3.5">
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-line-1 bg-surface-0 text-content-2">
                  {feature.icon}
                </span>
                <div>
                  <p className="text-caption font-medium text-content-1">{feature.title}</p>
                  <p className="mt-1 text-caption leading-relaxed text-content-3">
                    {feature.detail}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className="hidden flex-wrap items-center gap-x-3 gap-y-1.5 text-micro text-content-4 lg:flex">
          {STACK.map((item, index) => (
            <span key={item} className="flex items-center gap-3">
              {index > 0 ? <span className="h-3 w-px bg-line-2" /> : null}
              {item}
            </span>
          ))}
        </div>
      </section>

      {/* ---------- 右：登录 ---------- */}
      <section className="flex items-center justify-center px-6 pb-12 lg:border-l lg:border-line-1 lg:px-12 lg:py-14">
        <div className="animate-fade-up w-full max-w-[368px]">
          <div className="glass rounded-2xl px-7 py-8">
            <h2 className="text-heading text-content-1">登录</h2>
            <p className="mt-1.5 text-caption text-content-3">使用分配给你的账号进入工作台</p>

            <form onSubmit={submit} className="mt-7 space-y-4">
              {error ? (
                <div className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/[0.05] px-3.5 py-2.5">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-danger" />
                  <p className="text-caption text-danger">{error}</p>
                </div>
              ) : null}

              <label className="block">
                <span className="text-micro font-medium text-content-3">用户名</span>
                <div className={boxClass}>
                  <User size={15} className="shrink-0 text-content-4" />
                  <input
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    autoComplete="username"
                    placeholder="请输入用户名"
                    className={fieldClass}
                  />
                </div>
              </label>

              <label className="block">
                <span className="text-micro font-medium text-content-3">密码</span>
                <div className={boxClass}>
                  <Lock size={15} className="shrink-0 text-content-4" />
                  <input
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete="current-password"
                    placeholder="请输入密码"
                    className={fieldClass}
                  />
                </div>
              </label>

              <button
                type="submit"
                disabled={!canSubmit}
                className={cn(
                  "mt-1 flex w-full items-center justify-center gap-2 rounded-full px-4 py-3 text-body font-medium transition-colors",
                  canSubmit
                    ? "bg-accent-600 text-white hover:bg-accent-700 active:bg-accent-600"
                    : "cursor-not-allowed bg-surface-2 text-content-4",
                )}
              >
                进入工作台
              </button>
            </form>
          </div>

          <p className="mt-5 text-center text-micro leading-relaxed text-content-4">
            默认账号 {ACCOUNT_HINT}
            <br />
            重新登录会清空上一次的分析内容
          </p>
        </div>
      </section>
    </main>
  );
}
