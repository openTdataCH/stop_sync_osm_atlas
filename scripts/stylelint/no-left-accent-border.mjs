import stylelint from "stylelint";

const ruleName = "atlas/no-left-accent-border";
const messages = stylelint.utils.ruleMessages(ruleName, {
  rejected: (property) =>
    `Unexpected ${property}; left accent and colored left borders are not part of the design system`,
});

const properties = new Set([
  "border-left",
  "border-left-color",
  "border-left-style",
  "border-left-width",
  "border-inline-start",
  "border-inline-start-color",
  "border-inline-start-style",
  "border-inline-start-width",
]);

const resetKeywords = new Set([
  "initial",
  "inherit",
  "unset",
  "revert",
  "revert-layer",
]);

function isAllowedReset(property, value) {
  const normalized = value.trim().toLowerCase();

  if (resetKeywords.has(normalized)) return true;
  if (property.endsWith("-color")) return normalized === "transparent";
  if (property.endsWith("-style")) return normalized === "none" || normalized === "hidden";
  if (property.endsWith("-width")) return /^0(?:\.0+)?(?:[a-z%]+)?$/.test(normalized);

  const parts = normalized.split(/\s+/);
  if (parts.includes("transparent")) {
    return parts.every((part) =>
      part === "transparent" ||
      ["none", "hidden", "solid", "dashed", "dotted", "double"].includes(part) ||
      /^\d*\.?\d+(?:[a-z%]+)?$/.test(part),
    );
  }

  return parts.every((part) =>
      part === "none" ||
      part === "hidden" ||
      part === "transparent" ||
      /^0(?:\.0+)?(?:[a-z%]+)?$/.test(part),
  );
}

const ruleFunction = (primaryOption) => (root, result) => {
  const validOptions = stylelint.utils.validateOptions(result, ruleName, {
    actual: primaryOption,
    possible: [true],
  });

  if (!validOptions) return;

  root.walkDecls((declaration) => {
    const property = declaration.prop.toLowerCase();
    if (!properties.has(property) || isAllowedReset(property, declaration.value)) return;

    stylelint.utils.report({
      ruleName,
      result,
      node: declaration,
      word: declaration.prop,
      message: messages.rejected(declaration.prop),
    });
  });
};

ruleFunction.ruleName = ruleName;
ruleFunction.messages = messages;

export default stylelint.createPlugin(ruleName, ruleFunction);
