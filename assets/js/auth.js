// assets/js/auth.js
(function(){
  const KEY = 'ccm-user';

  function getUser(){ try{ return JSON.parse(localStorage.getItem(KEY) || 'null'); }catch(e){ return null; } }
  function setUser(u){ localStorage.setItem(KEY, JSON.stringify(u)); }
  function clearUser(){ localStorage.removeItem(KEY); }

  // Non-destructive merge (updates known fields only)
  function mergeUser(patch){
    const allowed = new Set([
      'first_name','last_name','email','phone',
      'company','vat','billing','delivery',
      'role','notes'
    ]);
    const current = getUser() || {};
    const next = { ...current };
    Object.keys(patch || {}).forEach(k=>{
      if (allowed.has(k) && patch[k] != null && patch[k] !== '') next[k] = patch[k];
    });
    setUser(next);
    return next;
  }

  // Prefill helper: pass element ids that should be filled if empty
  function prefill(idsMap){
    // idsMap: { fieldId: userKey }
    const u = getUser() || {};
    Object.entries(idsMap || {}).forEach(([id, key])=>{
      const el = document.getElementById(id);
      if(!el) return;
      if(!el.value && u[key] != null) el.value = u[key];
    });
    // Special case: contact full name from first/last
    if (idsMap && idsMap.contact && !document.getElementById(idsMap.contact)?.value) {
      const full = [u.first_name, u.last_name].filter(Boolean).join(' ');
      const el = document.getElementById(idsMap.contact);
      if (el && full) el.value = full;
    }
  }

  // Expose globally
  window.CCMAuth = { getUser, setUser, clearUser, mergeUser, prefill };

  // Nav helper: swap Login -> Hello, {first}
  document.addEventListener('DOMContentLoaded', ()=>{
    const user = getUser();
    const nav = document.querySelector('.ccm-nav');
    if(!nav) return;

    const loginLink = nav.querySelector('a[href*="login.html"]');
    if(user && user.email){
      if(loginLink){
        loginLink.textContent = `Hello, ${user.first_name || 'there'}`;
        loginLink.href = 'login.html';
      }
      const actions = document.querySelector('.ccm-actions');
      if(actions && !actions.querySelector('#ccmLogout')){
        const btn = document.createElement('button');
        btn.id = 'ccmLogout';
        btn.textContent = 'Logout';
        btn.className = 'ccm-btn ghost';
        btn.style.marginLeft = '.5rem';
        btn.addEventListener('click', ()=>{
          clearUser();
          location.reload();
        });
        actions.appendChild(btn);
      }
    } else {
      if(loginLink){ loginLink.textContent = 'Login'; }
      const lo = document.getElementById('ccmLogout');
      if(lo) lo.remove();
    }
  });
})();
