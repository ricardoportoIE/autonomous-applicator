import { errorDetail } from "./ui";

export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
  ) {
    super(message);
  }
}

/** A generation identifies a session, even when the same token is used again. */
export class ApiClient {
  private token = "";
  private generation = 0;
  constructor(private expired: (message: string) => void) {}
  setToken(token: string) {
    this.token = token;
    this.generation++;
  }
  session() {
    return this.generation;
  }
  isCurrent(session: number) {
    return session === this.generation && Boolean(this.token);
  }
  private async response(
    path: string,
    method = "GET",
    body?: unknown,
    revision?: number,
  ) {
    const session = this.generation;
    const options: RequestInit = {
      method,
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
      headers: {
        Authorization: "Bearer " + this.token,
        "Content-Type": "application/json",
        ...(revision === undefined ? {} : { "If-Match": String(revision) }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    };
    let response: Response;
    try {
      response = await fetch("/api" + path, options);
    } catch (error) {
      // One bounded transport retry is safe for reads; mutations are never retried.
      if (method !== "GET" || !this.isCurrent(session)) throw error;
      await new Promise((resolve) => setTimeout(resolve, 100));
      if (!this.isCurrent(session))
        throw new ApiError("Workspace locked. Unlock it before continuing.");
      response = await fetch("/api" + path, options);
    }
    if (!this.isCurrent(session))
      throw new ApiError("Workspace locked. Unlock it before continuing.");
    if (!response.ok) {
      const error: unknown = await response.json().catch(() => null);
      if (!this.isCurrent(session))
        throw new ApiError("Workspace locked. Unlock it before continuing.");
      const message = errorDetail(error, response.status);
      if (response.status === 401) this.expired(message);
      throw new ApiError(message, response.status);
    }
    return { response, session };
  }
  async json<T>(
    path: string,
    method = "GET",
    body?: unknown,
    revision?: number,
  ): Promise<T> {
    const { response, session } = await this.response(
      path,
      method,
      body,
      revision,
    );
    const result = (await response.json()) as T;
    if (!this.isCurrent(session))
      throw new ApiError("Workspace locked. Unlock it before continuing.");
    return result;
  }
  async blob(path: string): Promise<Blob> {
    const { response, session } = await this.response(path);
    const blob = await response.blob();
    if (!this.isCurrent(session))
      throw new ApiError("Workspace locked. Unlock it before continuing.");
    return blob;
  }
  async photo(id: number): Promise<Blob> {
    const { response, session } = await this.response(
      `/connections/${id}/photo`,
    );
    if (response.headers.get("Content-Type") !== "image/png")
      throw new ApiError("Profile photo unavailable");
    const blob = await response.blob();
    if (!this.isCurrent(session) || !blob.size || blob.size > 512000)
      throw new ApiError("Profile photo unavailable");
    return blob;
  }
}
