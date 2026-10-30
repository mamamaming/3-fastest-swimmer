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
