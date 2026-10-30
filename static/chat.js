const form = document.querySelector('#chat-form');
const input = document.querySelector('#message-input');
const sendButton = document.querySelector('#send-button');
const conversation = document.querySelector('#conversation');
const clearButton = document.querySelector('#clear-button');

let history = [];

function renderMessage(message, extraClass = '') {
  const row = document.createElement('article');
  row.className = `message ${message.role} ${extraClass}`.trim();
  const avatar = document.createElement('div');
  avatar.className = 'avatar';
  avatar.textContent = message.role === 'user' ? 'Y' : '✳';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  if (message.role === 'assistant') {
    appendLinkedText(bubble, message.content);
  } else {
    bubble.textContent = message.content;
  }
  const body = document.createElement('div');
  body.className = 'message-body';
  body.append(bubble);
  if (message.role === 'assistant' && Array.isArray(message.sources)) {
    const sources = document.createElement('p');
    sources.className = 'message-sources';
    sources.append(document.createTextNode('Sources: '));
    if (message.sources.length === 0) {
      sources.append(document.createTextNode('No document chunks retrieved'));
    } else {
      message.sources.forEach((source, index) => {
        if (index) sources.append(document.createTextNode('; '));
        let label = `${source.filename} · chunk ${source.chunk}`;
        if (source.page !== null && source.page !== undefined) label += ` · page ${source.page}`;
        sources.append(document.createTextNode(label));
      });
    }
    body.append(sources);
  }
  row.append(avatar, body);
  conversation.append(row);
  conversation.scrollTop = conversation.scrollHeight;
  return row;
}

function appendLinkedText(container, text) {
  const urlPattern = /https?:\/\/[^\s<>"']+/gi;
  let lastIndex = 0;

  for (const match of text.matchAll(urlPattern)) {
    let url = match[0];
    // Leave common sentence punctuation outside the link.
    const trailingPunctuation = url.match(/[.,!?;:]+$/)?.[0] || '';
    url = url.slice(0, url.length - trailingPunctuation.length);
    const start = match.index;

    container.append(document.createTextNode(text.slice(lastIndex, start)));
    if (url) {
      const link = document.createElement('a');
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = url;
      container.append(link);
    }
    container.append(document.createTextNode(trailingPunctuation));
    lastIndex = start + match[0].length;
  }

  container.append(document.createTextNode(text.slice(lastIndex)));
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const content = input.value.trim();
  if (!content || sendButton.disabled) return;

  document.querySelector('#welcome')?.remove();
  const userMessage = { role: 'user', content };
  history.push(userMessage);
  renderMessage(userMessage);
  input.value = '';
  input.style.height = 'auto';
  sendButton.disabled = true;
  const pending = renderMessage({ role: 'assistant', content: 'Thinking…' }, 'typing');

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: history }),
    });
    const data = await response.json();
    pending.remove();
    if (!response.ok) throw new Error(data.error || 'The request failed.');
    history.push(data.message);
    renderMessage(data.message);
  } catch (error) {
    pending.remove();
    renderMessage({ role: 'assistant', content: error.message || 'Something went wrong.' }, 'error');
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
});

input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
});

input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

clearButton.addEventListener('click', () => {
  history = [];
  conversation.replaceChildren();
  const welcome = document.createElement('div');
  welcome.id = 'welcome';
  welcome.className = 'welcome';
  welcome.innerHTML = '<div class="welcome-icon" aria-hidden="true">✦</div><h2>What’s on your mind?</h2><p>Ask anything. Your conversation stays in this browser.</p>';
  conversation.append(welcome);
  input.focus();
});
