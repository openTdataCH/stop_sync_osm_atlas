import fs from "node:fs";
import path from "node:path";
import colorNames from "color-name";
import stylelint from "stylelint";
import valueParser from "postcss-value-parser";

const ruleName = "atlas/no-undocumented-colors";
const messages = stylelint.utils.ruleMessages(ruleName, {
  rejected: (colors) =>
    `Unexpected undocumented color ${colors}; add a design token or use a color defined by the documented token source`,
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
const colorPattern = /#[\da-f]{3,8}\b|(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\([^)]*\)/gi;

function normalizeColor(color) {
  const compact = color.toLowerCase().replace(/\s+/g, "");
  const hex = compact.match(/^#([\da-f]{3,4})$/);

  if (!hex) return compact;

  return `#${[...hex[1]].map((character) => character.repeat(2)).join("")}`;
}

function colorBase(color) {
  const normalized = normalizeColor(color);
  const hex = normalized.match(/^#([\da-f]{6})(?:[\da-f]{2})?$/);
  if (hex) {
    return [0, 2, 4]
      .map((offset) => Number.parseInt(hex[1].slice(offset, offset + 2), 16))
      .join(",");
  }

  const rgb = normalized.match(/^rgba?\((\d+),(\d+),(\d+)(?:,.*)?\)$/);
  if (rgb) return `${rgb[1]},${rgb[2]},${rgb[3]}`;

  const named = colorNames[normalized];
  return named ? named.join(",") : null;
}

function loadDocumentedColors(tokenFiles) {
  const exact = new Set();
  const bases = new Set();

  for (const tokenFile of tokenFiles) {
    const contents = fs.readFileSync(path.resolve(process.cwd(), tokenFile), "utf8");
    for (const match of contents.matchAll(colorPattern)) {
      const normalized = normalizeColor(match[0]);
      const base = colorBase(normalized);
      exact.add(normalized);
      if (base) bases.add(base);
    }
  }

  return { exact, bases };
}

function isDocumentedColor(color, documentedColors) {
  const normalized = normalizeColor(color);
  const base = colorBase(normalized);
  return documentedColors.exact.has(normalized) || (base && documentedColors.bases.has(base));
}

const ruleFunction = (primaryOption, secondaryOptions = {}) => (root, result) => {
  const validOptions = stylelint.utils.validateOptions(result, ruleName, {
    actual: primaryOption,
    possible: [true],
  });

  if (!validOptions) return;

  const tokenFiles = secondaryOptions.tokenFiles || [];
  const documentedColors = loadDocumentedColors(tokenFiles);
  const sourceFile = root.source && root.source.input.file;
  const isTokenFile = tokenFiles.some(
    (tokenFile) => sourceFile && path.resolve(process.cwd(), tokenFile) === path.resolve(sourceFile),
  );

  if (isTokenFile) return;

  root.walkDecls((declaration) => {
    const undocumented = new Set();
    const parsedValue = valueParser(declaration.value);

    parsedValue.walk((node) => {
      if (node.type === "function") {
        const functionName = node.value.toLowerCase();
        if (functionName === "url") return false;
        if (!colorFunctionNames.has(functionName)) return undefined;

        const color = valueParser.stringify(node);
        if (!isDocumentedColor(color, documentedColors)) undocumented.add(color);
        return false;
      }

      if (node.type !== "word") return undefined;

      const word = node.value.toLowerCase();
      if (word.startsWith("#")) {
        if (!isDocumentedColor(word, documentedColors)) undocumented.add(node.value);
      } else if (Object.hasOwn(colorNames, word) && !allowedKeywords.has(word)) {
        if (!isDocumentedColor(word, documentedColors)) undocumented.add(node.value);
      }

      return undefined;
    });

    if (undocumented.size === 0) return;

    stylelint.utils.report({
      ruleName,
      result,
      node: declaration,
      message: messages.rejected([...undocumented].join(", ")),
    });
  });
};

ruleFunction.ruleName = ruleName;
ruleFunction.messages = messages;

export default stylelint.createPlugin(ruleName, ruleFunction);
