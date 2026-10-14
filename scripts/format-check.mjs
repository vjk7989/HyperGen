import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import * as prettier from "prettier";

const baseRef = process.env.FORMAT_BASE_REF?.trim() || null;

function git(args, { allowFailure = false } = {}) {
  const result = spawnSync("git", args, {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  if (!allowFailure && result.status !== 0) {
    process.stderr.write(result.stdout);
    process.stderr.write(result.stderr);
    process.exit(result.status ?? 1);
  }
  return result;
}

function nulPaths(args) {
  const result = git(args);
  return result.stdout.split("\0").filter(Boolean);
}

const candidates = new Set([
  ...(baseRef
    ? nulPaths(["diff", "--name-only", "-z", "--diff-filter=ACMR", `${baseRef}...HEAD`])
    : []),
  ...nulPaths(["diff", "--name-only", "-z", "--diff-filter=ACMR", "HEAD"]),
  ...nulPaths(["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"]),
  ...nulPaths(["ls-files", "--others", "--exclude-standard", "-z"]),
]);

let whitespaceFailed = false;
for (const args of [
  ...(baseRef ? [["diff", "--check", `${baseRef}...HEAD`]] : []),
  ["diff", "--check"],
  ["diff", "--cached", "--check"],
]) {
  const result = git(args, { allowFailure: true });
  if (result.status !== 0) {
    whitespaceFailed = true;
    process.stderr.write(result.stdout);
    process.stderr.write(result.stderr);
  }
}

const failures = [];
let checked = 0;
let skippedBaselineDebt = 0;
const baselineRef = baseRef ?? "HEAD";

for (const file of [...candidates].sort()) {
  if (!existsSync(file)) continue;
  if (file.startsWith(".codebase-memory/")) continue;
  if (file.endsWith(".md")) continue;

  const info = await prettier.getFileInfo(file, { ignorePath: ".prettierignore" });
  if (info.ignored || info.inferredParser === null) continue;

  const config = (await prettier.resolveConfig(file)) ?? {};
  const options = { ...config, filepath: file };
  const current = readFileSync(file, "utf8");
  const baseline = git(["show", `${baselineRef}:${file}`], { allowFailure: true });

  if (baseline.status === 0 && !(await prettier.check(baseline.stdout, options))) {
    skippedBaselineDebt += 1;
    continue;
  }

  checked += 1;
  if (!(await prettier.check(current, options))) failures.push(file);
}

if (failures.length > 0) {
  process.stderr.write("Changed files need Prettier formatting:\n");
  for (const file of failures) process.stderr.write(`  ${file}\n`);
}

console.log(
  `Format check: ${checked} checked, ${skippedBaselineDebt} skipped due to pre-existing formatting debt.`,
);

if (whitespaceFailed || failures.length > 0) process.exit(1);
