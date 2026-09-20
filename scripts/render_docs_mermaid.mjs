#!/usr/bin/env node

import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { mkdir } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const configPath = join(repoRoot, 'documentation', 'pdf_generator', 'mermaid_render_config.json');
const puppeteerConfigPath = join(repoRoot, 'documentation', 'pdf_generator', 'puppeteer-config.json');
const outputDir = join(repoRoot, 'documentation', 'generated', 'diagrams');
const embeddedEngineRoot = join(repoRoot, 'engine');
const engineRoot = process.env.ENGINE_DIR
  ? resolve(repoRoot, process.env.ENGINE_DIR)
  : existsSync(join(embeddedEngineRoot, 'pyproject.toml'))
    ? embeddedEngineRoot
    : resolve(repoRoot, '..', 'engine');
const sourceDirs = [
  join(repoRoot, 'documentation'),
  join(engineRoot, 'documentation'),
];
const puppeteerPackagePath = join(repoRoot, 'node_modules', 'puppeteer-core', 'package.json');
const mermaidBundlePath = join(repoRoot, 'node_modules', 'mermaid', 'dist', 'mermaid.min.js');
const checkOnly = process.argv.includes('--check');
const force = process.argv.includes('--force');
const config = JSON.parse(readFileSync(configPath, 'utf8'));

function normalizeMermaidSource(source) {
  let normalized = `${source.trim()}\n`;
  if (!normalized.includes('%%{init:')) {
    normalized = `${config.initDirective}\n${normalized}`;
  }
  return normalized;
}

function outputPathFor(source) {
  const normalized = normalizeMermaidSource(source);
  const digest = createHash('sha256')
    .update(`${config.cacheVersion}\0${normalized}`, 'utf8')
    .digest('hex')
    .slice(0, 16);
  return { normalized, outputPath: join(outputDir, `mermaid-${digest}.svg`) };
}

function discoverDiagrams() {
  const diagrams = new Map();
  const fencePattern = /```mermaid\s*\r?\n([\s\S]*?)```/g;

  for (const sourceDir of sourceDirs) {
    for (const filename of readdirSync(sourceDir).filter((name) => name.endsWith('.md')).sort()) {
      const markdown = readFileSync(join(sourceDir, filename), 'utf8');
      for (const match of markdown.matchAll(fencePattern)) {
        if (match[1].includes('{{stat:')) {
          throw new Error(
            `${join(sourceDir, filename)} contains a dynamic stats placeholder inside Mermaid. ` +
            'Keep diagrams structural and put run-specific values in surrounding text or tables.',
          );
        }
        const rendered = outputPathFor(match[1]);
        diagrams.set(rendered.outputPath, rendered.normalized);
      }
    }
  }
  return diagrams;
}

function detectBrowser() {
  if (process.env.PUPPETEER_EXECUTABLE_PATH) {
    return process.env.PUPPETEER_EXECUTABLE_PATH;
  }
  const candidates = process.platform === 'darwin'
    ? [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Chromium.app/Contents/MacOS/Chromium',
      ]
    : ['/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome'];
  return candidates.find(existsSync);
}

const diagrams = discoverDiagrams();
const missing = [...diagrams.entries()].filter(([outputPath]) => force || !existsSync(outputPath));

if (checkOnly) {
  if (missing.length > 0) {
    console.error(`${missing.length} Mermaid PDF asset(s) are missing or stale.`);
    console.error('Run: npm run docs:render-mermaid');
    process.exit(1);
  }
  console.log(`All ${diagrams.size} Mermaid PDF asset(s) are present.`);
  process.exit(0);
}

if (missing.length === 0) {
  console.log(`Mermaid PDF assets are current; ${diagrams.size} total.`);
  process.exit(0);
}

if (!existsSync(puppeteerPackagePath) || !existsSync(mermaidBundlePath)) {
  console.error('Local Mermaid rendering dependencies are not installed. Run: npm ci');
  process.exit(1);
}

await mkdir(outputDir, { recursive: true });
const browserPath = detectBrowser();
if (browserPath) {
  process.env.PUPPETEER_EXECUTABLE_PATH = browserPath;
}

const puppeteerConfig = JSON.parse(readFileSync(puppeteerConfigPath, 'utf8'));
if (browserPath) {
  puppeteerConfig.executablePath = browserPath;
}

const { default: puppeteer } = await import('puppeteer-core');
const browser = await puppeteer.launch(puppeteerConfig);
try {
  const page = await browser.newPage();
  try {
    await page.setRequestInterception(true);
    page.on('request', (request) => {
      const protocol = new URL(request.url()).protocol;
      if (protocol === 'http:' || protocol === 'https:') {
        request.abort();
      } else {
        request.continue();
      }
    });
    await page.setContent('<!doctype html><html><body></body></html>');
    await page.addScriptTag({ path: mermaidBundlePath });
    await page.evaluate(() => {
      globalThis.mermaid.initialize({ startOnLoad: false });
    });

    for (const [index, [outputPath, source]] of missing.entries()) {
      const svg = await page.evaluate(async ({ definition, diagramId }) => {
        const rendered = await globalThis.mermaid.render(diagramId, definition);
        return rendered.svg;
      }, {
        definition: source,
        diagramId: `docs-mermaid-${index + 1}`,
      });
      writeFileSync(outputPath, svg, 'utf8');
    }
  } finally {
    await page.close();
  }
  console.log(`Rendered ${missing.length} Mermaid PDF asset(s); ${diagrams.size} total.`);
} finally {
  await browser.close();
}
