// api/payfast-link.js
// Builds a PayFast redirect URL (Sandbox or Live via env)
const crypto = require('crypto');

const PF_MERCHANT_ID  = process.env.PF_MERCHANT_ID;
const PF_MERCHANT_KEY = process.env.PF_MERCHANT_KEY;
const PF_PASSPHRASE   = process.env.PF_PASSPHRASE; // from PayFast dashboard
const PF_SANDBOX      = String(process.env.PF_SANDBOX || '').toLowerCase() === 'true' || process.env.PF_SANDBOX === '1';

const PF_BASE   = PF_SANDBOX ? 'https://sandbox.payfast.co.za/eng/process'
                             : 'https://www.payfast.co.za/eng/process';
const RETURN_URL = process.env.PF_RETURN_URL; // e.g. https://corecloud-marketplace.vercel.app/thank-you.html
const CANCEL_URL = process.env.PF_CANCEL_URL; // e.g. https://corecloud-marketplace.vercel.app/cart.html
const NOTIFY_URL = process.env.PF_NOTIFY_URL; // e.g. https://<project>.vercel.app/api/payment-webhook

function md5(input){ return crypto.createHash('md5').update(input).digest('hex'); }

// PayFast requires URL-encoded query with spaces as '+'
function encodePF(v){ return encodeURIComponent(String(v)).replace(/%20/g, '+'); }

function buildSignature(params){
  // Exclude undefined/empty; alphabetical order; append passphrase (if set)
  const qp = Object.keys(params)
    .filter(k => params[k] !== undefined && params[k] !== '')
    .sort()
    .map(k => `${k}=${encodePF(params[k])}`)
    .join('&');

  const base = PF_PASSPHRASE ? `${qp}&passphrase=${encodePF(PF_PASSPHRASE)}` : qp;
  return md5(base);
}

// amount MUST be a string with 2 decimals and dot separator
function toAmount(v){
  const n = Number(v || 0);
  return n.toFixed(2);
}

function buildPayfastLink({ amount, item_name, m_payment_id, email_address }){
  const params = {
    merchant_id: PF_MERCHANT_ID,
    merchant_key: PF_MERCHANT_KEY,
    return_url: RETURN_URL,
    cancel_url: CANCEL_URL,
    notify_url: NOTIFY_URL,
    amount: toAmount(amount),
    item_name: item_name || 'Marketplace Order',
    m_payment_id,
    email_address
  };

  const signature = buildSignature(params);
  const query = Object.keys(params)
    .map(k => `${k}=${encodePF(params[k])}`)
    .join('&') + `&signature=${signature}`;

  return `${PF_BASE}?${query}`;
}

module.exports = { buildPayfastLink };
