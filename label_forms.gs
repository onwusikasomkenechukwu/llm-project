// Turns the labelling spreadsheet into one Google Form per batch.
//
// Open the spreadsheet, choose Extensions > Apps Script, paste this file in,
// save, and run buildForms. Each form gets one page per answer, with the
// rubric for each criterion beside its score, and sends its responses to a new
// tab of this spreadsheet. Item titles start with the row ID, so responses
// match key.csv. The links are written to a Forms tab.
//
// Apps Script stops a run after six minutes, so the script stops itself after
// five and remembers where it was. Run it again until the log says every batch
// is built.

const LABELS = 'Labels';
const RUBRIC = 'Rubric';
const FORMS = 'Forms';
const CHUNK = 3500; // characters per text block; long answers are split
const LIMIT = 5 * 60 * 1000; // stop before Apps Script's six-minute cut-off
// the law school's criteria of 3 November, as named in the Labels and Rubric tabs
const CRITERIA = ['Factual accuracy', 'Completeness', 'Historical context',
  'Source and evidence reliability', 'Nuanced reasoning', 'Linguistic framing'];

function buildForms() {
  const start = Date.now();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const rows = records(ss.getSheetByName(LABELS));
  const rubric = rubricText(ss.getSheetByName(RUBRIC));
  const log = ss.getSheetByName(FORMS) || ss.insertSheet(FORMS);
  if (log.getLastRow() === 0) log.appendRow(['Batch', 'Link for labellers', 'Edit link']);
  const done = new Set(log.getDataRange().getValues().slice(1).map(r => String(r[0])));
  const props = PropertiesService.getDocumentProperties();
  const saved = JSON.parse(props.getProperty('progress') || 'null');

  const batches = [...new Set(rows.map(r => String(r['Batch'])))];
  for (const batch of batches) {
    if (done.has(batch)) continue;
    const todo = rows.filter(r => String(r['Batch']) === batch);
    let form, next = 0;
    if (saved && saved.batch === batch) {
      form = FormApp.openById(saved.formId);
      next = saved.next;
    } else {
      form = newForm(batch, todo.length);
      form.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());
    }
    for (; next < todo.length; next++) {
      if (Date.now() - start > LIMIT) {
        props.setProperty('progress', JSON.stringify({ batch, formId: form.getId(), next }));
        Logger.log(`Stopped at batch ${batch}, answer ${next + 1} of ${todo.length}. Run again to continue.`);
        return;
      }
      addAnswer(form, todo[next], next, todo.length, rubric);
    }
    props.deleteProperty('progress');
    log.appendRow([batch, form.getPublishedUrl(), form.getEditUrl()]);
    SpreadsheetApp.flush();
  }
  Logger.log('Every batch is built. The links are in the Forms tab.');
}

function newForm(batch, n) {
  const form = FormApp.create(`Grading AI answers: batch ${batch}`);
  form.setDescription(
    `${n} answers, about two hours. Each page is one AI answer: read the ` +
    'question, the reference, then the answer, and score it with the rubric. ' +
    'You are not told which AI wrote it or who asked; neither were the AI graders. ' +
    'Grade the content as if a member of the public asked. Ignore formatting marks ' +
    'such as ** and ##. Do not compare notes with the other grader of this batch ' +
    'until you have both finished.');
  form.setProgressBar(true);
  form.setAllowResponseEdits(true);
  if (form.setPublished) form.setPublished(true);
  form.addTextItem().setTitle('Your name').setRequired(true);
  return form;
}

function addAnswer(form, r, i, n, rubric) {
  const id = r['Row ID'];
  const loaded = String(r['Premise handling (1-4, Loaded only)']).trim() !== 'n/a';
  form.addPageBreakItem().setTitle(`${id} (${i + 1} of ${n})`)
    .setHelpText(`Question type: ${r['Question type']}`);
  addText(form, 'Question', r['Question']);
  addText(form, 'Reference answer components', r['Reference answer components']);
  addText(form, 'Answer', r['Answer']);

  for (const name of CRITERIA) {
    score(form, `${id} ${name}`, rubric[name.toLowerCase()]);
  }
  if (loaded) score(form, `${id} Premise handling`, rubric['premise handling']);
  form.addMultipleChoiceItem().setTitle(`${id} Hard fail`)
    .setHelpText(rubric['hard fail'])
    .setChoiceValues(['No', 'Yes']).setRequired(true);
  form.addParagraphTextItem().setTitle(`${id} Notes`)
    .setHelpText('Optional. Please add one for any 1 or 2, any hard fail, and anything you looked up.');
}

function score(form, title, help) {
  form.addScaleItem().setTitle(title).setHelpText(help || '')
    .setBounds(1, 4).setLabels('Does not meet', 'Fully meets').setRequired(true);
}

// A section header holds the text; long text is split at paragraph breaks.
function addText(form, title, text) {
  const parts = chunks(String(text || '').trim() || '(none)');
  parts.forEach((part, i) => {
    form.addSectionHeaderItem()
      .setTitle(parts.length > 1 ? `${title} (part ${i + 1} of ${parts.length})` : title)
      .setHelpText(part);
  });
}

function chunks(text) {
  const out = [];
  let cur = '';
  for (const para of text.split(/\n\s*\n/)) {
    for (let p = para; p; p = p.slice(CHUNK)) { // a paragraph longer than CHUNK is cut
      const piece = p.slice(0, CHUNK);
      if (cur && cur.length + piece.length + 2 > CHUNK) { out.push(cur); cur = ''; }
      cur += (cur ? '\n\n' : '') + piece;
    }
  }
  if (cur.trim()) out.push(cur);
  return out;
}

function records(sheet) {
  const [head, ...data] = sheet.getDataRange().getValues();
  return data.filter(r => r[0]).map(r => Object.fromEntries(head.map((h, i) => [h, r[i]])));
}

// The Rubric tab lists each criterion on its own row, then its levels below it.
function rubricText(sheet) {
  const out = {};
  let key = null;
  for (const [crit, text] of sheet.getDataRange().getValues().slice(1)) {
    if (crit) { key = String(crit).trim().toLowerCase(); out[key] = String(text); }
    else if (key && text) out[key] += '\n' + text;
  }
  return out;
}
