"use strict";
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// src/index.ts
var index_exports = {};
__export(index_exports, {
  ApiError: () => ApiError,
  SmallStackClient: () => SmallStackClient,
  parseFieldErrors: () => parseFieldErrors
});
module.exports = __toCommonJS(index_exports);

// src/types.ts
function parseFieldErrors(response) {
  let data = response.data;
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const nested = data.errors;
  if (nested && typeof nested === "object" && !Array.isArray(nested)) {
    data = nested;
  }
  const errors = {};
  let found = false;
  for (const [key, value] of Object.entries(data)) {
    if (Array.isArray(value) && value.every((v) => typeof v === "string")) {
      errors[key] = value;
      found = true;
    }
  }
  return found ? errors : null;
}

// src/client.ts
var ApiError = class extends Error {
  status;
  data;
  fieldErrors;
  constructor(status, data) {
    super(`SmallStack API error ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
    this.fieldErrors = parseFieldErrors({ data, status, ok: false });
  }
};
function toStringParams(params) {
  if (!params) return void 0;
  const out = {};
  for (const [k, v] of Object.entries(params)) {
    if (v !== void 0 && v !== null && v !== "") out[k] = String(v);
  }
  return out;
}
var SmallStackClient = class {
  baseUrl;
  token;
  systemToken;
  persist;
  storageKey;
  /** Auth namespace with authentication-related methods. */
  auth;
  constructor(config) {
    this.baseUrl = config.baseUrl.replace(/\/+$/, "");
    this.systemToken = config.systemToken;
    this.persist = config.persist ?? false;
    this.storageKey = config.storageKey ?? "smallstack_token";
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
      passwordRequirements: this.passwordRequirements.bind(this)
    };
  }
  /**
   * Set the auth token for subsequent requests.
   */
  setToken(token) {
    this.token = token;
    this.persistToken(token);
  }
  /**
   * Clear the current auth token.
   */
  clearToken() {
    this.token = void 0;
    this.persistToken(void 0);
  }
  persistToken(token) {
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
  async api(path, options = {}) {
    const { method = "GET", headers = {}, body, params } = options;
    let url = `${this.baseUrl}${path}`;
    if (params) {
      const searchParams = new URLSearchParams(params);
      url += `?${searchParams.toString()}`;
    }
    const requestHeaders = {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...headers
    };
    if (this.token) {
      requestHeaders["Authorization"] = `Bearer ${this.token}`;
    }
    const response = await fetch(url, {
      method,
      headers: requestHeaders,
      body: body != null ? JSON.stringify(body) : void 0
    });
    const data = response.status === 204 ? void 0 : await response.json();
    return {
      data,
      status: response.status,
      ok: response.ok
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
  resource(base) {
    const b = base.replace(/\/+$/, "");
    const unwrap = async (res) => {
      if (!res.ok) throw new ApiError(res.status, res.data);
      return res.data;
    };
    return {
      list: async (params) => unwrap(await this.api(`${b}/`, { params: toStringParams(params) })),
      get: async (id) => unwrap(await this.api(`${b}/${id}/`)),
      create: async (data) => unwrap(await this.api(`${b}/`, { method: "POST", body: data })),
      update: async (id, data) => unwrap(await this.api(`${b}/${id}/`, { method: "PATCH", body: data })),
      remove: async (id) => {
        await unwrap(await this.api(`${b}/${id}/`, { method: "DELETE" }));
      }
    };
  }
  // ---- Auth methods (bound to this.auth namespace) ----
  async login(username, password) {
    const result = await this.api("/api/auth/token/", {
      method: "POST",
      body: { username, password }
    });
    if (result.ok && result.data?.token) {
      this.token = result.data.token;
      this.persistToken(result.data.token);
    }
    return result;
  }
  async logout() {
    const result = await this.api("/api/auth/logout/", {
      method: "POST"
    });
    if (result.ok) {
      this.clearToken();
    }
    return result;
  }
  async me() {
    return this.api("/api/auth/me/");
  }
  async register(data) {
    const previousToken = this.token;
    if (this.systemToken) {
      this.token = this.systemToken;
    }
    const result = await this.api("/api/auth/register/", {
      method: "POST",
      body: data
    });
    if (result.ok && result.data?.token) {
      this.token = result.data.token;
      this.persistToken(result.data.token);
    } else if (this.systemToken) {
      this.token = previousToken;
    }
    return result;
  }
  async refreshToken(expiresHours) {
    const result = await this.api("/api/auth/token/refresh/", {
      method: "POST",
      body: expiresHours != null ? { expires_hours: expiresHours } : void 0
    });
    if (result.ok && result.data?.token) {
      this.token = result.data.token;
      this.persistToken(result.data.token);
    }
    return result;
  }
  async passwordRequirements() {
    return this.api("/api/auth/password-requirements/");
  }
  async changePassword(current_password, new_password) {
    return this.api("/api/auth/password/", {
      method: "POST",
      body: { current_password, new_password }
    });
  }
};
// Annotate the CommonJS export names for ESM import in node:
0 && (module.exports = {
  ApiError,
  SmallStackClient,
  parseFieldErrors
});
//# sourceMappingURL=index.cjs.map