/** Configuration for the SmallStack client. */
export interface SmallStackConfig {
  /** Base URL of the SmallStack API (e.g. "https://example.com"). */
  baseUrl: string;
  /** Optional Bearer token for authentication. */
  token?: string;
  /** Auth-level token used automatically for register(). */
  systemToken?: string;
  /** Auto-sync token to localStorage (browser only). Default: false. */
  persist?: boolean;
  /** localStorage key for persisted token. Default: "smallstack_token". */
  storageKey?: string;
}

/** Represents an authenticated user. */
export interface User {
  id: number;
  username: string;
  email: string;
  is_staff: boolean;
}

/** Token response returned by login, register, and refresh endpoints. */
export interface TokenResponse {
  token: string;
  user: User;
  expires_at: string;
}

/** Standard API response wrapper. */
export interface ApiResponse<T = unknown> {
  data: T;
  status: number;
  ok: boolean;
}

/** Paginated list response from SmallStack CRUD endpoints. */
export interface PaginatedResponse<T = unknown> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/** Registration payload. */
export interface RegisterData {
  username: string;
  email: string;
  password: string;
  password_confirm: string;
  first_name?: string;
  last_name?: string;
}

/** A single password validation rule from Django's AUTH_PASSWORD_VALIDATORS. */
export interface PasswordRequirement {
  name: string;
  description: string;
  [key: string]: unknown;  // validators may include extra fields like min_length
}

/** Options for generic API requests. */
export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  headers?: Record<string, string>;
  body?: unknown;
  params?: Record<string, string>;
}

/** Per-field validation errors returned by SmallStack. */
export type FieldErrors = Record<string, string[]>;

/**
 * Extract per-field validation errors from a failed API response.
 *
 * SmallStack returns validation errors as `{ field_name: ["error message", ...] }`.
 * This helper extracts those into a typed `FieldErrors` object, ignoring
 * non-array values (like `detail` strings).
 *
 * Returns `null` if no field errors are found (e.g. the response is a
 * non-validation error like 401 or 500).
 *
 * @example
 * ```ts
 * const res = await client.auth.register(data);
 * if (!res.ok) {
 *   const errors = parseFieldErrors(res);
 *   if (errors) {
 *     // { username: ["A user with that username already exists."] }
 *     console.log(errors.username?.[0]);
 *   }
 * }
 * ```
 */
export function parseFieldErrors(response: ApiResponse): FieldErrors | null {
  let data = response.data;
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;

  // SmallStack nests validation errors under `errors`:
  //   { "errors": { "field": ["message", ...] } }
  // Unwrap that first; fall back to a flat { field: [...] } shape otherwise.
  const nested = (data as Record<string, unknown>).errors;
  if (nested && typeof nested === "object" && !Array.isArray(nested)) {
    data = nested as typeof data;
  }

  const errors: FieldErrors = {};
  let found = false;

  for (const [key, value] of Object.entries(data as Record<string, unknown>)) {
    if (Array.isArray(value) && value.every((v) => typeof v === "string")) {
      errors[key] = value as string[];
      found = true;
    }
  }

  return found ? errors : null;
}
