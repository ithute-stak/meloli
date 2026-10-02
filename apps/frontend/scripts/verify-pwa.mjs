import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const required = [
  "app/manifest.ts",
  "public/sw.js",
  "public/icons/meloli-pwa.svg",
  "public/icons/meloli-pwa-maskable.svg",
  "app/components/PwaRegistration.tsx",
];
const missing = required.filter(path => !existsSync(join(root, path)));
if (missing.length) {
  console.error("Missing PWA files:", missing.join(", "));
  process.exit(1);
}
const manifest = readFileSync(join(root, "app/manifest.ts"), "utf8");
const layout = readFileSync(join(root, "app/layout.tsx"), "utf8");
const serviceWorker = readFileSync(join(root, "public/sw.js"), "utf8");
for (const [label, ok] of [
  ["standalone display mode", manifest.includes('display: "standalone"')],
  ["theme color", manifest.includes('theme_color: "#070a45"')],
  ["service-worker registration", layout.includes("<PwaRegistration")],
  ["offline shell cache", serviceWorker.includes('CACHE_NAME') && serviceWorker.includes('caches.open')],
]) {
  if (!ok) {
    console.error("PWA verification failed:", label);
    process.exit(1);
  }
}
console.log("PWA verification passed.");
