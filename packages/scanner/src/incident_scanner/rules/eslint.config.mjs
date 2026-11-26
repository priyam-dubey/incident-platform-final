// Fixed analysis config. The repository's own ESLint config is NEVER loaded (config files are executable JS).
export default [
  {
    files: ["**/*.js", "**/*.jsx", "**/*.mjs", "**/*.cjs"],
    languageOptions: { ecmaVersion: "latest", sourceType: "module" },
    rules: {
      "no-eval": "error", "no-implied-eval": "error", "no-new-func": "error", "no-script-url": "error",
      "no-unsafe-finally": "error", "no-unsafe-negation": "error", "no-dupe-keys": "error", "no-unreachable": "warn",
      "no-self-assign": "warn", "no-cond-assign": "error", "no-constant-condition": "warn", "no-fallthrough": "warn",
      "no-prototype-builtins": "warn", "no-unused-vars": "off", "require-atomic-updates": "off", "use-isnan": "error",
      "valid-typeof": "error", "no-sparse-arrays": "warn", "no-useless-catch": "warn", "no-empty": "warn",
    },
  },
];
