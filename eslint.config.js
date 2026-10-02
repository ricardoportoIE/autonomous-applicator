import js from "@eslint/js";
import globals from "globals";

export default [
  js.configs.recommended,
  {
    files: ["src/applicator/static/*.js"],
    languageOptions: { globals: globals.browser },
  },
  {
    files: ["frontend/*.js", "tests/frontend/*.js"],
    languageOptions: { globals: globals.node },
  },
];
