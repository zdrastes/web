(() => {
  'use strict';
  const root = document.getElementById('portal-profile-controls');
  if (!root || location.protocol === 'file:') return;
  const $ = id => document.getElementById(id);
  const profile = $('portal-profile-button');
  const panel = $('portal-profile-panel');
  const help = $('portal-help');
  const chip = $('ld-user');
  const employee = $('task-employee');
  const login = $('tasks-signin');
  const sessionKey = 'zdrastes.web.demo.tasks-signed-out';

  function toggleProfile(open) {
    panel.hidden = !open;
    profile.setAttribute('aria-expanded', String(open));
  }

  function updateProfile() {
    if (chip) root.hidden = chip.hidden;
    const name = chip?.textContent.trim() || employee?.selectedOptions[0]?.textContent || 'Демосотрудник';
    $('portal-profile-name').textContent = name;
    profile.textContent = name.split(/\s+/).slice(0, 2).map(part => part[0]).join('').toUpperCase();
    profile.setAttribute('aria-label', 'Аккаунт: ' + name);
    if (root.hidden) toggleProfile(false);
  }

  function showTasksSession(signedOut) {
    login.hidden = !signedOut;
    $('tasks-workspace').hidden = signedOut;
    root.hidden = signedOut;
    if (signedOut) $('tasks-login').focus();
  }

  profile.addEventListener('click', () => toggleProfile(panel.hidden));
  $('portal-help-button').addEventListener('click', () => {
    toggleProfile(false);
    help.showModal();
  });
  $('portal-help-close').addEventListener('click', () => help.close());
  $('portal-profile-logout').addEventListener('click', () => {
    toggleProfile(false);
    if (chip) {
      $('ld-logout').click();
      $('ld-demo-login').focus();
      return;
    }
    try { sessionStorage.setItem(sessionKey, '1'); } catch {}
    showTasksSession(true);
  });
  document.addEventListener('click', event => {
    if (!panel.hidden && !root.contains(event.target)) toggleProfile(false);
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !panel.hidden) {
      toggleProfile(false);
      profile.focus();
    }
  });
  if (chip) {
    new MutationObserver(updateProfile).observe(chip, {
      attributes: true, attributeFilter: ['hidden'], childList: true, subtree: true,
    });
  } else if (login) {
    $('tasks-login').addEventListener('click', () => {
      try { sessionStorage.removeItem(sessionKey); } catch {}
      showTasksSession(false);
      profile.focus();
    });
    const restore = () => {
      let signedOut = false;
      try { signedOut = sessionStorage.getItem(sessionKey) === '1'; } catch {}
      showTasksSession(signedOut);
    };
    window.addEventListener('pageshow', restore);
    restore();
    employee?.addEventListener('change', updateProfile);
  }
  updateProfile();
})();