import { act } from "@testing-library/react";
import { vi } from "vitest";
import { Workspace } from "../../frontend/src/workspace";
import { payload } from "./fixtures";

/** The real controller and API client, with an isolated, fictional HTTP boundary. */
export function harness() {
  sessionStorage.clear();
  const workspace = new Workspace();
  const responses = new Map<string, unknown>();
  const fetch = vi.fn(async (path: string) =>
    Response.json(responses.has(path) ? responses.get(path) : payload(path)),
  );
  vi.stubGlobal("fetch", fetch);
  vi.stubGlobal("scrollTo", vi.fn());
  vi.stubGlobal("scrollIntoView", vi.fn());
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
  });
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value: function (this: HTMLDialogElement) {
      this.open = true;
    },
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true,
    value: function (this: HTMLDialogElement) {
      this.open = false;
    },
  });
  URL.createObjectURL = vi.fn(() => "blob:fixture");
  URL.revokeObjectURL = vi.fn();
  return {
    workspace,
    responses,
    fetch,
    unlock: () => act(() => workspace.unlock("fixture")),
    stop: () => {
      workspace.lock();
      vi.useRealTimers();
      vi.restoreAllMocks();
      vi.unstubAllGlobals();
    },
  };
}

export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
