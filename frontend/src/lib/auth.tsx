import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { findAccount, type Account } from "./accounts";

interface AuthValue {
  user: Account | null;
  /**
   * 会话编号：每次登录/登出递增。
   * 它被用作状态层的 React key，从而让 Provider 重新挂载——
   * 以此实现「只有重新登录时才清空页面内容」，无需让认证层依赖状态层。
   */
  sessionId: number;
  login: (username: string, password: string) => boolean;
  logout: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

/**
 * 认证上下文。
 *
 * 登录态只存在于内存中，因此刷新浏览器即回到登录页（符合「刷新即清空」的要求），
 * 无需引入 localStorage/sessionStorage。
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Account | null>(null);
  const [sessionId, setSessionId] = useState(0);

  const login = useCallback((username: string, password: string) => {
    const account = findAccount(username, password);
    if (!account) return false;
    setUser(account);
    setSessionId((prev) => prev + 1);
    return true;
  }, []);

  const logout = useCallback(() => {
    setUser(null);
    setSessionId((prev) => prev + 1);
  }, []);

  const value = useMemo<AuthValue>(
    () => ({ user, sessionId, login, logout }),
    [user, sessionId, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth 必须在 AuthProvider 内部使用");
  }
  return context;
}
