const tokenInput = document.querySelector('#token');
const errorBox = document.querySelector('#error');

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${tokenInput.value}`, ...options.headers },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${response.status}`);
  return data;
}

function showError(error) {
  errorBox.textContent = error.message;
  errorBox.hidden = false;
}

function clearError() {
  errorBox.hidden = true;
}

function node(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

async function refresh() {
  clearError();
  try {
    const [orders, policies, tickets] = await Promise.all([
      request('/api/orders'), request('/api/policies'), request('/api/tickets'),
    ]);
    const orderList = document.querySelector('#order-list');
    orderList.replaceChildren(...orders.orders.map(order => node('div', `${order.order_id} · ${order.status} · ${order.note}`)));
    const policyList = document.querySelector('#policy-list');
    policyList.replaceChildren(...policies.policies.map(policy => node('div', `${policy.title} [${policy.id}]`)));
    const ticketList = document.querySelector('#ticket-list');
    ticketList.replaceChildren();
    for (const ticket of tickets.tickets) {
      const row = node('div', '', 'ticket');
      row.append(node('strong', `#${ticket.id} · ${ticket.order_id}`));
      row.append(node('p', ticket.question));
      row.append(node('small', `${ticket.reason} · ${ticket.status}`));
      if (ticket.status === 'open') {
        const button = node('button', '标记已处理', 'secondary');
        button.addEventListener('click', async () => {
          try {
            await request(`/api/tickets/${ticket.id}`, { method: 'PATCH', body: JSON.stringify({ status: 'resolved', resolution: 'Reviewed by staff' }) });
            await refresh();
          } catch (error) { showError(error); }
        });
        row.append(button);
      }
      ticketList.append(row);
    }
    if (!tickets.tickets.length) ticketList.append(node('p', '暂无工单', 'muted'));
  } catch (error) { showError(error); }
}

document.querySelector('#connect').addEventListener('click', refresh);
document.querySelector('#refresh').addEventListener('click', refresh);

document.querySelector('#ask-form').addEventListener('submit', async event => {
  event.preventDefault();
  clearError();
  try {
    const data = await request('/api/ask', { method: 'POST', body: JSON.stringify({ order_id: document.querySelector('#order-id').value, question: document.querySelector('#question').value }) });
    const answer = document.querySelector('#answer');
    answer.replaceChildren(node('small', data.mode), node('p', data.answer));
    if (data.sources.length) answer.append(node('small', `依据：${data.sources.map(source => source.title).join('、')}`));
    if (data.ticket_id) answer.append(node('small', `工单 #${data.ticket_id}`));
    answer.hidden = false;
    await refresh();
  } catch (error) { showError(error); }
});

document.querySelector('#order-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    await request('/api/orders', { method: 'POST', body: JSON.stringify({ order_id: document.querySelector('#new-order-id').value, status: document.querySelector('#order-status').value, note: document.querySelector('#order-note').value }) });
    event.target.reset();
    await refresh();
  } catch (error) { showError(error); }
});

document.querySelector('#policy-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    await request('/api/policies', { method: 'POST', body: JSON.stringify({ title: document.querySelector('#policy-title').value, body: document.querySelector('#policy-body').value }) });
    event.target.reset();
    await refresh();
  } catch (error) { showError(error); }
});
