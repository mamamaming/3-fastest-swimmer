// Proposal form page (B1). Owner: Yuay.
(() => {
  const form = document.getElementById('brief-form');
  const statusBox = document.getElementById('form-status');
  const submitButton = document.getElementById('submit-button');
  const noBudget = document.getElementById('no-budget');
  const budgetBlock = document.getElementById('budget-block');
  const result = document.getElementById('result');

  const lists = {
    participant: { container: document.getElementById('participant-rows'), start: 2 },
    activity: { container: document.getElementById('activity-rows'), start: 3, max: 5 },
    speaker: { container: document.getElementById('speaker-rows'), start: 1 },
    budget: { container: document.getElementById('budget-rows'), start: 2 },
  };

  function addRow(kind) {
    const list = lists[kind];
    if (list.max && list.container.children.length >= list.max) return;
    const row = document.getElementById(`${kind}-template`).content.firstElementChild.cloneNode(true);
    row.querySelector('.remove-button').addEventListener('click', () => {
      row.remove();
      updateTotals();
      updateAddButtons();
    });
    row.addEventListener('input', updateTotals);
    list.container.append(row);
    updateAddButtons();
    return row;
  }

  function updateAddButtons() {
    for (const [kind, list] of Object.entries(lists)) {
      const button = document.querySelector(`[data-add="${kind}"]`);
      if (list.max) button.disabled = list.container.children.length >= list.max;
    }
  }

  function readRows(kind) {
    return [...lists[kind].container.children].map((row) => {
      const values = {};
      for (const input of row.querySelectorAll('[data-key]')) values[input.dataset.key] = input.value.trim();
      return values;
    });
  }

  function updateTotals() {
    const people = readRows('participant').reduce((sum, row) => sum + (Number(row.count) || 0), 0);
    document.getElementById('participant-total').textContent = `Total: ${people} people`;
    const baht = readRows('budget').reduce((sum, row) => sum + (Number(row.qty) || 0) * (Number(row.unit_price) || 0), 0);
    document.getElementById('budget-total').textContent = `Total: ${baht.toLocaleString('en-US')} baht`;
  }

  function showStatus(message, problems = [], isError = false, box = statusBox) {
    box.replaceChildren();
    box.classList.toggle('error', isError);
    box.classList.remove('warning');
    if (message) {
      const text = document.createElement('p');
      text.textContent = message;
      box.append(text);
    }
    if (problems.length) {
      const list = document.createElement('ul');
      for (const problem of problems) {
        const item = document.createElement('li');
        item.textContent = problem;
        list.append(item);
      }
      box.append(list);
    }
  }

  // ---- Follow-up questions (B5) ----
  const questionsForm = document.getElementById('questions-form');
  const questionList = document.getElementById('question-list');
  const questionsStatus = document.getElementById('questions-status');
  const answersButton = document.getElementById('answers-button');
  let currentBriefId = null;
  let currentQuestions = [];

  function showBrief(id, brief) {
    document.getElementById('result-id').textContent = `Saved as data/briefs/${id}.json`;
    document.getElementById('result-json').textContent = JSON.stringify(brief, null, 2);
    result.hidden = false;
  }

  function renderQuestions(questions) {
    questionList.replaceChildren();
    for (const question of questions) {
      const label = document.createElement('label');
      label.className = 'field';
      label.textContent = question.question;
      if (question.needed_for) {
        const note = document.createElement('span');
        note.className = 'optional';
        note.textContent = ` (for ${question.needed_for})`;
        label.append(note);
      }
      const input = document.createElement('input');
      input.type = question.field === 'attendance_target' ? 'number' : 'text';
      if (input.type === 'number') { input.min = '1'; input.step = '1'; }
      input.dataset.id = question.id;
      label.append(input);
      questionList.append(label);
    }
  }

  async function askQuestions(id) {
    questionsForm.hidden = false;
    questionList.replaceChildren();
    answersButton.disabled = true;
    showStatus('Checking what is missing… (the local model can take a minute)', [], false, questionsStatus);
    questionsForm.scrollIntoView({ behavior: 'smooth' });
    try {
      const response = await fetch(`/api/briefs/${id}/questions`, { method: 'POST' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'Could not get the questions.');
      currentQuestions = data.questions || [];
      if (!currentQuestions.length) {
        showStatus('Nothing is missing. The brief is ready for writing.', [], false, questionsStatus);
        showWriteCard();
        return;
      }
      renderQuestions(currentQuestions);
      showStatus('', [], false, questionsStatus);
      answersButton.disabled = false;
      questionList.querySelector('input')?.focus();
    } catch (error) {
      showStatus(`${error.message} You can still write the proposal.`, [], true, questionsStatus);
      showWriteCard();
    }
  }

  questionsForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const answers = {};
    for (const input of questionList.querySelectorAll('input[data-id]')) answers[input.dataset.id] = input.value.trim();
    answersButton.disabled = true;
    showStatus('Saving answers…', [], false, questionsStatus);
    try {
      const response = await fetch(`/api/briefs/${currentBriefId}/answers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ questions: currentQuestions, answers }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        showStatus(data.error || 'Could not save the answers.', data.problems || [], true, questionsStatus);
        answersButton.disabled = false;
        return;
      }
      const open = data.brief.to_confirm?.length || 0;
      showStatus(open ? `Answers saved. ${open} item(s) will be marked [TO CONFIRM].` : 'Answers saved.', [], false, questionsStatus);
      showBrief(data.id, data.brief);
      showWriteCard();
      writeCard.scrollIntoView({ behavior: 'smooth' });
    } catch (error) {
      showStatus(`Could not reach the app: ${error.message}`, [], true, questionsStatus);
      answersButton.disabled = false;
    }
  });

  // ---- Write and download (C3) ----
  const writeCard = document.getElementById('write-card');
  const writeButton = document.getElementById('write-button');
  const writeStatus = document.getElementById('write-status');
  const downloadLink = document.getElementById('download-link');

  function showWriteCard() {
    writeCard.hidden = false;
    writeButton.disabled = false;
    downloadLink.hidden = true;
    showStatus('', [], false, writeStatus);
  }

  writeButton.addEventListener('click', async () => {
    writeButton.disabled = true;
    downloadLink.hidden = true;
    const started = Date.now();
    const tick = () => showStatus(
      `Writing… ${Math.round((Date.now() - started) / 1000)} s (usually about 5 minutes)`, [], false, writeStatus,
    );
    tick();
    const timer = setInterval(tick, 1000);
    try {
      const response = await fetch(`/api/briefs/${currentBriefId}/write`, { method: 'POST' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'Could not write the proposal.');
      const warnings = data.warnings || [];
      showStatus(
        warnings.length ? 'Done. Check these in the Word file before sending:' : 'Done. No problems found.',
        warnings, false, writeStatus,
      );
      writeStatus.classList.toggle('warning', Boolean(warnings.length));
      downloadLink.href = `/api/briefs/${currentBriefId}/docx`;
      downloadLink.hidden = false;
      showBrief(data.id, data.brief);
    } catch (error) {
      showStatus(error.message, [], true, writeStatus);
    } finally {
      clearInterval(timer);
      writeButton.disabled = false;
    }
  });

  function collectForm() {
    const field = (name) => form.elements[name]?.value.trim() ?? '';
    return {
      event_name: field('event_name'),
      event_type: field('event_type'),
      date: field('date'),
      end_date: field('end_date'),
      start_time: field('start_time'),
      end_time: field('end_time'),
      location: field('location'),
      participants: readRows('participant'),
      attendance_target: field('attendance_target'),
      activities: readRows('activity').map((row) => row.text),
      speakers: readRows('speaker').map((row) => row.text),
      no_budget: noBudget.checked,
      budget_items: noBudget.checked ? [] : readRows('budget'),
      proposer: field('proposer'),
      department: field('department'),
    };
  }

  document.querySelectorAll('[data-add]').forEach((button) => {
    button.addEventListener('click', () => addRow(button.dataset.add)?.querySelector('input')?.focus());
  });

  noBudget.addEventListener('change', () => {
    budgetBlock.hidden = noBudget.checked;
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    submitButton.disabled = true;
    showStatus('Saving…');
    try {
      const response = await fetch('/api/briefs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(collectForm()),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        showStatus(data.error || 'Could not save the event brief.', data.problems || [], true);
        return;
      }
      showStatus(data.warnings?.length ? 'Saved. Please double-check:' : '', data.warnings || []);
      statusBox.classList.toggle('warning', Boolean(data.warnings?.length));
      currentBriefId = data.id;
      writeCard.hidden = true;
      showBrief(data.id, data.brief);
      askQuestions(data.id);
    } catch (error) {
      showStatus(`Could not reach the app: ${error.message}`, [], true);
    } finally {
      submitButton.disabled = false;
    }
  });

  for (const [kind, list] of Object.entries(lists)) {
    for (let i = 0; i < list.start; i += 1) addRow(kind);
  }
  updateTotals();
})();
