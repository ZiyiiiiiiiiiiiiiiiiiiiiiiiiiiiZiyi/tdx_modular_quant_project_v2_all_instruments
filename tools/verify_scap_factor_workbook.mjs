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
  renderPaths,
};
await fs.writeFile(
  path.join(renderDir, "workbook_visual_verification.json"),
  JSON.stringify(report, null, 2),
  "utf8",
);
console.log(JSON.stringify(report));
if (report.formulaErrorCount > 0) {
  process.exitCode = 1;
}
