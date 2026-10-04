import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError } from "../../frontend/src/api";

describe("session-bound API client", () => {
  let client: ApiClient;
  const expired = vi.fn();
  beforeEach(() => {
    client = new ApiClient(expired);
    client.setToken("fixture-token");
    expired.mockClear();
  });
  afterEach(() => vi.unstubAllGlobals());
  it("sends authentication and the reviewed profile revision without leaking them to URLs", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ ok: true }));
    vi.stubGlobal("fetch", fetcher);
    expect(await client.json("/profile", "PUT", { name: "Alex" }, 3)).toEqual({
      ok: true,
    });
    expect(fetcher).toHaveBeenCalledWith(
      "/api/profile",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer fixture-token",
          "If-Match": "3",
        }),
        body: '{"name":"Alex"}',
      }),
    );
  });
  it("locks on unauthorised responses and preserves the readable error", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          Response.json({ detail: "Token expired" }, { status: 401 }),
        ),
    );
    await expect(client.json("/settings")).rejects.toMatchObject({
      status: 401,
      message: "Token expired",
    });
    expect(expired).toHaveBeenCalledOnce();
  });
  it("explains non-JSON provider failures and validation locations", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(new Response("Bad gateway", { status: 502 }))
        .mockResolvedValueOnce(
          Response.json(
            { detail: [{ loc: ["body", "email"], msg: "Invalid address" }] },
            { status: 422 },
          ),
        ),
    );
    await expect(client.json("/jobs")).rejects.toThrow(
      "The request failed (502)",
    );
    await expect(client.json("/profile")).rejects.toThrow(
      "email: Invalid address",
    );
  });
  it("rejects an old request after locking and unlocking with the same token", async () => {
    let finish!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve;
          }),
      ),
    );
    const response = client.json("/profile");
    client.setToken("");
    client.setToken("fixture-token");
    finish(Response.json({ private: true }));
    await expect(response).rejects.toThrow("Workspace locked");
  });
  it("checks session ownership after the response body resolves", async () => {
    let finish!: (value: unknown) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      }),
    );
    const result = client.json("/profile");
    await vi.waitFor(() => expect(finish).toBeDefined());
    client.setToken("");
    finish({ private: true });
    await expect(result).rejects.toBeInstanceOf(ApiError);
  });
  it("downloads only blobs owned by the current session", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("pdf")));
    expect((await client.blob("/documents")).size).toBe(3);
    let finish!: (value: Blob) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        blob: () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      }),
    );
    const result = client.blob("/documents");
    await vi.waitFor(() => expect(finish).toBeDefined());
    client.setToken("");
    finish(new Blob(["pdf"]));
    await expect(result).rejects.toThrow("Workspace locked");
  });
  it.each([
    { type: "image/jpeg", body: "photo" },
    { type: "image/png", body: "" },
    { type: "image/png", body: "x".repeat(512001) },
  ])(
    "rejects invalid optional photo content: $type",
    async ({ type, body }) => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(
            new Response(body, { headers: { "Content-Type": type } }),
          ),
      );
      await expect(client.photo(1)).rejects.toThrow(
        "Profile photo unavailable",
      );
    },
  );
  it("accepts a bounded local PNG and discards a late photo", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response("png", { headers: { "Content-Type": "image/png" } }),
        ),
    );
    expect((await client.photo(1)).size).toBe(3);
    let finish!: (value: Blob) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ "Content-Type": "image/png" }),
        blob: () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      }),
    );
    const result = client.photo(1);
    await vi.waitFor(() => expect(finish).toBeDefined());
    client.setToken("");
    finish(new Blob(["png"]));
    await expect(result).rejects.toThrow("Profile photo unavailable");
  });
});
