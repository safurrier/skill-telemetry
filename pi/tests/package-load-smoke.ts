import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  DefaultResourceLoader,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

async function loadPackage(packagePath: string, agentDir: string) {
  const loader = new DefaultResourceLoader({
    cwd: agentDir,
    agentDir,
    settingsManager: SettingsManager.inMemory(),
    additionalExtensionPaths: [packagePath],
    noExtensions: true,
    noSkills: true,
    noPromptTemplates: true,
    noThemes: true,
    noContextFiles: true,
  });
  await loader.reload();
  return loader.getExtensions();
}

const tempRoot = await mkdtemp(resolve(tmpdir(), "skill-telemetry-pi-load-"));
try {
  const positive = await loadPackage(packageRoot, resolve(tempRoot, "positive"));
  assert.equal(positive.extensions.length, 1);
  assert.deepEqual(positive.errors, []);
  assert.equal(
    positive.extensions[0]?.resolvedPath,
    resolve(packageRoot, "pi/src/index.ts"),
  );

  const brokenPackage = resolve(tempRoot, "broken-package");
  await (await import("node:fs/promises")).mkdir(brokenPackage);
  await writeFile(
    resolve(brokenPackage, "package.json"),
    JSON.stringify({ pi: { extensions: ["./broken-extension.ts"] } }),
  );
  await writeFile(resolve(brokenPackage, "broken-extension.ts"), "export default (");
  const negative = await loadPackage(brokenPackage, resolve(tempRoot, "negative"));
  assert.equal(negative.extensions.length, 0);
  assert.equal(negative.errors.length, 1);
  assert.match(negative.errors[0]?.error ?? "", /error|unexpected|failed/i);

  console.log("Pi package-load smoke passed (positive and broken-package control).");
} finally {
  await rm(tempRoot, { force: true, recursive: true });
}
