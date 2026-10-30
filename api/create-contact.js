// api/create-contact.js
const { upsertContact } = require('./_lib/sage.js');

module.exports = async (req, res) => {
  if (req.method !== 'POST') return res.status(405).end();
  try {
    const { name, email, phone, tax_number, addresses } = req.body || {};
    if (!email) return res.status(400).json({ error: 'email required' });

    const contact = await upsertContact({ name, email, phone, tax_number, addresses });
    return res.json({ contact_id: contact?.id || contact?.$resource?.id || null, contact });
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
};
