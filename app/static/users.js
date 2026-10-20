const accountForm = document.getElementById('accountForm');
const userList = document.getElementById('userList');
const usersMessage = document.getElementById('usersMessage');
let currentUserId = null;

async function loadUsers() {
  const currentUserResponse = await fetch('/api/auth/me');
  if (!currentUserResponse.ok) throw new Error('Session expirée. Reconnectez-vous.');
  const currentUser = await currentUserResponse.json();
  currentUserId = currentUser.id;
  const response = await fetch('/api/admin/users');
  const users = await response.json();
  if (!response.ok) throw new Error(users.detail || `Erreur (${response.status}).`);
  userList.replaceChildren();
  for (const user of users) {
    const row = document.createElement('div');
    row.className = 'account-row';
    const summary = document.createElement('div');
    const name = document.createElement('strong');
    name.textContent = user.username;
    const status = document.createElement('span');
    status.className = 'account-status';
    status.textContent = `${user.is_admin ? 'Administrateur' : 'Utilisateur'} · ${user.is_active ? 'Actif' : 'Désactivé'}`;
    summary.append(name, status);
    row.appendChild(summary);
    const resetDetails = document.createElement('details');
    const resetSummary = document.createElement('summary');
    resetSummary.textContent = user.id === currentUserId
      ? 'Réinitialiser mon mot de passe administrateur'
      : 'Réinitialiser le mot de passe';
    const resetForm = document.createElement('form');
    resetForm.className = 'users-form';
    const resetInput = document.createElement('input');
    resetInput.type = 'password';
    resetInput.minLength = 12;
    resetInput.autocomplete = 'new-password';
    resetInput.placeholder = 'Nouveau mot de passe (12 caractères min.)';
    resetInput.required = true;
    const resetButton = document.createElement('button');
    resetButton.type = 'submit';
    resetButton.textContent = 'Appliquer';
    resetForm.append(resetInput, resetButton);
    resetForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      resetButton.disabled = true;
      try {
        const result = await fetch(`/api/admin/users/${user.id}/password`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ new_password: resetInput.value }),
        });
        const body = await result.json();
        if (!result.ok) throw new Error(body.detail || `Erreur (${result.status}).`);
        resetForm.reset();
        if (user.id === currentUserId) {
          usersMessage.textContent = 'Mot de passe administrateur modifié. Reconnectez-vous avec le nouveau mot de passe.';
          usersMessage.className = 'form-message';
          window.setTimeout(() => window.location.replace('/login'), 1200);
          return;
        }
        usersMessage.textContent = `Mot de passe de ${user.username} réinitialisé.`;
        usersMessage.className = 'form-message';
        resetDetails.open = false;
      } catch (error) {
        usersMessage.textContent = error.message;
        usersMessage.className = 'form-message error';
        resetButton.disabled = false;
      }
    });
    resetDetails.append(resetSummary, resetForm);
    row.appendChild(resetDetails);
    if (!user.is_admin) {
      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = user.is_active ? 'secondary' : '';
      toggle.textContent = user.is_active ? 'Désactiver' : 'Réactiver';
      toggle.addEventListener('click', async () => {
        toggle.disabled = true;
        try {
          const result = await fetch(`/api/admin/users/${user.id}/active`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_active: !user.is_active }),
          });
          const body = await result.json();
          if (!result.ok) throw new Error(body.detail || `Erreur (${result.status}).`);
          await loadUsers();
        } catch (error) {
          usersMessage.textContent = error.message;
          usersMessage.className = 'form-message error';
          toggle.disabled = false;
        }
      });
      row.appendChild(toggle);
    }
    userList.appendChild(row);
  }
}

accountForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = accountForm.querySelector('button[type="submit"]');
  const fields = new FormData(accountForm);
  button.disabled = true;
  try {
    const response = await fetch('/api/admin/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: String(fields.get('username')).trim(),
        password: String(fields.get('password')),
        is_admin: fields.get('is_admin') === 'true',
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `Erreur (${response.status}).`);
    accountForm.reset();
    usersMessage.textContent = `Le compte ${result.username} (${result.is_admin ? 'administrateur' : 'utilisateur'}) a été créé.`;
    usersMessage.className = 'form-message';
    await loadUsers();
  } catch (error) {
    usersMessage.textContent = error.message;
    usersMessage.className = 'form-message error';
  } finally {
    button.disabled = false;
  }
});

loadUsers().catch((error) => {
  usersMessage.textContent = error.message;
  usersMessage.className = 'form-message error';
});
