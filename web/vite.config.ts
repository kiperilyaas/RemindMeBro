/// <reference types="vitest" />
import { dirname, resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";

// Three single-file builds, committed prebuilt (the Run & Go launcher never needs Node.js).
// Pick one with --mode:  hub (default) | unilearn | unisis
const TARGETS = {
  hub: { input: "index.html", out: "frontend/app" },                     // student + lecturer hub, served at /
  unilearn: { input: "apps/unilearn/index.html", out: "unilearn/static/staff" },  // UniLearn /staff
  unisis: { input: "apps/unisis/index.html", out: "unisis/static/staff" },        // UniSIS /staff
} as const;

export default defineConfig(({ mode }) => {
  const target = TARGETS[(mode in TARGETS ? mode : "hub") as keyof typeof TARGETS];
  const projectRoot = process.env.RMB_PROJECT_ROOT || resolve(__dirname, "..");
  return {
    // the folder of the entry HTML is the Vite root, so every build is written as <outDir>/index.html
    root: resolve(__dirname, dirname(target.input)),
    plugins: [react(), viteSingleFile()],
    build: { outDir: resolve(projectRoot, target.out), emptyOutDir: true, },
    server: { proxy: { "/api": "http://127.0.0.1:8000", "/media": "http://127.0.0.1:8000" } },
    test: { environment: "jsdom", globals: true, root: __dirname, setupFiles: [resolve(__dirname, "src/test/setup.ts")] },
  };
});
