async function addAccountControls() {
  const response = await fetch('/api/auth/me');
  if (!response.ok) {
    window.location.replace('/login');
    return;
  }
  const user = await response.json();
  fetch('/api/health')
    .then((healthResponse) => {
      if (!healthResponse.ok) throw new Error(`État du serveur indisponible (${healthResponse.status}).`);
      return healthResponse.json();
    })
    .then((health) => {
      if (!health.transport_warning) return;
      const notice = document.createElement('p');
      notice.className = 'transport-warning';
      notice.setAttribute('role', 'alert');
      notice.textContent = health.transport_warning;
      document.body.prepend(notice);
    })
    .catch((error) => console.error('Impossible de vérifier la sécurité de la connexion.', error));
  const header = document.querySelector('.topbar');
  if (!header) return;
  const controls = document.createElement('div');
  controls.className = 'account-controls';
  const identity = document.createElement('span');
  identity.textContent = `Connecté : ${user.username}`;
  controls.appendChild(identity);
  if (user.is_admin) {
    const adminLink = document.createElement('a');
    adminLink.href = '/admin/users';
    adminLink.textContent = 'Gérer les comptes';
    controls.appendChild(adminLink);
  }
  const passwordDetails = document.createElement('details');
  const passwordSummary = document.createElement('summary');
  passwordSummary.textContent = 'Changer mon mot de passe';
  const passwordForm = document.createElement('form');
  passwordForm.className = 'account-password-form';
  const currentPassword = document.createElement('input');
  currentPassword.type = 'password';
  currentPassword.autocomplete = 'current-password';
  currentPassword.placeholder = 'Mot de passe actuel';
  currentPassword.required = true;
  const newPassword = document.createElement('input');
  newPassword.type = 'password';
  newPassword.autocomplete = 'new-password';
  newPassword.placeholder = 'Nouveau mot de passe (12 caractères min.)';
  newPassword.minLength = 12;
  newPassword.required = true;
  const savePassword = document.createElement('button');
  savePassword.type = 'submit';
  savePassword.textContent = 'Enregistrer';
  const passwordStatus = document.createElement('span');
  passwordStatus.setAttribute('role', 'status');
  passwordForm.append(currentPassword, newPassword, savePassword, passwordStatus);
  passwordForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    savePassword.disabled = true;
    try {
      const result = await fetch('/api/auth/password', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_password: currentPassword.value,
          new_password: newPassword.value,
        }),
      });
      const body = await result.json();
      if (!result.ok) throw new Error(body.detail || `Erreur (${result.status}).`);
      passwordStatus.textContent = body.status;
      window.location.replace('/login');
    } catch (error) {
      passwordStatus.textContent = error.message;
      savePassword.disabled = false;
    }
  });
  passwordDetails.append(passwordSummary, passwordForm);
  controls.appendChild(passwordDetails);
  const logoutButton = document.createElement('button');
  logoutButton.type = 'button';
  logoutButton.className = 'secondary';
  logoutButton.textContent = 'Déconnexion';
  logoutButton.addEventListener('click', async () => {
    const result = await fetch('/api/auth/logout', { method: 'POST' });
    if (!result.ok) {
      window.alert('La déconnexion a échoué.');
      return;
    }
    window.location.replace('/login');
  });
  controls.appendChild(logoutButton);
  header.appendChild(controls);
}

addAccountControls().catch((error) => {
  console.error('Impossible de charger le compte connecté.', error);
  window.location.replace('/login');
});
