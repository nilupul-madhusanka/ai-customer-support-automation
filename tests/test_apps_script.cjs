const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const properties = new Map();
const headers = ['Timestamp', 'Customer Name', 'Describe your issue', 'Customer Email', 'Customer Email'];
const responses = [headers,
  [new Date('2026-10-14T18:00:00Z'), 'Customer', 'Please help.', 'customer@example.com', ''],
  [new Date('2026-10-14T18:01:00Z'), 'Customer', 'Please help.', '', 'customer@example.com'],
  [new Date('2026-10-14T18:02:00Z'), 'Customer', 'Please help.', '', '']];
let flushFailure = false;
let released = 0;
let triggerCount = 0;
const ticketRows = [];
function sheet(name, id, rows) {
  return {
    getName: () => name,
    getSheetId: () => id,
    getLastRow: () => rows.length,
    getLastColumn: () => rows[0].length,
    getRange: (row, column, height, width) => ({getValues: () =>
      rows.slice(row - 1, row - 1 + height).map(values => values.slice(column - 1, column - 1 + width))}),
    appendRow: row => rows.push(row)
  };
}
const inquiries = sheet('Inquiries', 1, ticketRows);
const source = sheet('Form Responses 1', 2, responses);
const spreadsheet = {
  getId: () => 'test-sheet',
  getSheetByName: name => name === 'Inquiries' ? inquiries : source,
  getSheets: () => [inquiries, source]
};
const triggers = [];
const context = vm.createContext({Date, Logger: {log: () => {}},
  SpreadsheetApp: {getActiveSpreadsheet: () => spreadsheet, flush: () => {
    if (flushFailure) { flushFailure = false; throw new Error('Simulated crash after append'); }
  }},
  LockService: {getDocumentLock: () => ({waitLock: () => {}, releaseLock: () => released++})},
  PropertiesService: {getDocumentProperties: () => ({
    getProperty: key => properties.get(key) || null,
    setProperty: (key, value) => properties.set(key, value)
  })},
  ScriptApp: {
    EventType: {ON_FORM_SUBMIT: 'submit'}, TriggerSource: {SPREADSHEETS: 'sheets'},
    getProjectTriggers: () => [...triggers],
    deleteTrigger: trigger => triggers.splice(triggers.indexOf(trigger), 1),
    newTrigger: () => ({forSpreadsheet: () => ({onFormSubmit: () => ({create: () => {
      triggerCount++;
      triggers.push({getHandlerFunction: () => 'onFormSubmit', getEventType: () => 'submit',
        getTriggerSource: () => 'sheets', getTriggerSourceId: () => spreadsheet.getId()});
    }})})})
  }
});
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'google_apps_script.js'), 'utf8'), context);
ticketRows.push(Array.from(context.INQUIRY_FIELDS));

context.setupFormIntake();
assert.equal(triggerCount, 1);
assert.equal(ticketRows.length, 3); // Both populated duplicate-column layouts imported.
assert.equal(ticketRows[1][3], 'customer@example.com');
assert.equal(ticketRows[2][3], 'customer@example.com');
assert.equal(ticketRows[1][5], 'NEW');
assert.equal(ticketRows[1].length, 15);
assert.equal(ticketRows[1][1], '2026-10-14T18:00:00.000Z');
context.setupFormIntake();
assert.equal(triggerCount, 1);
assert.equal(ticketRows.length, 3); // Re-running setup doesn't duplicate tickets or triggers.
assert.throws(() => context.extractResponse_(headers, [new Date(), 'Customer', 'Help', 'a@example.com', 'b@example.com']), /Conflicting/);
assert.throws(() => context.onFormSubmit(), /setupFormIntake/);

responses.push([new Date('2026-10-14T18:03:00Z'), 'Customer', '=1+1', 'customer@example.com', '']);
const event = {source: spreadsheet, range: {getSheet: () => source, getRow: () => 5}};
flushFailure = true;
assert.throws(() => context.onFormSubmit(event), /Simulated crash/);
assert.equal(ticketRows.length, 4);
context.onFormSubmit(event);
assert.equal(ticketRows.length, 4); // Recovery after append doesn't send a duplicate ticket.
assert.equal(ticketRows[3][4], "'=1+1");
assert.ok(released >= 5);
console.log('Apps Script checks passed: duplicate headers, setup, recovery, incomplete rows, and repeated events.');
