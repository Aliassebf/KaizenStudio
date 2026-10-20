const form = document.querySelector('#loginForm, #setupForm');
const message = document.getElementById('authMessage');

fetch('/api/health')
  .then((response) => {
    if (!response.ok) throw new Error(`État du serveur indisponible (${response.status}).`);
    return response.json();
  })
  .then((health) => {
    if (!health.transport_warning) return;
    const notice = document.createElement('p');
    notice.className = 'transport-warning';
    notice.setAttribute('role', 'alert');
    notice.textContent = health.transport_warning;
    document.querySelector('.auth-panel').prepend(notice);
  })
  .catch((error) => console.error('Impossible de vérifier la sécurité de la connexion.', error));

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = new FormData(form);
  const setup = form.id === 'setupForm';
  const endpoint = setup ? '/api/auth/setup' : '/api/auth/login';
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  message.textContent = 'Connexion en cours…';
  message.className = 'form-message';
  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: String(data.get('username')).trim(),
        password: String(data.get('password')),
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `Erreur (${response.status}).`);
    window.location.replace('/');
  } catch (error) {
    message.textContent = error.message;
    message.className = 'form-message error';
    button.disabled = false;
  }
});
