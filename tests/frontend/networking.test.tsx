import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Networking } from "../../frontend/src/networking";
import { connection } from "./fixtures";
import { deferred, harness } from "./harness";
let h: ReturnType<typeof harness>;
beforeEach(async () => {
  h = harness();
  await h.unlock();
});
afterEach(() => h.stop());
it("loads bounded private portraits, falls back after image errors and sends only the requested invitation", async () => {
  h.workspace.navigate("networking");
  const send = vi.spyOn(h.workspace, "sendInvitation").mockResolvedValue();
  const discard = vi.spyOn(h.workspace, "discardPhoto");
  vi.spyOn(h.workspace, "photo").mockResolvedValue("blob:portrait");
  render(
    <Networking
      state={h.workspace.getSnapshot()}
      workspace={h.workspace}
      add={vi.fn()}
    />,
  );
  const image = await screen.findByAltText(
    "Profile photo of Example Recruiter",
  );
  await waitFor(() => expect(image).toHaveAttribute("src", "blob:portrait"));
  fireEvent.load(image);
  expect(image).toBeVisible();
  fireEvent.error(image);
  expect(image).not.toBeVisible();
  expect(discard).toHaveBeenCalledWith(1);
  fireEvent.click(
    screen.getByRole("button", { name: "Send queued invitation" }),
  );
  expect(send).toHaveBeenCalledWith(1);
  expect(
    screen.getByRole("link", {
      name: /Open LinkedIn profile for Example Recruiter/,
    }),
  ).toHaveAttribute("rel", "noopener noreferrer");
});
it("ignores a portrait arriving after its contact unmounts", async () => {
  h.workspace.navigate("networking");
  const photo = deferred<string | null>();
  vi.spyOn(h.workspace, "photo").mockReturnValue(photo.promise);
  const view = render(
    <Networking
      state={h.workspace.getSnapshot()}
      workspace={h.workspace}
      add={vi.fn()}
    />,
  );
  view.unmount();
  await act(async () => photo.resolve("blob:late"));
  expect(screen.queryByRole("img")).toBeNull();
});
it("keeps archived contacts accessible and resets to Active while discovering new contacts", () => {
  const state = {
    ...h.workspace.getSnapshot(),
    connections: [
      {
        ...connection,
        name: "",
        photo_available: false,
        state: "sent" as const,
        run_status: "done",
      },
    ],
  };
  const view = render(
    <Networking state={state} workspace={h.workspace} add={vi.fn()} />,
  );
  fireEvent.click(screen.getByRole("tab", { name: "Archived (1)" }));
  expect(screen.getByText("?")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Send queued invitation" }),
  ).toBeNull();
  view.rerender(
    <Networking
      state={{ ...state, searchingContacts: true }}
      workspace={h.workspace}
      add={vi.fn()}
    />,
  );
  expect(screen.getByRole("tab", { name: "Active (0)" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(screen.getByRole("button", { name: "Searching…" })).toHaveAttribute(
    "aria-busy",
    "true",
  );
});
it("opens only the requested contact modal and displays failure feedback", () => {
  const add = vi.fn();
  render(
    <Networking
      state={{
        ...h.workspace.getSnapshot(),
        activeInvitation: 1,
        feedback: {
          1: { run_status: "failed", run_message: "Provider unavailable" },
        },
      }}
      workspace={h.workspace}
      add={add}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Add contact" }));
  expect(add).toHaveBeenCalledOnce();
  expect(screen.getByText("Provider unavailable")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Send queued invitation" }),
  ).toBeDisabled();
});
