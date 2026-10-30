// api/_lib/sage.js
const SAGE_TOKEN_URL = process.env.SAGE_TOKEN_URL;      // e.g. https://oauth.accounting.sage.com/token
const SAGE_API_BASE  = process.env.SAGE_API_BASE;       // e.g. https://api.accounting.sage.com/v3.1
const SAGE_CLIENT_ID = process.env.SAGE_CLIENT_ID;
const SAGE_CLIENT_SECRET = process.env.SAGE_CLIENT_SECRET;
const SAGE_COMPANY_ID = process.env.SAGE_COMPANY_ID;    // Sage company GUID
const SAGE_REFRESH_TOKEN = process.env.SAGE_REFRESH_TOKEN;
const SAGE_VAT_STD_ID = process.env.SAGE_VAT_STD_ID;    // ZA 15% VAT rate id

async function getAccessToken() {
  const body = new URLSearchParams({
    grant_type: 'refresh_token',
    refresh_token: SAGE_REFRESH_TOKEN,
    client_id: SAGE_CLIENT_ID,
    client_secret: SAGE_CLIENT_SECRET
  });
  const r = await fetch(SAGE_TOKEN_URL, {
    method:'POST',
    headers:{ 'Content-Type':'application/x-www-form-urlencoded' },
    body
  });
  if (!r.ok) throw new Error(`Sage token ${r.status}`);
  return r.json(); // { access_token, expires_in, ... }
}

async function sFetch(path, opts = {}) {
  const { access_token } = await getAccessToken();
  const r = await fetch(`${SAGE_API_BASE}${path}`, {
    ...opts,
    headers: {
      'Authorization': `Bearer ${access_token}`,
      'Accept': 'application/json',
      'Content-Type': 'application/json',
      'X-Site': SAGE_COMPANY_ID,
      ...(opts.headers || {})
    }
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`Sage ${r.status}: ${text}`);
  }
  return r.json();
}

// -------- Contacts --------
async function upsertContact({ name, email, phone, tax_number, addresses = [] }) {
  const found = await sFetch(`/contacts?email=${encodeURIComponent(email)}`);
  const existing = (found?.$items || []).find(c => (c.email || '').toLowerCase() === email.toLowerCase());
  const payload = { contact: { name, email, telephone: phone || null, tax_number: tax_number || null, addresses } };
  if (existing) {
    return sFetch(`/contacts/${existing.id}`, { method: 'PUT', body: JSON.stringify(payload) });
  }
  return sFetch(`/contacts`, { method: 'POST', body: JSON.stringify(payload) });
}

// -------- Invoices --------
async function createInvoice({ contact_id, lines, reference, notes, due_days = 7 }) {
  const today = new Date();
  const due = new Date(Date.now() + due_days * 864e5);
  const payload = {
    sales_invoice: {
      contact_id,
      date: today.toISOString().slice(0,10),
      due_date: due.toISOString().slice(0,10),
      reference: reference || null,
      notes: notes || null,
      invoice_lines: lines.map(l => ({
        description: l.description,
        item_id: l.item_id || null,
        quantity: l.quantity,
        unit_price: Number(l.unit_price),
        tax_rate_id: l.tax_rate_id || SAGE_VAT_STD_ID
      }))
    }
  };
  return sFetch(`/sales_invoices`, { method: 'POST', body: JSON.stringify(payload) });
}

// -------- Receipts (payment callback) --------
async function allocateReceipt({ contact_id, invoice_id, amount, reference }) {
  const payload = {
    receipt: {
      contact_id,
      date: new Date().toISOString().slice(0,10),
      reference: reference || null,
      total_amount: Number(amount),
      allocations: [{ transaction_id: invoice_id, amount: Number(amount) }]
    }
  };
  return sFetch(`/receipts`, { method: 'POST', body: JSON.stringify(payload) });
}

module.exports = {
  getAccessToken,
  sFetch,
  upsertContact,
  createInvoice,
  allocateReceipt
};
