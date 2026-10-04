import { act, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { harness } from "./harness";
it("boots the actual React entry point into the private locked workspace", async () => {
  const h = harness();
  const root = document.createElement("div");
  root.id = "root";
  document.body.append(root);
  try {
    await act(async () => {
      await import("../../frontend/src/main");
    });
    expect(
      screen.getByRole("button", { name: "Unlock workspace" }),
    ).toBeVisible();
    expect(h.fetch).not.toHaveBeenCalled();
  } finally {
    root.remove();
    h.stop();
  }
});
