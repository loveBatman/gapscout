export interface Account {
  username: string;
  password: string;
  displayName: string;
  role: string;
}

/**
 * 预设账号（用户名 + 密码）。
 *
 * 安全边界（重要，需在技术文档中如实说明）：
 * 这是**纯前端门禁**——账号密码会随构建产物一起打包进前端资源，
 * 任何能打开浏览器开发者工具的人都能读到。
 * 它的作用是区分使用者、阻挡无意访问，不构成真正的访问控制。
 * 若后续需要真正的权限校验，应由后端提供登录接口与令牌验证。
 */
export const ACCOUNTS: Account[] = [
  { username: "root", password: "123456", displayName: "root", role: "管理员" },
];

export function findAccount(username: string, password: string): Account | null {
  const name = (username || "").trim().toLowerCase();
  return ACCOUNTS.find((item) => item.username === name && item.password === password) ?? null;
}

/**
 * 登录页页脚展示的可用账号，便于快速登录。
 *
 * 基于数组首项构造，而不是写死下标：此处曾用 ACCOUNTS[2]，
 * 账号精简为一个后就会渲染出 "undefined / undefined"。
 * 现在不论账号数量如何调整都不会再出这种错。
 */
export const ACCOUNT_HINT = ACCOUNTS[0]
  ? `${ACCOUNTS[0].username} / ${ACCOUNTS[0].password}`
  : "";
