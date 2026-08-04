import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = path.resolve(process.argv[2]);
const renderDir = path.resolve(process.argv[3]);
await fs.mkdir(renderDir, { recursive: true });

const blob = await FileBlob.load(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(blob);
const sheetNames = workbook.worksheets.items.map((sheet) => sheet.name);

const errorScan = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 500 },
  summary: "SCAP factor workbook formula error scan",
});
const errorRecords = errorScan.ndjson
  .split("\n")
  .map((line) => line.trim())
  .filter(Boolean)
  .map((line) => JSON.parse(line))
  .filter((item) => item.kind === "match");

const summaryInspect = await workbook.inspect({
  kind: "table",
  sheetId: "Summary",
  range: "A1:B20",
  include: "values,formulas",
  tableMaxRows: 24,
  tableMaxCols: 4,
  maxChars: 12000,
});
const checksInspect = await workbook.inspect({
  kind: "table",
  sheetId: "Checks",
  range: "A1:F6",
  include: "values,formulas",
  tableMaxRows: 8,
  tableMaxCols: 8,
  maxChars: 12000,
});

const renderPaths = [];
for (const sheetName of sheetNames) {
  const preview = await workbook.render({
    sheetName,
    autoCrop: "all",
    scale: 0.8,
    format: "png",
  });
  const safeName = sheetName.replace(/[<>:"/\\|?*]/g, "_");
  const outputPath = path.join(renderDir, `${safeName}.png`);
  await fs.writeFile(outputPath, new Uint8Array(await preview.arrayBuffer()));
  renderPaths.push(outputPath);
}

const report = {
  workbook: workbookPath,
  sheetNames,
  sheetCount: sheetNames.length,
  formulaErrorCount: errorRecords.length,
  formulaErrorScan: errorScan.ndjson,
  summaryInspect: summaryInspect.ndjson,
  checksInspect: checksInspect.ndjson,
  checksFailureCount: (checksInspect.ndjson.match(/FAIL/g) || []).length,
  renderPaths,
};
await fs.writeFile(
  path.join(renderDir, "workbook_visual_verification.json"),
  JSON.stringify(report, null, 2),
  "utf8",
);
console.log(JSON.stringify(report));
if (report.formulaErrorCount > 0 || report.checksFailureCount > 0) {
  process.exitCode = 1;
}
