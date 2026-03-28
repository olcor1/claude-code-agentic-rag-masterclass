export const AUTH_TOKEN_STORAGE_KEY = "agentic-rag-token";
export const AUTH_UNAUTHORIZED_EVENT = "agentic-rag-unauthorized";

export class UnauthorizedError extends Error {
  constructor(message = "Session expired. Sign in again.") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

export function notifyUnauthorizedSession(message = "Session expired. Sign in again."): UnauthorizedError {
  window.localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
  window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT, { detail: { message } }));
  return new UnauthorizedError(message);
}
