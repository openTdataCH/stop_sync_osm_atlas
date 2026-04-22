#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");
const nodeModulesDir = path.join(repoRoot, "node_modules");
const vendorDir = path.join(repoRoot, "static", "vendor");

const copyPlan = [
  {
    source: "bootstrap/dist/css/bootstrap.min.css",
    target: "bootstrap/css/bootstrap.min.css",
  },
  {
    source: "bootstrap/dist/js/bootstrap.bundle.min.js",
    target: "bootstrap/js/bootstrap.bundle.min.js",
  },
  // Font Awesome: individual files instead of whole webfonts dir.
  // We copy fontawesome.min.css (base + icon classes) + solid.min.css +
  // regular.min.css, then merge & trim them during post-processing.
  {
    source: "@fortawesome/fontawesome-free/css/fontawesome.min.css",
    target: "font-awesome/css/fontawesome.min.css",
  },
  {
    source: "@fortawesome/fontawesome-free/css/solid.min.css",
    target: "font-awesome/css/solid.min.css",
  },
  {
    source: "@fortawesome/fontawesome-free/css/regular.min.css",
    target: "font-awesome/css/regular.min.css",
  },
  // Only woff2 webfonts for solid and regular (no brands, no legacy formats).
  {
    source: "@fortawesome/fontawesome-free/webfonts/fa-solid-900.woff2",
    target: "font-awesome/webfonts/fa-solid-900.woff2",
  },
  {
    source: "@fortawesome/fontawesome-free/webfonts/fa-regular-400.woff2",
    target: "font-awesome/webfonts/fa-regular-400.woff2",
  },
  {
    source: "leaflet/dist/leaflet.css",
    target: "leaflet/leaflet.css",
  },
  {
    source: "leaflet/dist/leaflet.js",
    target: "leaflet/leaflet.js",
  },
  {
    source: "leaflet/dist/images",
    target: "leaflet/images",
  },
  {
    source: "mermaid/dist/mermaid.min.js",
    target: "mermaid/mermaid.min.js",
  },
  {
    source: "mathjax/es5/tex-mml-chtml.js",
    target: "mathjax/es5/tex-mml-chtml.js",
  },
  {
    source: "mathjax/es5/output/chtml/fonts/tex.js",
    target: "mathjax/es5/output/chtml/fonts/tex.js",
  },
  {
    source: "mathjax/es5/output/chtml/fonts/woff-v2",
    target: "mathjax/es5/output/chtml/fonts/woff-v2",
  },
];

function resolveUnder(baseDir, relativePath) {
  return path.join(baseDir, ...relativePath.split("/"));
}

function assertPathExists(filePath) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`Required asset not found: ${filePath}`);
  }
}

function copyPath(sourcePath, targetPath) {
  const sourceStat = fs.statSync(sourcePath);
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });

  if (sourceStat.isDirectory()) {
    fs.cpSync(sourcePath, targetPath, { recursive: true, force: true });
    return;
  }

  fs.copyFileSync(sourcePath, targetPath);
}

function cleanManagedRoots(plan) {
  const roots = new Set(plan.map((entry) => entry.target.split("/")[0]));

  for (const root of roots) {
    fs.rmSync(path.join(vendorDir, root), { recursive: true, force: true });
  }
}

// ---------------------------------------------------------------------------
// Font Awesome post-processing
// ---------------------------------------------------------------------------
// Merge fontawesome.min.css + solid.min.css + regular.min.css into a single
// all.min.css and rewrite @font-face rules to reference only woff2 files.
// This eliminates brands (~1 MB) and legacy font formats (~70% of remaining).
// ---------------------------------------------------------------------------

/**
 * Rewrite @font-face blocks to only keep the woff2 src.
 *
 * Rebuilds each block from scratch: keeps every property except src,
 * then appends a single src pointing to the .woff2 file.
 *
 * Before: multiple src lines with eot, woff2, woff, ttf, svg
 * After:  src:url(../webfonts/fa-solid-900.woff2) format("woff2")
 */
