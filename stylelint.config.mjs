export default {
  plugins: [
    "./scripts/stylelint/no-left-accent-border.mjs",
    "./scripts/stylelint/no-undocumented-colors.mjs",
  ],
  rules: {
    "atlas/no-left-accent-border": true,
    "atlas/no-undocumented-colors": [
      true,
      {
        tokenFiles: ["static/css/src/01-settings/tokens.css"],
      },
    ],
    "block-no-empty": true,
    "declaration-block-no-duplicate-properties": [
      true,
      {
        ignore: ["consecutive-duplicates-with-different-values"],
      },
    ],
    "property-no-unknown": true,
  },
};
