// TrackFlow UI baseline runner (U-A5).
//
//   node tests/ui/run.mjs                 -> website + backoffice + talent
//   node tests/ui/run.mjs website backoffice
//
// Exit code 0 only if every check of every selected suite passed. Output goes to stdout only:
// no reports, screenshots or logs are written to the repository.

import path from "node:path";
import { fileURLToPath } from "node:url";
import { killAll } from "./lib/harness.mjs";

const SUITES = ["website", "backoffice", "talent"];
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

const major = Number(process.versions.node.split(".")[0]);
if (major < 22) {
  console.error(`Node >= 22 required (built-in WebSocket); found ${process.version}`);
  process.exit(2);
}

const selected = process.argv.slice(2);
const unknown = selected.filter((s) => !SUITES.includes(s));
if (unknown.length) {
  console.error(`Unknown suite(s): ${unknown.join(", ")}. Available: ${SUITES.join(", ")}`);
  process.exit(2);
}
const toRun = selected.length ? SUITES.filter((s) => selected.includes(s)) : SUITES;

// Never leave Chrome / next dev / uvicorn behind, whatever happens.
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => { killAll(); process.exit(130); });
process.on("exit", killAll);
const globalTimeout = setTimeout(() => { console.error("GLOBAL TIMEOUT (20 min)"); killAll(); process.exit(3); }, 20 * 60 * 1000);
globalTimeout.unref();

const all = [];
for (const name of toRun) {
  console.log(`\n=== ${name} ===`);
  const t0 = Date.now();
  const { run } = await import(`./${name}.mjs`);
  const rec = await run({ repoRoot });
  all.push(...rec.checks);
  console.log(`--- ${name}: ${rec.checks.filter((c) => c.ok).length}/${rec.checks.length} passed (${((Date.now() - t0) / 1000).toFixed(1)}s)`);
}

const failed = all.filter((c) => !c.ok);
console.log(`\n=== UI BASELINE: ${all.length} checks, ${all.length - failed.length} passed, ${failed.length} failed ===`);
for (const name of toRun) {
  const s = all.filter((c) => c.suite === name);
  console.log(`  ${name.padEnd(11)} ${s.filter((c) => c.ok).length}/${s.length}`);
}
if (failed.length) {
  console.log("\nFailed checks:");
  for (const c of failed) console.log(`  ${c.suite} ${c.id}: ${c.description}`);
}
process.exitCode = failed.length ? 1 : 0;
