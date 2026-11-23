// Google Apps Script: Extensions > Apps Script in the target Sheet, paste,
// Deploy > New deployment > Web app (execute as me). Put the URL in SHEET_WEBHOOK_URL.
function doPost(e) {
  const rows = JSON.parse(e.postData.contents);
  if (!Array.isArray(rows)) return ContentService.createTextOutput("bad payload");
  const sheet = SpreadsheetApp.getActive().getSheetByName("digest") ||
                SpreadsheetApp.getActive().insertSheet("digest");
  if (sheet.getLastRow() === 0) sheet.appendRow(["week", "intern", "logged_days", "hours", "alerts"]);
  // idempotent: re-running the same week replaces that week's rows
  const data = sheet.getDataRange().getValues();
  const week = rows.length ? rows[0].week : null;
  for (let i = data.length - 1; i >= 1; i--) if (String(data[i][0]) === week) sheet.deleteRow(i + 1);
  rows.forEach(r => sheet.appendRow([r.week, r.intern, r.logged_days, r.hours ?? "", r.alerts]));
  return ContentService.createTextOutput("ok " + rows.length);
}
