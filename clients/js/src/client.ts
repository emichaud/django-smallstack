import { parseFieldErrors } from "./types.js";
import type {
  SmallStackConfig,
  User,
  TokenResponse,
  ApiResponse,
  PaginatedResponse,
  PasswordRequirement,
  RegisterData,
  RequestOptions,
  FieldErrors,
} from "./types.js";

/**
 * Thrown by {@link SmallStackClient.resource} helpers when a request fails
 * (non-2xx). Carries the HTTP status, the raw response body, and — for 400
 * validation errors — a parsed `{ field: [messages] }` map ready for forms.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly data: unknown;
  readonly fieldErrors: FieldErrors | null;

  constructor(status: number, data: unknown) {
    super(`SmallStack API error ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
    this.fieldErrors = parseFieldErrors({ data, status, ok: false } as ApiResponse);
  }
}

/** Query params for list requests — values are coerced to strings, empties dropped. */
export type QueryParams = Record<string, string | number | boolean | undefined | null>;

function toStringParams(params?: QueryParams): Record<string, string> | undefined {
  if (!params) return undefined;
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") out[k] = String(v);
  }
  return out;
}

/** Typed CRUD helpers for one CRUDView resource. Throws {@link ApiError} on failure. */
export interface Resource<T> {
  list(params?: QueryParams): Promise<PaginatedResponse<T>>;
  get(id: number | string): Promise<T>;
  create(data: Partial<T>): Promise<T>;
  update(id: number | string, data: Partial<T>): Promise<T>;
  remove(id: number | string): Promise<void>;
}

export class SmallStackClient {
  private baseUrl: string;
  private token: string | undefined;
  private systemToken: string | undefined;
  private persist: boolean;
  private storageKey: string;

  /** Auth namespace with authentication-related methods. */
  public readonly auth: {
    login: (username: string, password: string) => Promise<ApiResponse<TokenResponse>>;
    logout: () => Promise<ApiResponse<{ message: string }>>;
    me: () => Promise<ApiResponse<User>>;
    register: (data: RegisterData) => Promise<ApiResponse<TokenResponse>>;
    refreshToken: (expiresHours?: number) => Promise<ApiResponse<TokenResponse>>;
    changePassword: (current_password: string, new_password: string) => Promise<ApiResponse<{ message: string }>>;
    passwordRequirements: () => Promise<ApiResponse<PasswordRequirement[]>>;
  };

  constructor(config: SmallStackConfig) {
    this.baseUrl = config.baseUrl.replace(/\/+$/, "");
    this.systemToken = config.systemToken;
    this.persist = config.persist ?? false;
    this.storageKey = config.storageKey ?? "smallstack_token";

    // Restore token: explicit > storage > none
    if (config.token) {
      this.token = config.token;
    } else if (this.persist && typeof localStorage !== "undefined") {
      const stored = localStorage.getItem(this.storageKey);
      if (stored) this.token = stored;
    }

    this.auth = {
      login: this.login.bind(this),
      logout: this.logout.bind(this),
      me: this.me.bind(this),
      register: this.register.bind(this),
      refreshToken: this.refreshToken.bind(this),
      changePassword: this.changePassword.bind(this),
      passwordRequirements: this.passwordRequirements.bind(this),
    };
  }

  /**
   * Set the auth token for subsequent requests.
   */
  setToken(token: string): void {
    this.token = token;
    this.persistToken(token);
  }

  /**
   * Clear the current auth token.
   */
  clearToken(): void {
    this.token = undefined;
    this.persistToken(undefined);
  }

  private persistToken(token: string | undefined): void {
    if (!this.persist || typeof localStorage === "undefined") return;
    if (token) {
      localStorage.setItem(this.storageKey, token);
    } else {
      localStorage.removeItem(this.storageKey);
    }
  }

  /**
   * Make an authenticated API request.
   */
  async api<T = unknown>(
    path: string,
    options: RequestOptions = {},
  ): Promise<ApiResponse<T>> {
    const { method = "GET", headers = {}, body, params } = options;

    let url = `${this.baseUrl}${path}`;
    if (params) {
      const searchParams = new URLSearchParams(params);
      url += `?${searchParams.toString()}`;
    }

    const requestHeaders: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...headers,
    };

