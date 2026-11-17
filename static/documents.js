const uploadForm = document.querySelector('#upload-form');
const fileInput = document.querySelector('#file-input');
const uploadButton = document.querySelector('#upload-button');
const uploadStatus = document.querySelector('#upload-status');
const fileList = document.querySelector('#file-list');
const fileCount = document.querySelector('#file-count');
const emptyState = document.querySelector('#empty-state');

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let size = bytes / 1024;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(1)} ${units[unit]}`;
}

function showStatus(message, isError = false) {
  uploadStatus.textContent = message;
  uploadStatus.classList.toggle('error', isError);
  uploadStatus.hidden = !message;
}

async function loadFiles() {
  const response = await fetch('/api/documents');
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Could not load files.');

  fileList.replaceChildren();
  const count = data.files.length;
  fileCount.textContent = `${count} ${count === 1 ? 'file' : 'files'}`;
  emptyState.hidden = count !== 0;

  for (const file of data.files) {
    const row = document.createElement('li');
    row.className = 'file-row';
    const details = document.createElement('div');
    details.className = 'file-details';
    const name = document.createElement('a');
    name.className = 'file-name';
    name.href = `/api/documents/file/${encodeURIComponent(file.name)}`;
    name.target = '_blank';
    name.rel = 'noopener noreferrer';
    name.textContent = file.name;
    const size = document.createElement('span');
    size.className = 'file-size';
    size.textContent = `${formatSize(file.size)} · ${file.chunks ? `Indexed · ${file.chunks} chunks` : 'Not indexed'}`;
    if (file.event_type) {
      const type = document.createElement('span');
      type.className = 'search-score';
      type.textContent = file.event_type === 'reference' ? 'reference file' : file.event_type;
      size.append(' · ', type);
    }
    const removeButton = document.createElement('button');
    removeButton.className = 'delete-button';
    removeButton.type = 'button';
    removeButton.textContent = 'Delete';
    removeButton.addEventListener('click', () => deleteFile(file.name, removeButton));
    details.append(name, size);
    row.append(details, removeButton);
    fileList.append(row);
  }
}

async function deleteFile(name, button) {
  button.disabled = true;
  showStatus('');
  try {
    const response = await fetch(`/api/documents/${encodeURIComponent(name)}`, { method: 'DELETE' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not delete the file.');
    await loadFiles();
  } catch (error) {
    showStatus(error.message, true);
    button.disabled = false;
  }
}

uploadForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!fileInput.files.length) {
    showStatus('Choose a file to upload.', true);
    fileInput.focus();
    return;
  }

  const formData = new FormData();
  formData.append('file', fileInput.files[0]);
  formData.append('event_type', document.querySelector('#event-type-input').value);
  uploadButton.disabled = true;
  showStatus('');
  try {
    const response = await fetch('/api/documents', { method: 'POST', body: formData });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not upload the file.');
    showStatus(`Uploaded ${data.file.name}.`);
    fileInput.value = '';
    await loadFiles();
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    uploadButton.disabled = false;
  }
});

loadFiles().catch((error) => showStatus(error.message, true));

const searchForm = document.querySelector('#search-form');
const searchButton = document.querySelector('#search-button');
const searchStatus = document.querySelector('#search-status');
const searchResults = document.querySelector('#search-results');

function showSearchStatus(message, isError = false) {
  searchStatus.textContent = message;
  searchStatus.classList.toggle('error', isError);
  searchStatus.hidden = !message;
}

function resultCard(result, rank) {
  const item = document.createElement('li');
  item.className = 'search-card';
  const top = document.createElement('div');
  top.className = 'search-card-top';
  const title = document.createElement('strong');
  title.textContent = `${rank}. ${result.event_name || result.source}`;
  const score = document.createElement('span');
  score.className = 'search-score';
  score.textContent = `match ${Math.min(100, Math.round(result.score * 100))}%`;
  top.append(title, score);
  const meta = document.createElement('p');
  meta.className = 'search-meta';
  meta.textContent = `${result.section} · ${result.event_type} · ${result.source}${result.page ? ` · page ${result.page}` : ''}`;
  const text = document.createElement('p');
  text.className = 'search-text';
  text.textContent = result.text.length > 420 ? `${result.text.slice(0, 420)}…` : result.text;
  item.append(top, meta, text);
  return item;
}

searchForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const params = new URLSearchParams({
    section: document.querySelector('#search-section').value,
    event_type: document.querySelector('#search-event-type').value,
    q: document.querySelector('#search-query').value,
  });
  searchButton.disabled = true;
  searchResults.replaceChildren();
  showSearchStatus('Searching…');
  try {
    const response = await fetch(`/api/search?${params}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Search failed.');
    if (!data.results.length) {
      showSearchStatus('No matching sections. Upload old proposals first.', true);
      return;
    }
    showSearchStatus('');
    data.results.forEach((result, index) => searchResults.append(resultCard(result, index + 1)));
  } catch (error) {
    showSearchStatus(error.message, true);
  } finally {
    searchButton.disabled = false;
  }
});
