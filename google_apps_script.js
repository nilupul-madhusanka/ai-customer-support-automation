/**
 * Paste into Extensions > Apps Script in the linked response spreadsheet.
 * Run setupFormIntake once and authorize it. This installs the spreadsheet
 * submit trigger and imports valid submissions that were missed previously.
 */
var INQUIRY_FIELDS = ["id", "received_at", "customer_name", "customer_email", "message", "status",
  "category", "priority", "summary", "draft_reply", "final_reply", "reviewed_at",
  "error_message", "email_status", "emailed_at"];

function onFormSubmit(e) {
  if (!e || !e.range || !e.source) {
    throw new Error("Use the spreadsheet On form submit trigger. To set up or recover responses, run setupFormIntake.");
  }
  importResponseRow_(e.source, e.range.getSheet(), e.range.getRow());
}

function setupFormIntake() {
  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  validateInquiries_(spreadsheet);
  var validTrigger = null;
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (trigger.getHandlerFunction() !== "onFormSubmit") return;
    var correct = trigger.getEventType() === ScriptApp.EventType.ON_FORM_SUBMIT &&
      trigger.getTriggerSource() === ScriptApp.TriggerSource.SPREADSHEETS &&
      trigger.getTriggerSourceId() === spreadsheet.getId();
    if (correct && !validTrigger) validTrigger = trigger;
    else ScriptApp.deleteTrigger(trigger);
  });
  if (!validTrigger) {
    ScriptApp.newTrigger("onFormSubmit").forSpreadsheet(spreadsheet).onFormSubmit().create();
  }
  Logger.log("Spreadsheet form-submit trigger is installed.");
  importPendingFormResponses();
}

function importPendingFormResponses() {
  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  validateInquiries_(spreadsheet);
  var imported = 0;
  var skipped = 0;
  var sources = 0;
  spreadsheet.getSheets().forEach(function(sheet) {
    if (sheet.getName() === "Inquiries" || sheet.getLastRow() < 1) return;
    var headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0].map(normalizeHeader_);
    if (headers.indexOf("customer name") < 0 || headers.indexOf("describe your issue") < 0 ||
        headers.indexOf("customer email") < 0 || headers.indexOf("timestamp") < 0) return;
    sources++;
    for (var row = 2; row <= sheet.getLastRow(); row++) {
      try {
        if (importResponseRow_(spreadsheet, sheet, row)) imported++;
        else skipped++;
      } catch (error) {
        skipped++;
        Logger.log("Response row " + row + " was not imported: " + error.message);
      }
    }
  });
  if (!sources) throw new Error("No form-response tab found. Check the form question titles and linked spreadsheet.");
  Logger.log("Imported " + imported + " NEW tickets; skipped " + skipped + " already imported or incomplete responses.");
}

function normalizeHeader_(value) { return String(value).trim().toLowerCase(); }

function extractResponse_(headers, cells) {
  var normalized = headers.map(normalizeHeader_);
  function answers(title) {
    return cells.filter(function(value, index) { return normalized[index] === title; })
      .map(function(value) { return String(value == null ? "" : value).trim(); })
      .filter(function(value) { return value !== ""; });
  }
  var emails = answers("customer email").filter(function(value) {
    return /^[^\s@<>,;]+@[^\s@<>,;]+\.[^\s@<>,;]+$/.test(value);
  });
  var uniqueEmails = emails.filter(function(value, index) { return emails.indexOf(value) === index; });
  if (uniqueEmails.length > 1) throw new Error("Conflicting Customer Email answers. Keep one required email question in the form.");
  var name = answers("customer name")[0] || "";
  var message = answers("describe your issue")[0] || "";
  if (!name || !message || !uniqueEmails.length) {
    throw new Error("Missing name, issue, or valid customer email. Check form question titles and required fields.");
  }
  var timestampIndex = normalized.indexOf("timestamp");
  var timestamp = timestampIndex >= 0 ? cells[timestampIndex] : null;
  if (!(timestamp instanceof Date) || isNaN(timestamp.getTime())) {
    throw new Error("Form response timestamp is missing or invalid.");
  }
  return {name: name, email: uniqueEmails[0], message: message, receivedAt: timestamp.toISOString()};
}

function validateInquiries_(spreadsheet) {
  var sheet = spreadsheet.getSheetByName("Inquiries");
  if (!sheet) throw new Error("Inquiries sheet not found");
  if (JSON.stringify(sheet.getRange(1, 1, 1, INQUIRY_FIELDS.length).getValues()[0]) !== JSON.stringify(INQUIRY_FIELDS)) {
    throw new Error("Inquiries headers must match the 15 columns in docs/email_setup.md");
  }
  return sheet;
}

function importResponseRow_(spreadsheet, source, rowNumber) {
  if (rowNumber < 2) return false;
  var lock = LockService.getDocumentLock();
  lock.waitLock(30000);
  try {
    var sheet = validateInquiries_(spreadsheet);
    var width = source.getLastColumn();
    var headers = source.getRange(1, 1, 1, width).getValues()[0];
    var cells = source.getRange(rowNumber, 1, 1, width).getValues()[0];
    // Read by column position, preserving duplicate question titles. namedValues
    // cannot reliably distinguish two columns with the same question title.
    var response = extractResponse_(headers, cells);
    var properties = PropertiesService.getDocumentProperties();
    var key = "form_ticket:" + source.getSheetId() + ":" + rowNumber + ":" + response.receivedAt;
    var ticketId = properties.getProperty(key);
    var rows = sheet.getLastRow() >= 2 ? sheet.getRange(2, 1, sheet.getLastRow() - 1, 5).getValues() : [];
    if (ticketId && rows.some(function(row) { return String(row[0]) === ticketId; })) return false;
    // Also recognize this script's imports if a response row is moved.
    var existing = rows.find(function(row) {
      var received = row[1] instanceof Date ? row[1].toISOString() : String(row[1]);
      return received === response.receivedAt && String(row[2]) === response.name &&
        String(row[3]) === response.email && String(row[4]) === response.message;
    });
    if (existing) {
      properties.setProperty(key, String(existing[0]));
      return false;
    }
    if (!ticketId) {
      var nextNumber = Number(properties.getProperty("next_ticket_number") || "1");
      rows.forEach(function(row) {
        var match = String(row[0]).match(/^TKT-(\d+)$/);
        if (match) nextNumber = Math.max(nextNumber, Number(match[1]) + 1);
      });
      ticketId = "TKT-" + String(nextNumber).padStart(3, "0");
      // Reserve the ID before appending, so recovery after a crash reuses it.
      properties.setProperty("next_ticket_number", String(nextNumber + 1));
      properties.setProperty(key, ticketId);
    }
    function literal(value) { return value.charAt(0) === "=" ? "'" + value : value; }
    sheet.appendRow([ticketId, response.receivedAt, literal(response.name), response.email,
      literal(response.message), "NEW", "", "", "", "", "", "", "", "", ""]);
    SpreadsheetApp.flush();
    Logger.log("Created ticket " + ticketId + " from response row " + rowNumber);
    return true;
  } finally {
    lock.releaseLock();
  }
}
