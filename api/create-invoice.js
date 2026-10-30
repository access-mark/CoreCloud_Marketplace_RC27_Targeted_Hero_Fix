// api/create-invoice.js
const { upsertContact, createInvoice } = require('./_lib/sage.js');
const { buildPayfastLink } = require('./payfast-link.js');

module.exports = async (req, res) => {
  if (req.method !== 'POST') return res.status(405).end();
  try {
    const { buyer, cart, reference, notes } = req.body || {};
    if (!buyer?.email || !Array.isArray(cart) || cart.length === 0) {
      return res.status(400).json({ error: 'buyer.email and cart[] required' });
    }

    // Ensure Contact exists in Sage
    const contact = await upsertContact({
      name: buyer.name || buyer.company || buyer.email,
      email: buyer.email,
      phone: buyer.phone,
      tax_number: buyer.vat_number,
      addresses: buyer.addresses || []
    });

    // Build invoice lines
    const lines = cart.map(i => ({
      description: i.name,
      item_id: i.sage_item_id || null,
      quantity: Number(i.qty || 1),
      unit_price: Number(i.price_zar),
      tax_rate_id: i.tax_rate_id // fallback to SAGE_VAT_STD_ID inside lib
    }));

    // Create invoice
    const inv = await createInvoice({
      contact_id: contact.id || contact?.$resource?.id,
      lines,
      reference,
      notes
    });

    const invoice_id = inv?.id || inv?.$resource?.id;
    if (!invoice_id) {
      return res.status(500).json({ error: 'No invoice id returned from Sage' });
    }

    // Compute total for PayFast link
    const total = lines.reduce((s, l) => s + Number(l.unit_price) * Number(l.quantity), 0);

    const pay_url = buildPayfastLink({
      amount: total.toFixed(2),
      item_name: reference || 'Marketplace Order',
      m_payment_id: invoice_id,             // Sage invoice id for reconciliation
      email_address: buyer.email
    });

    return res.json({ ok: true, invoice_id, pay_url });
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
};
