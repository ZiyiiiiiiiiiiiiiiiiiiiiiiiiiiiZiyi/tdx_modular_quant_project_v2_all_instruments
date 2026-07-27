import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const workDir = path.dirname(fileURLToPath(import.meta.url));
const dataDir = path.resolve(process.argv[2] || workDir);
const outputPath = path.resolve(
  process.argv[3] || path.join(dataDir, "SCAP_持仓逐因子曲线.xlsx"),
);
const payload = JSON.parse(await fs.readFile(path.join(dataDir, "workbook_payload.json"), "utf8"));
const workbook = Workbook.create();

const navy = "#17365D";
const blue = "#D9EAF7";
const green = "#E2F0D9";
const amber = "#FFF2CC";
const red = "#FCE4D6";
const gray = "#E7E6E6";
const white = "#FFFFFF";

function columnName(index) {
  let value = index + 1;
  let result = "";
  while (value > 0) {
    const rem = (value - 1) % 26;
    result = String.fromCharCode(65 + rem) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function writeRecords(sheet, startRow, startCol, records, preferredColumns = null) {
  const columns = preferredColumns || (records.length ? Object.keys(records[0]) : []);
  if (!columns.length) return { columns, lastRow: startRow, lastCol: startCol };
  const rows = [columns, ...records.map(row => columns.map(col => row[col] ?? null))];
  sheet.getRangeByIndexes(startRow, startCol, rows.length, columns.length).values = rows;
  return {
    columns,
    lastRow: startRow + rows.length - 1,
    lastCol: startCol + columns.length - 1,
  };
}

function styleTable(sheet, topRow, leftCol, rowCount, colCount) {
  const header = sheet.getRangeByIndexes(topRow, leftCol, 1, colCount);
  header.format.fill = navy;
  header.format.font = { bold: true, color: white };
  header.format.wrapText = true;
  const body = sheet.getRangeByIndexes(topRow + 1, leftCol, Math.max(rowCount - 1, 1), colCount);
  body.format.borders = { preset: "inside", style: "thin", color: "#D9E2F3" };
}

const summary = workbook.worksheets.add("Summary");
summary.showGridLines = false;
summary.getRange("A1:H2").merge();
summary.getRange("A1").values = [["SCAP 持仓逐因子评分曲线"]];
summary.getRange("A1:H2").format.fill = navy;
summary.getRange("A1:H2").format.font = { bold: true, color: white, size: 18 };
summary.getRange("A1:H2").format.verticalAlignment = "center";
summary.getRange("A4:B4").values = [["指标", "结果"]];
summary.getRange("A4:B4").format.fill = navy;
summary.getRange("A4:B4").format.font = { bold: true, color: white };
const summaryLabels = [
  "交易日",
  "初始资金",
  "最终资金",
  "总收益",
  "持有5只的天数",
  "5只且仓位缺口>5%的天数",
  "平均实际仓位",
  "5只时平均仓位缺口",
  "基准期末净值",
  "基准总收益",
  "策略-基准收益差（百分点）",
  "闭合交易数",
  "已实现PnL",
  "因子数",
  "持仓股票数",
  "持仓-日期因子覆盖率",
];
summary.getRange(`A5:A${4 + summaryLabels.length}`).values = summaryLabels.map(x => [x]);

const daily = workbook.worksheets.add("Daily Constraints");
daily.showGridLines = false;
const dailyWrite = writeRecords(daily, 0, 0, payload.daily_constraints);
styleTable(daily, 0, 0, payload.daily_constraints.length + 1, dailyWrite.columns.length);
daily.freezePanes.freezeRows(1);
const dCol = Object.fromEntries(dailyWrite.columns.map((name, i) => [name, columnName(i)]));
const dLast = payload.daily_constraints.length + 1;

const trades = workbook.worksheets.add("Closed Trades");
trades.showGridLines = false;
const tradeColumns = [
  "trade_id", "symbol", "entry_date", "exit_date", "holding_days",
  "entry_price", "exit_net_price", "realized_pnl_amount", "realized_pnl_pct",
  "is_win", "entry_matrix_score_at_buy", "sell_reason", "position_exit_reason_at_sell",
];
const tradeWrite = writeRecords(trades, 0, 0, payload.closed_trades, tradeColumns);
styleTable(trades, 0, 0, payload.closed_trades.length + 1, tradeColumns.length);
trades.freezePanes.freezeRows(1);
trades.getRange(`F2:I${payload.closed_trades.length + 1}`).format.numberFormat = "0.00";
trades.getRange(`I2:I${payload.closed_trades.length + 1}`).format.numberFormat = "0.00%";

const sell = workbook.worksheets.add("Sell Diagnostics");
sell.showGridLines = false;
const sellColumns = [
  "date", "symbol", "holding_days", "unrealized_return", "mfe", "mae",
  "entry_matrix_score", "trend_stability_score", "volume_health_score",
  "downtrend_decay_score", "follow_through_score", "entry_thesis",
  "entry_module_support", "current_module_support", "support_decay",
  "signal_failure_exit", "thesis_failure_exit", "position_exit_reason",
];
writeRecords(sell, 0, 0, payload.active_sell_diagnostics, sellColumns);
styleTable(sell, 0, 0, payload.active_sell_diagnostics.length + 1, sellColumns.length);
sell.freezePanes.freezeRows(1);
sell.getRange(`D2:O${payload.active_sell_diagnostics.length + 1}`).format.numberFormat = "0.00%";

const factorMap = workbook.worksheets.add("Factor Map");
factorMap.showGridLines = false;
writeRecords(factorMap, 0, 0, payload.factor_meta, ["model_name", "factor_role", "factor_module"]);
styleTable(factorMap, 0, 0, payload.factor_meta.length + 1, 3);
factorMap.freezePanes.freezeRows(1);

const bFormulas = [
  `=ROWS('Daily Constraints'!${dCol.date}2:${dCol.date}${dLast})`,
  `='Daily Constraints'!${dCol.nominal_nav}2`,
  `=INDEX('Daily Constraints'!${dCol.nominal_nav}2:${dCol.nominal_nav}${dLast},ROWS('Daily Constraints'!${dCol.nominal_nav}2:${dCol.nominal_nav}${dLast}))`,
  "=B7/B6-1",
  `=COUNTIF('Daily Constraints'!${dCol.holding_count}2:${dCol.holding_count}${dLast},\">=5\")`,
  `=COUNTIFS('Daily Constraints'!${dCol.holding_count}2:${dCol.holding_count}${dLast},\">=5\",'Daily Constraints'!${dCol.exposure_gap}2:${dCol.exposure_gap}${dLast},\">0.05\")`,
  `=AVERAGE('Daily Constraints'!${dCol.actual_exposure}2:${dCol.actual_exposure}${dLast})`,
  `=IFERROR(AVERAGEIF('Daily Constraints'!${dCol.holding_count}2:${dCol.holding_count}${dLast},\">=5\",'Daily Constraints'!${dCol.exposure_gap}2:${dCol.exposure_gap}${dLast}),0)`,
  `=INDEX('Daily Constraints'!${dCol.benchmark_net_value}2:${dCol.benchmark_net_value}${dLast},ROWS('Daily Constraints'!${dCol.benchmark_net_value}2:${dCol.benchmark_net_value}${dLast}))/'Daily Constraints'!${dCol.benchmark_net_value}2`,
  "=B13-1",
  "=B8-B14",
  `=MAX(COUNTA('Closed Trades'!A:A)-1,0)`,
  `=SUM('Closed Trades'!H2:H${payload.closed_trades.length + 1})`,
  payload.summary.factor_model_count,
  payload.summary.held_symbol_count,
  `=IF(${payload.summary.holding_symbol_days}=0,0,${payload.summary.covered_holding_symbol_days}/${payload.summary.holding_symbol_days})`,
];
summary.getRange(`B5:B${4 + bFormulas.length}`).formulas = bFormulas.map(value =>
  typeof value === "string" && value.startsWith("=") ? [value] : [null]
);
for (let i = 0; i < bFormulas.length; i++) {
  if (typeof bFormulas[i] !== "string" || !bFormulas[i].startsWith("=")) {
    summary.getCell(4 + i, 1).values = [[bFormulas[i]]];
  }
}
summary.getRange("B6:B7").format.numberFormat = "¥#,##0.00;[Red](¥#,##0.00);-";
summary.getRange("B8:B8").format.numberFormat = "0.00%";
summary.getRange("B11:B15").format.numberFormat = "0.00%";
summary.getRange("B17:B17").format.numberFormat = "¥#,##0.00;[Red](¥#,##0.00);-";
summary.getRange("B20:B20").format.numberFormat = "0.00%";
summary.getRange("A22:H22").merge();
summary.getRange("A22").values = [["说明：本工作簿逐日保存每只历史持仓的单因子原始分、角色和权重；它是只读诊断，不取得交易决策权。"]];
summary.getRange("A22:H22").format.fill = amber;
summary.getRange("A22:H22").format.font = { bold: true, color: "#7F6000" };
summary.getRange("A24:H24").merge();
summary.getRange("A24").values = [[`数据源：${payload.summary.source_run}`]];
summary.getRange("A24:H24").format.font = { color: "#008000", italic: true };
summary.getRange("A24:H24").format.wrapText = true;
summary.getRange("A24:H24").format.rowHeight = 42;
summary.getRange("A26:H26").merge();
summary.getRange("A26").values = [["蓝色表头=源数据；黑色公式=可追溯计算；各股票页前两张图为波动最大的12个单因子曲线，右侧矩阵保存全部74个因子。"]];
summary.getRange("A26:H26").format.fill = blue;
summary.getRange("A26:H26").format.wrapText = true;

const symbolSheetNames = [];
for (const item of payload.symbols) {
  const sheetName = item.symbol.slice(0, 31);
  symbolSheetNames.push(sheetName);
  const sheet = workbook.worksheets.add(sheetName);
  sheet.showGridLines = false;
  sheet.getRange("A1:N1").merge();
  sheet.getRange("A1").values = [[`${item.symbol} · 单因子5日预测收益曲线`]];
  sheet.getRange("A1:N1").format.fill = navy;
  sheet.getRange("A1:N1").format.font = { bold: true, color: white, size: 15 };
  const factors = item.factors;
  const factorIndex = Object.fromEntries(factors.map((name, i) => [name, i]));
  const top = item.top_factors.slice(0, 12);
  const helperOne = [["date", ...top.slice(0, 6)]];
  const helperTwo = [["date", ...top.slice(6, 12)]];
  for (let r = 0; r < item.dates.length; r++) {
    helperOne.push([new Date(`${item.dates[r]}T00:00:00`), ...top.slice(0, 6).map(name => item.values[r][factorIndex[name]] ?? null)]);
    helperTwo.push([new Date(`${item.dates[r]}T00:00:00`), ...top.slice(6, 12).map(name => item.values[r][factorIndex[name]] ?? null)]);
  }
  const helperStart = 41;
  sheet.getRangeByIndexes(helperStart, 0, helperOne.length, 7).values = helperOne;
  sheet.getRangeByIndexes(helperStart, 7, helperTwo.length, 7).values = helperTwo;
  styleTable(sheet, helperStart, 0, helperOne.length, 14);
  sheet.getRangeByIndexes(helperStart + 1, 0, item.dates.length, 1).format.numberFormat = "yyyy-mm-dd";
  sheet.getRangeByIndexes(helperStart + 1, 7, item.dates.length, 1).format.numberFormat = "yyyy-mm-dd";
  sheet.getRangeByIndexes(helperStart + 1, 1, item.dates.length, 6).format.numberFormat = "0.00%";
  sheet.getRangeByIndexes(helperStart + 1, 8, item.dates.length, 6).format.numberFormat = "0.00%";

  const matrixHeaders = ["date", "price", "unrealized_return", ...factors];
  const matrixRows = [matrixHeaders];
  for (let r = 0; r < item.dates.length; r++) {
    matrixRows.push([
      new Date(`${item.dates[r]}T00:00:00`),
      item.price[r] ?? null,
      item.unrealized_return[r] ?? null,
      ...item.values[r],
    ]);
  }
  sheet.getRangeByIndexes(helperStart, 15, matrixRows.length, matrixHeaders.length).values = matrixRows;
  styleTable(sheet, helperStart, 15, matrixRows.length, matrixHeaders.length);
  sheet.getRangeByIndexes(helperStart + 1, 15, item.dates.length, 1).format.numberFormat = "yyyy-mm-dd";
  sheet.getRangeByIndexes(helperStart + 1, 16, item.dates.length, 1).format.numberFormat = "0.00";
  sheet.getRangeByIndexes(helperStart + 1, 17, item.dates.length, factors.length + 1).format.numberFormat = "0.00%";
  sheet.freezePanes.freezeRows(helperStart + 1);

  const firstEnd = helperStart + helperOne.length;
  const chart1 = sheet.charts.add("line", sheet.getRange(`A42:G${firstEnd}`));
  chart1.titleText = `${item.symbol}｜波动最大因子 1-6`;
  chart1.hasLegend = true;
  chart1.legend.position = "bottom";
  chart1.setPosition("A3", "N19");
  const chart2 = sheet.charts.add("line", sheet.getRange(`H42:N${firstEnd}`));
  chart2.titleText = `${item.symbol}｜波动最大因子 7-12`;
  chart2.hasLegend = true;
  chart2.legend.position = "bottom";
  chart2.setPosition("A21", "N37");
}

const checks = workbook.worksheets.add("Checks");
checks.showGridLines = false;
checks.getRange("A1:F1").values = [["检查项", "实际", "预期", "差异", "状态", "说明"]];
checks.getRange("A1:F1").format.fill = navy;
checks.getRange("A1:F1").format.font = { bold: true, color: white };
checks.getRange("A2:A5").values = [
  ["持仓-日期因子覆盖"],
  ["因子数量"],
  ["活跃卖出行数"],
  ["股票工作表数量"],
];
checks.getRange("B2:B5").formulas = [
  [`=${payload.summary.covered_holding_symbol_days}`],
  [`=${payload.summary.factor_model_count}`],
  [`=MAX(COUNTA('Sell Diagnostics'!A:A)-1,0)`],
  [`=${symbolSheetNames.length}`],
];
checks.getRange("C2:C5").values = [
  [payload.summary.holding_symbol_days],
  [payload.summary.factor_model_count],
  [payload.summary.active_exit_rows ?? payload.summary.active_signal_failure_rows],
  [payload.summary.held_symbol_count],
];
checks.getRange("D2:D5").formulas = [["=B2-C2"], ["=B3-C3"], ["=B4-C4"], ["=B5-C5"]];
checks.getRange("E2:E5").formulas = [
  ['=IF(D2=0,"OK","FAIL")'],
  ['=IF(D3=0,"OK","FAIL")'],
  ['=IF(D4=0,"OK","FAIL")'],
  ['=IF(D5=0,"OK","FAIL")'],
];
checks.getRange("F2:F5").values = [
  ["每一个持仓股票-日期均应有74条因子记录"],
  ["固定因子柜模型数"],
  ["与运行中全部实际退出状态行数一致"],
  ["每只历史持仓股票一个曲线页"],
];
styleTable(checks, 0, 0, 5, 6);

for (const sheet of [summary, daily, trades, sell, factorMap, checks]) {
  const used = sheet.getUsedRange();
  used.format.font = { name: "Aptos", size: 10 };
  used.format.autofitColumns();
  used.format.autofitRows();
}
summary.getRange("A:A").format.columnWidth = 32;
summary.getRange("B:B").format.columnWidth = 20;
daily.getUsedRange().format.columnWidth = 16;
trades.getUsedRange().format.columnWidth = 16;
sell.getUsedRange().format.columnWidth = 16;
daily.getRange("1:1").format.rowHeight = 42;
trades.getRange("1:1").format.rowHeight = 42;
sell.getRange("1:1").format.rowHeight = 42;
factorMap.getRange("A:A").format.columnWidth = 42;
factorMap.getRange("B:C").format.columnWidth = 22;
checks.getRange("A:E").format.columnWidth = 20;
checks.getRange("F:F").format.columnWidth = 48;

const out = await SpreadsheetFile.exportXlsx(workbook);
await out.save(outputPath);

const inspect = await workbook.inspect({
  kind: "table",
  range: "Summary!A1:H26",
  include: "values,formulas",
  tableMaxRows: 30,
  tableMaxCols: 10,
});
console.log(inspect.ndjson);
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);
if (["1", "true", "yes"].includes(String(process.env.TDX_FACTOR_WORKBOOK_RENDER || "").toLowerCase())) {
  for (const sheetName of ["Summary", "Daily Constraints", "Closed Trades", "Sell Diagnostics", "Factor Map", ...symbolSheetNames, "Checks"]) {
    const preview = await workbook.render({ sheetName, range: sheetName === "Summary" ? "A1:H26" : undefined, autoCrop: "all", scale: 0.8, format: "png" });
    const bytes = new Uint8Array(await preview.arrayBuffer());
    await fs.writeFile(path.join(dataDir, `preview_${sheetName}.png`), bytes);
  }
}
console.log(JSON.stringify({ workbook: outputPath, status: "ok" }));
