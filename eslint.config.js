import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";
export default [
  {
    ignores: ["src/applicator/static/**", "node_modules/**", "test-results/**"],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["frontend/src/**/*.{ts,tsx}", "tests/frontend/**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser },
  },
  {
    files: ["frontend/*.js", "vite.config.ts", "eslint.config.js"],
    languageOptions: { globals: globals.node },
  },
];
