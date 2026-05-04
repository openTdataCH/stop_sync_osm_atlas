#!/usr/bin/env node

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";

let svgoOptimize = null;
try {
  ({ optimize: svgoOptimize } = await import("svgo"));
} catch {
  // Optional dependency. Raster mode does not need svgo.
}

function printHelp() {
  console.log(`
Usage:
  node scripts/reduce_svg_bandwidth.mjs [options]

Options:
  --input <path>           Input SVG path (default: static/osm.svg)
  --output <path>          Output SVG path (default: <input>.optimized.svg)
  --in-place               Overwrite input file
  --mode <auto|vector|raster>
                           auto: choose smallest output (default)
  --display-width <px>     Intended CSS render width (default: 16)
  --display-height <px>    Intended CSS render height (default: 16)
  --pixel-ratio <n>        Render multiplier for crispness (default: 2)
  --quality <0-100>        Initial WebP quality for raster mode (default: 82)
  --min-quality <0-100>    Lowest quality to try for target size (default: 40)
  --target-reduction <pct> Target reduction percentage (default: 80)
  --vector-float <n>       Float precision for svgo vector mode (default: 0)
  --help                   Show this help

Examples:
  node scripts/reduce_svg_bandwidth.mjs --input static/osm.svg --in-place
  node scripts/reduce_svg_bandwidth.mjs --mode vector --output static/osm.min.svg
  node scripts/reduce_svg_bandwidth.mjs --display-width 16 --display-height 16 --pixel-ratio 2
`);
}

function parseArgs(argv) {
  const args = {
    input: "static/osm.svg",
    output: null,
    inPlace: false,
    mode: "auto",
    displayWidth: 16,
    displayHeight: 16,
    pixelRatio: 2,
    quality: 82,
    minQuality: 40,
    targetReduction: 80,
    vectorFloat: 0,
    help: false,
  };

  const readValue = (index, flag) => {
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) {
      throw new Error(`Missing value for ${flag}`);
    }
    return value;
  };

  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith("--")) {
      throw new Error(`Unknown argument: ${token}`);
    }

    switch (token) {
      case "--help":
        args.help = true;
        break;
      case "--input":
        args.input = readValue(i, token);
        i += 1;
        break;
      case "--output":
        args.output = readValue(i, token);
        i += 1;
        break;
      case "--in-place":
        args.inPlace = true;
        break;
      case "--mode":
        args.mode = readValue(i, token);
        i += 1;
        break;
      case "--display-width":
        args.displayWidth = Number(readValue(i, token));
        i += 1;
        break;
      case "--display-height":
        args.displayHeight = Number(readValue(i, token));
        i += 1;
        break;
      case "--pixel-ratio":
        args.pixelRatio = Number(readValue(i, token));
        i += 1;
        break;
      case "--quality":
        args.quality = Number(readValue(i, token));
        i += 1;
        break;
      case "--min-quality":
        args.minQuality = Number(readValue(i, token));
        i += 1;
        break;
      case "--target-reduction":
        args.targetReduction = Number(readValue(i, token));
        i += 1;
        break;
      case "--vector-float":
        args.vectorFloat = Number(readValue(i, token));
        i += 1;
        break;
      default:
        throw new Error(`Unknown flag: ${token}`);
    }
  }

  return args;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function runCommand(command, args) {
  try {
    execFileSync(command, args, { stdio: ["ignore", "pipe", "pipe"] });
  } catch (error) {
    const stderr = (error.stderr || "").toString().trim();
    const stdout = (error.stdout || "").toString().trim();
    const details = [stderr, stdout].filter(Boolean).join("\n");
    throw new Error(
      details
        ? `Command failed: ${command} ${args.join(" ")}\n${details}`
        : `Command failed: ${command} ${args.join(" ")}`,
    );
  }
}

function parseSvgMetadata(svg) {
  const viewBoxMatch = svg.match(/\bviewBox="([^"]+)"/i);
  const widthMatch = svg.match(/\bwidth="([^"]+)"/i);
  const heightMatch = svg.match(/\bheight="([^"]+)"/i);

  const viewBox = viewBoxMatch ? viewBoxMatch[1] : null;
  let vbWidth = null;
  let vbHeight = null;

  if (viewBox) {
    const parts = viewBox
      .trim()
      .split(/[\s,]+/)
      .map((n) => Number(n));
    if (parts.length === 4 && parts.every((n) => Number.isFinite(n))) {
      vbWidth = parts[2];
      vbHeight = parts[3];
    }
  }

  const parsedWidth = widthMatch ? Number.parseFloat(widthMatch[1]) : null;
  const parsedHeight = heightMatch ? Number.parseFloat(heightMatch[1]) : null;

  return {
    viewBox,
    width: Number.isFinite(parsedWidth) ? parsedWidth : null,
    height: Number.isFinite(parsedHeight) ? parsedHeight : null,
    vbWidth,
    vbHeight,
  };
}

function buildOutputPath(inputPath, outputPath, inPlace) {
  if (inPlace) return inputPath;
  if (outputPath) return outputPath;
  if (inputPath.toLowerCase().endsWith(".svg")) {
    return inputPath.slice(0, -4) + ".optimized.svg";
  }
  return inputPath + ".optimized.svg";
}

