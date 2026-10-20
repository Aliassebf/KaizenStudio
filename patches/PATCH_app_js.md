# Correctifs front-end (`app/static/app.js` et pages associées)

## F1 — `apiRequest` robuste (session expirée, 204, délai, erreurs réseau)

**Remplacer** la fonction `apiRequest` (≈ L120) par :

```js
class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function apiRequest(url, options = {}, timeoutMs = 120000) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetch(url, { credentials: 'same-origin', ...options, signal: options.signal || controller.signal });
  } catch (error) {
    throw new ApiError(
      error.name === 'AbortError'
        ? 'Le serveur ne répond pas (délai dépassé).'
        : 'Serveur Kaizen Studio injoignable. Vérifiez qu’il est toujours lancé.',
      0,
    );
  } finally {
    window.clearTimeout(timer);
  }
  if (response.status === 401) {
    window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname)}`);
    throw new ApiError('Session expirée : reconnectez-vous.', 401);
  }
  if (!response.ok) {
    let message = `Erreur serveur (${response.status}).`;
    try {
      const body = await response.json();
      message = typeof body.detail === 'string'
        ? body.detail
        : Array.isArray(body.detail)
          ? body.detail.map((item) => item.msg).join(' · ')   // erreurs de validation FastAPI (422)
          : message;
    } catch (error) {
      console.error('Réponse API non JSON', error);
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return null;
  const type = response.headers.get('content-type') || '';
  return type.includes('application/json') ? response.json() : response;
}
```
> Aujourd'hui, une session expirée (12 h, `SESSION_HOURS` dans `auth.py`) produit des messages « Authentification
> requise » dans chaque panneau au lieu de renvoyer vers la connexion, et les erreurs 422 de
> Pydantic s'affichent « [object Object] ».

## F2 — Confirmation avant ré-analyse (pendant de P4 côté serveur)

```js
async function postWithReviewConfirmation(url, body) {
  const send = (force) => apiRequest(`${url}${force ? '?force=true' : ''}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  try {
    return await send(false);
  } catch (error) {
    if (error.status !== 409 || !/décrites|classées|chronométrées/.test(error.message)) throw error;
    if (!window.confirm(`${error.message}\n\nContinuer et remplacer les phases ?`)) {
      throw new ApiError('Analyse annulée : les phases existantes sont conservées.', 409);
    }
    return send(true);
  }
}
```
Utiliser `postWithReviewConfirmation` pour `POST /api/stations/${stationId}/analysis`
et `POST /api/stations/${stationId}/resegment`.

⚠️ **Point critique** : `scheduleAnalysisAfterSettingChange` (≈ L1801) relance **automatiquement**
`resegmentPhases` ou `startAnalysis` 450 ms après chaque relâchement des curseurs seuil / durée
minimale. Un simple réglage efface donc toutes les phases décrites. Remplacer par :
```js
function scheduleAnalysisAfterSettingChange() {
  if (!state.station?.has_video) return;
  const reviewed = state.phases.some((phase) => phase.chrono_reel_s != null
    || (phase.commentaire || '').trim()
    || (phase.categorie && phase.categorie !== 'Non classé')
    || !/^(Activité détectée|Arrêt détecté|Phase fusionnée)/.test(phase.description || ''));
  if (reviewed) {
    showAnalysisStatus('Réglages modifiés. Les phases déjà décrites sont conservées : cliquez sur « Analyser » pour recalculer.');
    return;
  }
  window.clearTimeout(analysisDebounce);
  analysisDebounce = window.setTimeout(state.motionSamples.length ? resegmentPhases : startAnalysis, 450);
}
```

## F3 — Polling des tâches : arrêt propre et tolérance réseau

Factoriser la boucle `do { … } while (status === 'queued' || 'running')` (posture **et** mouvement) :

```js
async function pollJob(pollUrl, onProgress, { intervalMs = 500, maxErrors = 5 } = {}) {
  let errors = 0;
  for (;;) {
    await new Promise((resolve) => window.setTimeout(resolve, document.hidden ? intervalMs * 4 : intervalMs));
    try {
      const job = await apiRequest(pollUrl, {}, 15000);
      errors = 0;
      onProgress(job);
      if (job.status !== 'queued' && job.status !== 'running') return job;
    } catch (error) {
      if (error.status === 404 || ++errors >= maxErrors) throw error;
    }
  }
}
```
> Une micro-coupure Wi-Fi en mode réseau fait aujourd'hui échouer l'analyse côté interface alors
> qu'elle continue côté serveur.

## F4 — Surcouche posture alignée sur l'image réellement affichée

`drawPostureOverlay` utilise `video.clientWidth/clientHeight`. Si le `<video>` est en
`object-fit: contain` (bandes noires), le squelette est décalé. Calculer la zone utile :

```js
function displayedVideoRect() {
  const boxW = video.clientWidth, boxH = video.clientHeight;
  const ratio = video.videoWidth / video.videoHeight;
  let width = boxW, height = boxW / ratio;
  if (height > boxH) { height = boxH; width = boxH * ratio; }
  return { left: video.offsetLeft + (boxW - width) / 2, top: video.offsetTop + (boxH - height) / 2, width, height };
}
```
puis utiliser `rect.width/rect.height/rect.left/rect.top` à la place de `width/height/offsetLeft/offsetTop`.

## F5 — Découpage de `app.js` (2 261 lignes) sans outil de build

Passer `review.html` en `<script type="module" src="/static/review/main.js?v=…">` et répartir :

| Module | Contenu actuel de app.js |
|---|---|
| `review/api.js` | `apiRequest`, `pollJob`, `postWithReviewConfirmation` |
| `review/state.js` | objet `state`, sauvegarde de configuration par section |
| `review/timeline.js` | frise, phases, filtres, graphe de mouvement |
| `review/roi.js` | dessin/liste des ROI |
| `review/operations.js` | référentiel, annotations, apprentissage local |
| `review/cycles.js` | cycles et suggestions |
| `review/ergonomics.js` | posture, surcouche, pré-cotation, historique |
| `review/main.js` | initialisation, onglets, raccourcis clavier |

Aucun CDN, compatible avec la CSP `script-src 'self'` (P10). Mettre à jour `test_review_ui.py`
pour pointer vers les nouveaux fichiers.
