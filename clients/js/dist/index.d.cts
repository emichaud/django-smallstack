/** Configuration for the SmallStack client. */
interface SmallStackConfig {
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
interface User {
    id: number;
    username: string;
    email: string;
    is_staff: boolean;
}
/** Token response returned by login, register, and refresh endpoints. */
interface TokenResponse {
    token: string;
    user: User;
    expires_at: string;
}
/** Standard API response wrapper. */
interface ApiResponse<T = unknown> {
    data: T;
    status: number;
    ok: boolean;
}
/** Paginated list response from SmallStack CRUD endpoints. */
interface PaginatedResponse<T = unknown> {
    count: number;
    next: string | null;
    previous: string | null;
    results: T[];
}
/** Registration payload. */
interface RegisterData {
    username: string;
    email: string;
    password: string;
    password_confirm: string;
    first_name?: string;
    last_name?: string;
}
/** A single password validation rule from Django's AUTH_PASSWORD_VALIDATORS. */
interface PasswordRequirement {
    name: string;
    description: string;
    [key: string]: unknown;
}
/** Options for generic API requests. */
interface RequestOptions {
    method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
    headers?: Record<string, string>;
    body?: unknown;
    params?: Record<string, string>;
}
/** Per-field validation errors returned by SmallStack. */
type FieldErrors = Record<string, string[]>;
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
declare function parseFieldErrors(response: ApiResponse): FieldErrors | null;

/**
 * Thrown by {@link SmallStackClient.resource} helpers when a request fails
 * (non-2xx). Carries the HTTP status, the raw response body, and — for 400
 * validation errors — a parsed `{ field: [messages] }` map ready for forms.
 */
declare class ApiError extends Error {
    readonly status: number;
    readonly data: unknown;
    readonly fieldErrors: FieldErrors | null;
    constructor(status: number, data: unknown);
}
/** Query params for list requests — values are coerced to strings, empties dropped. */
type QueryParams = Record<string, string | number | boolean | undefined | null>;
/** Typed CRUD helpers for one CRUDView resource. Throws {@link ApiError} on failure. */
interface Resource<T> {
    list(params?: QueryParams): Promise<PaginatedResponse<T>>;
    get(id: number | string): Promise<T>;
    create(data: Partial<T>): Promise<T>;
    update(id: number | string, data: Partial<T>): Promise<T>;
    remove(id: number | string): Promise<void>;
}
declare class SmallStackClient {
    private baseUrl;
    private token;
    private systemToken;
    private persist;
    private storageKey;
    /** Auth namespace with authentication-related methods. */
    readonly auth: {
        login: (username: string, password: string) => Promise<ApiResponse<TokenResponse>>;
        logout: () => Promise<ApiResponse<{
            message: string;
        }>>;
        me: () => Promise<ApiResponse<User>>;
        register: (data: RegisterData) => Promise<ApiResponse<TokenResponse>>;
        refreshToken: (expiresHours?: number) => Promise<ApiResponse<TokenResponse>>;
        changePassword: (current_password: string, new_password: string) => Promise<ApiResponse<{
            message: string;
        }>>;
        passwordRequirements: () => Promise<ApiResponse<PasswordRequirement[]>>;
    };
    constructor(config: SmallStackConfig);
    /**
     * Set the auth token for subsequent requests.
     */
    setToken(token: string): void;
    /**
     * Clear the current auth token.
     */
    clearToken(): void;
    private persistToken;
    /**
     * Make an authenticated API request.
     */
    api<T = unknown>(path: string, options?: RequestOptions): Promise<ApiResponse<T>>;
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
    resource<T = unknown>(base: string): Resource<T>;
    private login;
    private logout;
    private me;
    private register;
    private refreshToken;
    private passwordRequirements;
    private changePassword;
}

export { ApiError, type ApiResponse, type FieldErrors, type PaginatedResponse, type PasswordRequirement, type QueryParams, type RegisterData, type RequestOptions, type Resource, SmallStackClient, type SmallStackConfig, type TokenResponse, type User, parseFieldErrors };
