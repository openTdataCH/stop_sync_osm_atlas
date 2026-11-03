import fs from "node:fs";
import path from "node:path";
import colorNames from "color-name";
import stylelint from "stylelint";
import valueParser from "postcss-value-parser";

const ruleName = "atlas/no-undocumented-colors";
const messages = stylelint.utils.ruleMessages(ruleName, {
  literal: (colors) =>
    `Unexpected colour literal ${colors}; use a --color-* or --shadow-* token from the token file`,
  unknownToken: (tokens) =>
    `Unknown colour token ${tokens}; use a --color-* token defined in the token file`,
});

const colorFunctionNames = new Set([
  "rgb",
  "rgba",
  "hsl",
  "hsla",
  "hwb",
  "lab",
  "lch",
  "oklab",
  "oklch",
  "color",
]);
const allowedKeywords = new Set(["currentcolor", "transparent"]);
const tokenDefinitionPattern = /^\s*(--color-[a-z\d-]+)\s*:/gim;

function loadColorTokens(tokenFiles) {
  const tokens = new Set();

  for (const tokenFile of tokenFiles) {
    const contents = fs.readFileSync(path.resolve(process.cwd(), tokenFile), "utf8");
    for (const match of contents.matchAll(tokenDefinitionPattern)) tokens.add(match[1]);
  }

  return tokens;
}

const ruleFunction = (primaryOption, secondaryOptions = {}) => (root, result) => {
  const validOptions = stylelint.utils.validateOptions(result, ruleName, {
    actual: primaryOption,
    possible: [true],
  });

  if (!validOptions) return;

  const tokenFiles = secondaryOptions.tokenFiles || [];
  const colorTokens = loadColorTokens(tokenFiles);
  const sourceFile = root.source && root.source.input.file;
  const isTokenFile = tokenFiles.some(
    (tokenFile) => sourceFile && path.resolve(process.cwd(), tokenFile) === path.resolve(sourceFile),
  );

  if (isTokenFile) return;

  root.walkDecls((declaration) => {
    const literals = new Set();
    const unknownTokens = new Set();

    valueParser(declaration.value).walk((node) => {
      if (node.type === "function") {
        const functionName = node.value.toLowerCase();
        if (functionName === "url") return false;

        if (functionName === "var") {
          const name = node.nodes[0] && node.nodes[0].value;
          if (name && name.startsWith("--color-") && !colorTokens.has(name)) unknownTokens.add(name);
          return undefined;
        }

        if (colorFunctionNames.has(functionName)) {
          literals.add(valueParser.stringify(node));
          return false;
        }

        return undefined;
      }

      if (node.type !== "word") return undefined;

      const word = node.value.toLowerCase();
      if (/^#[\da-f]{3,8}$/.test(word)) {
        literals.add(node.value);
      } else if (Object.hasOwn(colorNames, word) && !allowedKeywords.has(word)) {
        literals.add(node.value);
      }

      return undefined;
    });

    if (literals.size > 0) {
      stylelint.utils.report({
        ruleName,
        result,
        node: declaration,
        message: messages.literal([...literals].join(", ")),
      });
    }

    if (unknownTokens.size > 0) {
      stylelint.utils.report({
        ruleName,
        result,
        node: declaration,
        message: messages.unknownToken([...unknownTokens].join(", ")),
      });
    }
  });
};

ruleFunction.ruleName = ruleName;
ruleFunction.messages = messages;

export default stylelint.createPlugin(ruleName, ruleFunction);
