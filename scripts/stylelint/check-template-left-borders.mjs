import fs from "node:fs";
import path from "node:path";

const templatesRoot = path.resolve("templates");
const violations = [];

function visit(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      visit(entryPath);
    } else if (entry.isFile() && entry.name.endsWith(".html")) {
      const lines = fs.readFileSync(entryPath, "utf8").split("\n");
      lines.forEach((line, index) => {
        if (/\bborder-start(?:-\d+)?\b/.test(line)) {
          violations.push(`${path.relative(process.cwd(), entryPath)}:${index + 1}`);
        }
      });
    }
  }
}

visit(templatesRoot);

if (violations.length > 0) {
  console.error("Left-border utility classes are not part of the design system:");
  violations.forEach((violation) => console.error(`  ${violation}`));
  process.exitCode = 1;
}