function trimFontFaceSources(css) {
  return css.replace(
    /@font-face\{[^}]+\}/g,
    (block) => {
      // Extract the woff2 url+format pair from anywhere in the block
      const woff2Match = block.match(
        /url\([^)]*\.woff2\)\s*format\(["']woff2["']\)/,
      );
      if (!woff2Match) return block;

      // Get the inner content between @font-face{ and }
      const inner = block.slice("@font-face{".length, -1);

      // Parse properties: split on ; but handle values that contain
      // parentheses (like url() and format()) which may contain commas.
      // We split on semicolons and also handle the last property that
      // ends with the closing brace (no trailing semicolon).
      const props = inner
        .split(";")
        .map((p) => p.trim())
        .filter((p) => p.length > 0)
        // Drop all src: properties
        .filter((p) => !p.startsWith("src:"));

      // Rebuild with a clean woff2-only src
      props.push(`src:${woff2Match[0]}`);

      return `@font-face{${props.join(";")}}`;
    },
  );
}

function buildFontAwesomeCss() {
  const faDir = path.join(vendorDir, "font-awesome", "css");
  const files = [
    "fontawesome.min.css",
    "solid.min.css",
    "regular.min.css",
  ];

  let merged = files
    .map((f) => fs.readFileSync(path.join(faDir, f), "utf-8"))
    .join("\n");

  merged = trimFontFaceSources(merged);

  const outputPath = path.join(faDir, "all.min.css");
  fs.writeFileSync(outputPath, merged, "utf-8");

  // Remove the individual source CSS files (they are now merged)
  for (const f of files) {
    fs.unlinkSync(path.join(faDir, f));
  }

  const originalAllCss = path.join(
    nodeModulesDir,
    "@fortawesome",
    "fontawesome-free",
    "css",
    "all.min.css",
  );
  const originalSize = fs.statSync(originalAllCss).size;
  const trimmedSize = Buffer.byteLength(merged, "utf-8");

  console.log(
    `  Font Awesome CSS: ${originalSize} -> ${trimmedSize} bytes ` +
      `(${Math.round((1 - trimmedSize / originalSize) * 100)}% smaller)`,
  );
}

function reportWebfontSavings() {
  const originalDir = path.join(
    nodeModulesDir,
    "@fortawesome",
    "fontawesome-free",
    "webfonts",
  );
  let originalTotal = 0;
  for (const f of fs.readdirSync(originalDir)) {
    originalTotal += fs.statSync(path.join(originalDir, f)).size;
  }

  const trimmedDir = path.join(vendorDir, "font-awesome", "webfonts");
  let trimmedTotal = 0;
  for (const f of fs.readdirSync(trimmedDir)) {
    trimmedTotal += fs.statSync(path.join(trimmedDir, f)).size;
  }

  console.log(
    `  Font Awesome webfonts: ${originalTotal} -> ${trimmedTotal} bytes ` +
      `(${Math.round((1 - trimmedTotal / originalTotal) * 100)}% smaller)`,
  );
}

function writeVersionsManifest() {
  const packageJsonPath = path.join(repoRoot, "package.json");
  const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, "utf-8"));
  const devDeps = packageJson.devDependencies || {};

  const manifest = {
    generatedAtUtc: new Date().toISOString(),
    bootstrap: devDeps.bootstrap || null,
    "font-awesome": devDeps["@fortawesome/fontawesome-free"] || null,
    leaflet: devDeps.leaflet || null,
    mermaid: devDeps.mermaid || null,
    mathjax: devDeps.mathjax || null,
  };

  fs.mkdirSync(vendorDir, { recursive: true });
  fs.writeFileSync(
    path.join(vendorDir, "VERSIONS.json"),
    JSON.stringify(manifest, null, 2) + "\n",
    "utf-8",
  );
}

function main() {
  if (!fs.existsSync(nodeModulesDir)) {
    throw new Error("node_modules not found. Run npm install first.");
  }

  fs.mkdirSync(vendorDir, { recursive: true });
  cleanManagedRoots(copyPlan);

  for (const entry of copyPlan) {
    const sourcePath = resolveUnder(nodeModulesDir, entry.source);
    const targetPath = resolveUnder(vendorDir, entry.target);

    assertPathExists(sourcePath);
    copyPath(sourcePath, targetPath);
    console.log(`Copied ${entry.source} -> static/vendor/${entry.target}`);
  }

  // Post-process Font Awesome: merge CSS, strip brands & legacy formats.
  console.log("Post-processing Font Awesome...");
  buildFontAwesomeCss();
  reportWebfontSavings();

  writeVersionsManifest();
  console.log("Wrote static/vendor/VERSIONS.json");
}

main();
