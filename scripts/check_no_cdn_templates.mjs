#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");
const templatesDir = path.join(repoRoot, "templates");

const templateExtensions = new Set([".html", ".jinja", ".jinja2"]);
const externalAssetTagRegex = /<(script|link)\b[^>]*(src|href)\s*=\s*["']https?:\/\/[^"']+["'][^>]*>/i;

function walkFiles(dirPath, acc) {
  const entries = fs.readdirSync(dirPath, { withFileTypes: true });

  for (const entry of entries) {
    const entryPath = path.join(dirPath, entry.name);

    if (entry.isDirectory()) {
      walkFiles(entryPath, acc);
      continue;
    }

    if (templateExtensions.has(path.extname(entry.name).toLowerCase())) {
      acc.push(entryPath);
    }
  }
}

function main() {
  if (!fs.existsSync(templatesDir)) {
    throw new Error("templates directory not found.");
  }

  const files = [];
  walkFiles(templatesDir, files);

  const violations = [];

  for (const filePath of files) {
    const content = fs.readFileSync(filePath, "utf-8");
    const lines = content.split(/\r?\n/);

    lines.forEach((line, index) => {
      if (!externalAssetTagRegex.test(line)) {
        return;
      }

      violations.push({
        filePath: path.relative(repoRoot, filePath),
        lineNumber: index + 1,
        line: line.trim(),
      });
    });
  }

  if (violations.length > 0) {
    console.error("Found external asset URLs in <script>/<link> tags:");
    for (const violation of violations) {
      console.error(`${violation.filePath}:${violation.lineNumber}`);
      console.error(`  ${violation.line}`);
    }
    process.exit(1);
  }

  console.log("No external CDN <script>/<link> asset URLs found in templates.");
}

main();
