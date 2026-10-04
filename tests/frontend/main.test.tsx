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
    const mark = root.querySelector(".brand-mark")!;
    expect(mark).toHaveAttribute("src", "./icon.svg");
    expect(mark).toHaveAttribute("alt", "");
    expect(mark).toHaveAttribute("aria-hidden", "true");
    expect(mark).toHaveAttribute("width", "44");
    expect(mark).toHaveAttribute("height", "44");
  } finally {
    root.remove();
    h.stop();
  }
});
