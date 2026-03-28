import { createContext, startTransition, useContext, useEffect, useState, type ReactNode } from "react";

import { fetchMe, login, register } from "@/api/client";
import type { User } from "@/api/types";
import { AUTH_TOKEN_STORAGE_KEY, AUTH_UNAUTHORIZED_EVENT } from "@/lib/auth-session";

type AuthContextValue = {
  token: string | null;
  user: User | null;
  isReady: boolean;
  error: string | null;
  loginWithPassword: (email: string, password: string) => Promise<void>;
  registerWithPassword: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [isReady, setIsReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const savedToken = window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
    if (!savedToken) {
      setIsReady(true);
      return;
    }

    setToken(savedToken);
    fetchMe(savedToken)
      .then((nextUser) => {
        startTransition(() => {
          setUser(nextUser);
          setIsReady(true);
        });
      })
      .catch(() => {
        window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
        setToken(null);
        setUser(null);
        setIsReady(true);
      });
  }, []);

  useEffect(() => {
    const handleUnauthorized = (event: Event) => {
      const message =
        event instanceof CustomEvent && typeof event.detail?.message === "string"
          ? event.detail.message
          : "Session expired. Sign in again.";
      window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
      startTransition(() => {
        setToken(null);
        setUser(null);
        setError(message);
        setIsReady(true);
      });
    };

    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
  }, []);

  const saveSession = async (nextToken: string) => {
    window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, nextToken);
    const nextUser = await fetchMe(nextToken);
    startTransition(() => {
      setToken(nextToken);
      setUser(nextUser);
      setError(null);
    });
  };

  const loginWithPassword = async (email: string, password: string) => {
    try {
      const response = await login(email, password);
      await saveSession(response.access_token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
      throw err;
    }
  };

  const registerWithPassword = async (email: string, password: string) => {
    try {
      const response = await register(email, password);
      await saveSession(response.access_token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
      throw err;
    }
  };

  const logout = () => {
    window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    startTransition(() => {
      setToken(null);
      setUser(null);
      setError(null);
    });
  };

  return (
    <AuthContext.Provider
      value={{
        token,
        user,
        isReady,
        error,
        loginWithPassword,
        registerWithPassword,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
