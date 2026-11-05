// Turns the labelling spreadsheet into one Google Form per topic.
//
// Open the spreadsheet, choose Extensions > Apps Script, paste this file in,
// save, and run buildForms. Each form opens by asking for
// the rater's email, then gives one page per answer: the question as the model
// was asked it, with nothing about the asker; the reference answer; the
// model's answer; and the rubric beside each score. Responses go to a new tab
// of this spreadsheet. Item titles start with the row ID, so responses match
// key.csv, which holds the model, cue and run and never reaches a rater. The
// links are written to a Forms tab.
//
// Apps Script stops a run after six minutes, so the script stops itself after
// five and remembers where it was. Run it again until the log says every topic
// is built. Nothing is emailed or shared: who gets which topic's link is
// decided by hand.

const LABELS = 'Labels';
const RUBRIC = 'Rubric';
const FORMS = 'Forms';
// the law school's rubric sheet of 3 November
const RUBRIC_URL = 'https://docs.google.com/spreadsheets/d/1zWJz2_OQb6nz1lgKDAICp-VdEsELWfkk9MSgxBIJxd4/edit';
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
  if (log.getLastRow() === 0) log.appendRow(['Topic', 'Link for raters', 'Edit link']);
  const done = new Set(log.getDataRange().getValues().slice(1).map(r => String(r[0])));
  const props = PropertiesService.getDocumentProperties();
  const saved = JSON.parse(props.getProperty('progress') || 'null');
  if (!RUBRIC_URL) Logger.log('RUBRIC_URL is empty: the forms will not link the rubric.');

  for (const topic of topicsOf(rows)) {
    if (done.has(topic)) continue;
    const todo = rows.filter(r => String(r['Topic']) === topic);
    let form, next = 0;
    if (saved && saved.topic === topic) {
      form = FormApp.openById(saved.formId);
      next = saved.next;
    } else {
      form = newForm(topic, todo.length);
      form.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());
    }
    for (; next < todo.length; next++) {
      if (Date.now() - start > LIMIT) {
        props.setProperty('progress', JSON.stringify({ topic, formId: form.getId(), next }));
        Logger.log(`Stopped at ${topic}, answer ${next + 1} of ${todo.length}. Run again to continue.`);
        return;
      }
      addAnswer(form, todo[next], next, todo.length, rubric);
    }
    props.deleteProperty('progress');
    log.appendRow([topic, form.getPublishedUrl(), form.getEditUrl()]);
    SpreadsheetApp.flush();
  }
  Logger.log('Every topic is built. The links are in the Forms tab.');
}

function newForm(topic, n) {
  const form = FormApp.create(`Grading AI answers: ${topic}`);
  form.setDescription(
    `${n} answers on ${topic}, about two hours. Each page is one AI answer: read the ` +
    'question, the reference, then the answer, and score it with the rubric' +
    (RUBRIC_URL ? ` (full rubric: ${RUBRIC_URL})` : '') + '. ' +
    'You are not told which AI wrote it or who asked; neither were the AI graders. ' +
    'Grade the content as if a member of the public asked. Ignore formatting marks ' +
    'such as ** and ##. Do not compare notes with the other rater of this topic ' +
    'until you have both finished.');
  // the email is the first question; typed, so no Google sign-in is needed
  if (form.setEmailCollectionType) {
    form.setEmailCollectionType(FormApp.EmailCollectionType.RESPONDER_INPUT);
  } else {
    form.setCollectEmail(true);
  }
  form.setProgressBar(true);
  form.setAllowResponseEdits(true);
  if (form.setPublished) form.setPublished(true);
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

function topicsOf(rows) {
  return [...new Set(rows.map(r => String(r['Topic'])))].sort();
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
