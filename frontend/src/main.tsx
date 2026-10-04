import { createRoot } from "react-dom/client";
import { App } from "./App";
import { Workspace } from "./workspace";
import "../dashboard.css";

createRoot(document.getElementById("root")!).render(
  <App workspace={new Workspace()} />,
);
