#!/usr/bin/env node
/**
 * Zero-dependency build script that produces unpacked Manifest V3 bundles for:
 *   - extension/dist/chrome   (Chrome / Edge on Windows & macOS)
 *   - extension/dist/firefox  (Firefox on Windows & macOS)
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const EXT_ROOT = path.resolve(__dirname, "..");
const SRC_DIR = path.join(EXT_ROOT, "src");
const DIST_DIR = path.join(EXT_ROOT, "dist");

const baseManifest = JSON.parse(
  fs.readFileSync(path.join(EXT_ROOT, "manifest.base.json"), "utf-8")
);

function copyRecursive(src, dest) {
  const stat = fs.statSync(src);
  if (stat.isDirectory()) {
    fs.mkdirSync(dest, { recursive: true });
    for (const entry of fs.readdirSync(src)) {
      copyRecursive(path.join(src, entry), path.join(dest, entry));
    }
  } else {
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.copyFileSync(src, dest);
  }
}

function buildTarget(targetName, manifestOverrides) {
  const outDir = path.join(DIST_DIR, targetName);
  fs.rmSync(outDir, { recursive: true, force: true });
  fs.mkdirSync(outDir, { recursive: true });

  copyRecursive(SRC_DIR, outDir);

  const manifest = {
    ...baseManifest,
    ...manifestOverrides,
  };
  fs.writeFileSync(
    path.join(outDir, "manifest.json"),
    JSON.stringify(manifest, null, 2) + "\n",
    "utf-8"
  );
}

buildTarget("chrome", {
  background: {
    service_worker: "background.js",
    type: "module",
  },
});

buildTarget("firefox", {
  background: {
    scripts: ["background.js"],
    type: "module",
  },
  browser_specific_settings: {
    gecko: {
      id: "truepricememory@ihavethereceipts.local",
      strict_min_version: "115.0",
    },
  },
});

console.log("Built extension/dist/chrome and extension/dist/firefox");
