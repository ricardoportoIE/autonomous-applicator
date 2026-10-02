import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import v8ToIstanbul from "v8-to-istanbul";
import coverage from "istanbul-lib-coverage";
import reporting from "istanbul-lib-report";
import reports from "istanbul-reports";

const folder = "test-results/frontend-coverage";
const map = coverage.createCoverageMap({});
for (const filename of await fs.readdir(folder)) {
  if (!filename.endsWith(".json")) continue;
  const record = JSON.parse(
    await fs.readFile(path.join(folder, filename), "utf8"),
  );
  for (const script of record.result) {
    const sourcePath = fileURLToPath(script.url);
    if (script.source !== (await fs.readFile(sourcePath, "utf8"))) continue;
    const converter = v8ToIstanbul(sourcePath, 0, { source: script.source });
    await converter.load();
    converter.applyCoverage(script.functions);
    map.merge(converter.toIstanbul());
  }
}
const context = reporting.createContext({
  dir: "test-results/frontend-report",
  coverageMap: map,
});
for (const format of ["text", "json-summary", "html"])
  reports.create(format).execute(context);
for (const filename of ["app.js", "ui.js"]) {
  if (!map.files().some((file) => path.basename(file) === filename))
    throw new Error(`Missing browser coverage for ${filename}`);
}
const summary = map.getCoverageSummary();
// Browser tests measure the actual dashboard. Helpers have separate 100% unit coverage.
if (summary.lines.pct < 90 || summary.branches.pct < 80) {
  throw new Error(
    "Browser coverage must reach 90% of lines and 80% of branches.",
  );
}
