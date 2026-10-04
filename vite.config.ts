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
    maxWorkers: 4,
    include: ["../tests/frontend/**/*.test.{ts,tsx}"],
    setupFiles: ["../tests/frontend/setup.ts"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/contracts.ts", "src/**/*.d.ts"],
      reporter: ["text", "json", "html"],
      reportsDirectory: "../test-results/unit-coverage",
      thresholds: {
        perFile: true,
        lines: 100,
        branches: 100,
        functions: 100,
        statements: 100,
      },
    },
  },
});
