import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  root: "frontend",
  base: "./",
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../src/applicator/static",
    emptyOutDir: true,
    sourcemap: true,
  },
  test: {
    environment: "jsdom",
    include: ["../tests/frontend/**/*.test.{ts,tsx}"],
    setupFiles: ["../tests/frontend/setup.ts"],
    coverage: {
      provider: "v8",
      include: ["src/api.ts", "src/ui.ts", "src/workspace.ts"],
      reporter: ["text", "json", "html"],
      reportsDirectory: "../test-results/unit-coverage",
      thresholds: { lines: 90, branches: 80, functions: 90, statements: 90 },
    },
  },
});