function optimizeVector(svg, vectorFloat) {
  if (!svgoOptimize) return null;

  const precision = clamp(Math.trunc(vectorFloat), 0, 5);
  const result = svgoOptimize(svg, {
    multipass: true,
    js2svg: { pretty: false },
    plugins: [
      "preset-default",
      {
        name: "cleanupNumericValues",
        params: { floatPrecision: precision },
      },
      {
        name: "convertPathData",
        params: {
          floatPrecision: precision,
          transformPrecision: precision,
        },
      },
      "sortAttrs",
      "removeDimensions",
    ],
  });

  if (result.error) {
    throw new Error(result.error);
  }

  return result.data;
}

function renderRasterWrappedSvg({
  inputPath,
  metadata,
  displayWidth,
  displayHeight,
  pixelRatio,
  quality,
}) {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "svg-shrink-"));
  const pngPath = path.join(tempDir, "raster.png");
  const webpPath = path.join(tempDir, "raster.webp");

  const targetWidth = Math.max(1, Math.round(displayWidth * pixelRatio));
  const targetHeight = Math.max(1, Math.round(displayHeight * pixelRatio));

  try {
    runCommand("inkscape", [
      inputPath,
      "--export-type=png",
      `--export-filename=${pngPath}`,
      `--export-width=${targetWidth}`,
      `--export-height=${targetHeight}`,
      "--export-background-opacity=0",
    ]);

    runCommand("cwebp", [
      "-quiet",
      "-q",
      String(clamp(Math.trunc(quality), 0, 100)),
      pngPath,
      "-o",
      webpPath,
    ]);

    const webpBase64 = fs.readFileSync(webpPath).toString("base64");
    const imageWidth = metadata.vbWidth || metadata.width || targetWidth;
    const imageHeight = metadata.vbHeight || metadata.height || targetHeight;

    const rootAttrs = metadata.viewBox
      ? `viewBox="${metadata.viewBox}"`
      : `width="${imageWidth}" height="${imageHeight}"`;

    return (
      `<svg xmlns="http://www.w3.org/2000/svg" ${rootAttrs}>` +
      `<image width="${imageWidth}" height="${imageHeight}" preserveAspectRatio="xMidYMid meet" href="data:image/webp;base64,${webpBase64}"/>` +
      `</svg>\n`
    );
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

function percentReduction(beforeBytes, afterBytes) {
  return ((beforeBytes - afterBytes) / beforeBytes) * 100;
}

function formatPercent(value) {
  return `${value.toFixed(2)}%`;
}

function assertMode(mode) {
  if (!["auto", "vector", "raster"].includes(mode)) {
    throw new Error(`Invalid --mode value: ${mode}`);
  }
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    return;
  }

  assertMode(args.mode);

  if (!fs.existsSync(args.input)) {
    throw new Error(`Input file not found: ${args.input}`);
  }

  const originalSvg = fs.readFileSync(args.input, "utf8");
  const metadata = parseSvgMetadata(originalSvg);
  const outputPath = buildOutputPath(args.input, args.output, args.inPlace);
  const originalBytes = Buffer.byteLength(originalSvg, "utf8");
  const targetBytes = Math.floor(
    originalBytes * (1 - clamp(args.targetReduction, 0, 100) / 100),
  );

  const candidates = [];

  if (args.mode === "auto" || args.mode === "vector") {
    if (!svgoOptimize && args.mode === "vector") {
      throw new Error(
        "Vector mode needs svgo. Install it with: npm install --save-dev svgo",
      );
    }

    if (svgoOptimize) {
      const vectorSvg = optimizeVector(originalSvg, args.vectorFloat);
      candidates.push({
        name: "vector",
        content: vectorSvg,
        bytes: Buffer.byteLength(vectorSvg, "utf8"),
      });
    }
  }

  if (args.mode === "auto" || args.mode === "raster") {
    let bestRaster = null;
    const startQuality = clamp(Math.trunc(args.quality), 0, 100);
    const minQuality = clamp(Math.trunc(args.minQuality), 0, 100);

    for (let q = startQuality; q >= minQuality; q -= 5) {
      const rasterSvg = renderRasterWrappedSvg({
        inputPath: args.input,
        metadata,
        displayWidth: args.displayWidth,
        displayHeight: args.displayHeight,
        pixelRatio: args.pixelRatio,
        quality: q,
      });

      const bytes = Buffer.byteLength(rasterSvg, "utf8");
      bestRaster = { name: `raster(q=${q})`, content: rasterSvg, bytes };

      if (bytes <= targetBytes) {
        break;
      }
    }

    if (bestRaster) {
      candidates.push(bestRaster);
    }
  }

  if (candidates.length === 0) {
    throw new Error(
      "No output produced. Install svgo for vector mode or use raster mode with inkscape/cwebp available.",
    );
  }

  const selected = candidates.reduce((smallest, current) =>
    current.bytes < smallest.bytes ? current : smallest,
  );

  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, selected.content, "utf8");

  console.log(`Input: ${args.input}`);
  console.log(`Original size: ${originalBytes} bytes`);
  for (const candidate of candidates) {
    const reduction = percentReduction(originalBytes, candidate.bytes);
    console.log(
      `Candidate ${candidate.name}: ${candidate.bytes} bytes (${formatPercent(reduction)} smaller)`,
    );
  }
  const selectedReduction = percentReduction(originalBytes, selected.bytes);
  console.log(
    `Selected: ${selected.name} -> ${outputPath} (${formatPercent(selectedReduction)} smaller)`,
  );

  if (selected.bytes > targetBytes) {
    console.warn(
      `Target not fully reached (${args.targetReduction}% requested). ` +
        `Try lower --quality, lower --pixel-ratio, or smaller --display-width/--display-height.`,
    );
  }
}

try {
  main();
} catch (error) {
  console.error(`Error: ${error.message}`);
  process.exitCode = 1;
}