    if (this.token) {
      requestHeaders["Authorization"] = `Bearer ${this.token}`;
    }

    const response = await fetch(url, {
      method,
      headers: requestHeaders,
      body: body != null ? JSON.stringify(body) : undefined,
    });

    const data = response.status === 204
      ? (undefined as T)
      : ((await response.json()) as T);

    return {
      data,
      status: response.status,
      ok: response.ok,
    };
  }

  /**
   * Typed CRUD helpers for a CRUDView resource. Each method calls the API and
   * **throws {@link ApiError}** on a non-2xx response (so forms can `catch` and
   * read `err.fieldErrors`), returning the parsed body on success.
   *
   * @example
   * ```ts
   * const items = client.resource<Item>("/api/inventory/items");
   * const page = await items.list({ q: "drill", status: "active", expand: "category" });
   * await items.create({ name: "New", sku: "X1", category: 1, bin: 1 });
   * ```
   */
  resource<T = unknown>(base: string): Resource<T> {
    const b = base.replace(/\/+$/, "");
    const unwrap = async <R>(res: ApiResponse<R>): Promise<R> => {
      if (!res.ok) throw new ApiError(res.status, res.data);
      return res.data;
    };
    return {
      list: async (params?: QueryParams) =>
        unwrap(await this.api<PaginatedResponse<T>>(`${b}/`, { params: toStringParams(params) })),
      get: async (id) => unwrap(await this.api<T>(`${b}/${id}/`)),
      create: async (data) => unwrap(await this.api<T>(`${b}/`, { method: "POST", body: data })),
      update: async (id, data) => unwrap(await this.api<T>(`${b}/${id}/`, { method: "PATCH", body: data })),
      remove: async (id) => {
        await unwrap(await this.api<void>(`${b}/${id}/`, { method: "DELETE" }));
      },
    };
  }

  // ---- Auth methods (bound to this.auth namespace) ----

  private async login(
    username: string,
    password: string,
  ): Promise<ApiResponse<TokenResponse>> {
    const result = await this.api<TokenResponse>("/api/auth/token/", {
      method: "POST",
      body: { username, password },
    });

    if (result.ok && result.data?.token) {
      this.token = result.data.token;
      this.persistToken(result.data.token);
    }

    return result;
  }

  private async logout(): Promise<ApiResponse<{ message: string }>> {
    const result = await this.api<{ message: string }>("/api/auth/logout/", {
      method: "POST",
    });

    if (result.ok) {
      this.clearToken();
    }

    return result;
  }

  private async me(): Promise<ApiResponse<User>> {
    return this.api<User>("/api/auth/me/");
  }

  private async register(data: RegisterData): Promise<ApiResponse<TokenResponse>> {
    // If systemToken configured, use it for the register call
    // then restore the previous token state on failure
    const previousToken = this.token;
    if (this.systemToken) {
      this.token = this.systemToken;
    }

    const result = await this.api<TokenResponse>("/api/auth/register/", {
      method: "POST",
      body: data,
    });

    if (result.ok && result.data?.token) {
      this.token = result.data.token;
      this.persistToken(result.data.token);
    } else if (this.systemToken) {
      // Failure: restore whatever token was set before
      this.token = previousToken;
    }

    return result;
  }

  private async refreshToken(expiresHours?: number): Promise<ApiResponse<TokenResponse>> {
    const result = await this.api<TokenResponse>("/api/auth/token/refresh/", {
      method: "POST",
      body: expiresHours != null ? { expires_hours: expiresHours } : undefined,
    });

    if (result.ok && result.data?.token) {
      this.token = result.data.token;
      this.persistToken(result.data.token);
    }

    return result;
  }

  private async passwordRequirements(): Promise<ApiResponse<PasswordRequirement[]>> {
    return this.api<PasswordRequirement[]>("/api/auth/password-requirements/");
  }

  private async changePassword(
    current_password: string,
    new_password: string,
  ): Promise<ApiResponse<{ message: string }>> {
    return this.api<{ message: string }>("/api/auth/password/", {
      method: "POST",
      body: { current_password, new_password },
    });
  }
}
