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

  function showStatus(message, problems = [], isError = false) {
    statusBox.replaceChildren();
    statusBox.classList.toggle('error', isError);
    if (message) {
      const text = document.createElement('p');
      text.textContent = message;
      statusBox.append(text);
    }
    if (problems.length) {
      const list = document.createElement('ul');
      for (const problem of problems) {
        const item = document.createElement('li');
        item.textContent = problem;
        list.append(item);
      }
      statusBox.append(list);
    }
  }

  function collectForm() {
    const field = (name) => form.elements[name]?.value.trim() ?? '';
    return {
      event_name: field('event_name'),
      event_type: field('event_type'),
      date: field('date'),
      start_time: field('start_time'),
      end_time: field('end_time'),
      location: field('location'),
      participants: readRows('participant'),
      activities: readRows('activity').map((row) => row.text),
      speakers: readRows('speaker').map((row) => row.text),
      no_budget: noBudget.checked,
      budget_items: noBudget.checked ? [] : readRows('budget'),
      proposer: field('proposer'),
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
      showStatus('');
      document.getElementById('result-id').textContent = `Saved as data/briefs/${data.id}.json`;
      document.getElementById('result-json').textContent = JSON.stringify(data.brief, null, 2);
      result.hidden = false;
      result.scrollIntoView({ behavior: 'smooth' });
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
