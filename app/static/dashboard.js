const projectGrid = document.getElementById('projectGrid');
const projectForm = document.getElementById('projectForm');
const projectMessage = document.getElementById('projectMessage');
const retentionForm = document.getElementById('retentionForm');
const retentionMessage = document.getElementById('retentionMessage');
const purgeButton = document.getElementById('purgeNow');
const projectSearch = document.getElementById('projectSearch');
const projectFilter = document.getElementById('projectFilter');
const projectSort = document.getElementById('projectSort');
const projectLoadMessage = document.getElementById('projectLoadMessage');
let dashboardProjects = [];

async function apiRequest(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `Erreur serveur (${response.status}).`;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch (error) {
      console.error('Réponse API non JSON', error);
    }
    throw new Error(message);
  }
  return response.json();
}

function messageFor(element, text, type = '') {
  element.textContent = text;
  element.className = `form-message ${type}`.trim();
}

function importVideoWithProgress(projectId, name, file, status) {
  return new Promise((resolve, reject) => {
    const params = new URLSearchParams({ nom: name, filename: file.name });
    const request = new XMLHttpRequest();
    request.open('POST', `/api/projects/${projectId}/stations/import-stream?${params}`);
    request.setRequestHeader('Content-Type', 'application/octet-stream');

    request.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) {
        const percent = Math.round((event.loaded / event.total) * 100);
        const transferredMb = (event.loaded / (1024 * 1024)).toFixed(0);
        const totalMb = (event.total / (1024 * 1024)).toFixed(0);
        messageFor(status, `Import local : ${percent} % (${transferredMb} / ${totalMb} Mo)…`);
      } else {
        messageFor(status, `Import local : ${(event.loaded / (1024 * 1024)).toFixed(0)} Mo transférés…`);
      }
    });
    request.upload.addEventListener('load', () => {
      messageFor(status, 'Vidéo transférée. Extraction de la durée et des images/seconde…');
    });
    request.addEventListener('load', () => {
      let payload;
      try {
        payload = JSON.parse(request.responseText);
      } catch (error) {
        reject(new Error(`Réponse serveur invalide (${request.status}).`));
        return;
      }
      if (request.status < 200 || request.status >= 300) {
        reject(new Error(payload.detail || `Erreur serveur (${request.status}).`));
        return;
      }
      resolve(payload);
    });
    request.addEventListener('error', () => reject(new Error('Échec de la connexion pendant l’import vidéo.')));
    request.addEventListener('abort', () => reject(new Error('Import vidéo interrompu.')));
    request.send(file);
  });
}

function makeStationForm(projectId) {
  const form = document.createElement('form');
  form.className = 'station-form';

  const nameLabel = document.createElement('label');
  nameLabel.append('Nom du poste');
  const nameInput = document.createElement('input');
  nameInput.name = 'nom';
  nameInput.type = 'text';
  nameInput.maxLength = 200;
  nameInput.placeholder = 'Ex. Montage porte';
  nameInput.required = true;
  nameLabel.appendChild(nameInput);

  const videoLabel = document.createElement('label');
  videoLabel.append('Vidéo (MP4, MOV, AVI)');
  const videoInput = document.createElement('input');
  videoInput.name = 'video';
  videoInput.type = 'file';
  videoInput.accept = '.mp4,.mov,.avi,video/mp4,video/quicktime,video/x-msvideo';
  videoInput.required = true;
  videoLabel.appendChild(videoInput);

  const submit = document.createElement('button');
  submit.type = 'submit';
  submit.textContent = 'Ajouter le poste';

  const status = document.createElement('p');
  status.className = 'form-message';
  status.setAttribute('role', 'status');
  form.append(nameLabel, videoLabel, submit, status);

  videoInput.addEventListener('change', () => {
    const file = videoInput.files[0];
    if (file) {
      messageFor(
        status,
        `Vidéo sélectionnée : ${file.name}. Clique sur « Ajouter le poste » pour lancer l’import local.`,
      );
    } else {
      messageFor(status, '');
    }
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const file = videoInput.files[0];
    if (!file) {
      messageFor(status, 'Sélectionne une vidéo à importer.', 'error');
      return;
    }

    submit.disabled = true;
    messageFor(status, 'Préparation de l’import vidéo…');
    try {
      const station = await importVideoWithProgress(projectId, nameInput.value.trim(), file, status);
      window.location.href = `/review/${station.id}?station_id=${station.id}`;
    } catch (error) {
      messageFor(status, error.message, 'error');
      submit.disabled = false;
    }
  });
  return form;
}

function stationStatus(station) {
  if (!station.has_video) return { label: 'Vidéo manquante', className: 'pending' };
  if (!station.phase_count) return { label: 'À analyser', className: 'pending' };
  if (!station.assessment_count) return { label: 'À coter', className: 'pending' };
  return { label: 'Coté', className: 'ready' };
}

function makeScoreChip(method, score, level) {
  const chip = document.createElement('span');
  chip.className = `score-chip${score == null ? '' : ' has-score'}`;
  chip.textContent = score == null ? `${method} · À saisir` : `${method} ${score} · ${level}`;
  return chip;
}

function makeProjectCard(project) {
  const article = document.createElement('article');
  article.className = 'project-card';
  article.id = `project-${project.id}`;

  const cardHeader = document.createElement('div');
  cardHeader.className = 'project-card-header';
  const titleGroup = document.createElement('div');
  const title = document.createElement('h3');
  title.textContent = project.nom;
  const created = document.createElement('p');
  const createdDate = new Date(project.cree_le);
  created.textContent = Number.isNaN(createdDate.getTime())
    ? 'Date de création indisponible'
    : `Créé le ${createdDate.toLocaleDateString('fr-FR')}`;
  titleGroup.append(title, created);
  const takt = document.createElement('span');
  takt.className = 'chip';
  takt.textContent = `Takt ${Number(project.takt_s).toFixed(1)} s`;
  cardHeader.append(titleGroup, takt);

  const overview = document.createElement('div');
  overview.className = 'project-overview';
  const countChip = document.createElement('span');
  countChip.className = 'chip chip-neutral';
  countChip.textContent = `${project.station_count} poste${project.station_count === 1 ? '' : 's'}`;
  const analyzedChip = document.createElement('span');
  analyzedChip.className = 'chip chip-neutral';
  analyzedChip.textContent = `${project.analyzed_station_count} analysé${project.analyzed_station_count === 1 ? '' : 's'}`;
  const assessmentChip = document.createElement('span');
  assessmentChip.className = `chip${project.assessment_count ? '' : ' chip-attention'}`;
  assessmentChip.textContent = `${project.assessment_count} cotation${project.assessment_count === 1 ? '' : 's'} RULA/REBA`;
  overview.append(countChip, analyzedChip, assessmentChip);

  const progress = document.createElement('div');
  progress.className = 'project-progress';
  const progressTrack = document.createElement('div');
  progressTrack.className = 'project-progress-track';
  const progressFill = document.createElement('span');
  progressFill.style.width = `${project.station_count
    ? Math.min(100, (project.analyzed_station_count / project.station_count) * 100)
    : 0}%`;
  progressTrack.appendChild(progressFill);
  const progressLabel = document.createElement('span');
  progressLabel.textContent = project.station_count
    ? `${project.analyzed_station_count}/${project.station_count} postes analysés`
    : 'Aucun poste pour le moment';
  progress.append(progressTrack, progressLabel);

  const stationList = document.createElement('div');
  stationList.className = 'station-list';
  if (!project.stations.length) {
    const empty = document.createElement('p');
    empty.className = 'form-message';
    empty.textContent = 'Ajoute un poste et sa vidéo pour commencer la revue.';
    stationList.appendChild(empty);
  } else {
    for (const station of project.stations) {
      const row = document.createElement('div');
      row.className = 'station-row';
      const link = document.createElement('a');
      link.className = 'station-link';
      link.href = `/review/${station.id}`;
      const copy = document.createElement('span');
      copy.className = 'station-link-copy';
      const name = document.createElement('span');
      name.textContent = station.nom;
      const badge = document.createElement('span');
      badge.className = 'badge';
      badge.textContent = station.has_video
        ? `${Number(station.video_duration_s || 0).toFixed(1)} s · ${Number(station.video_fps || 0).toFixed(1)} i/s`
        : 'vidéo manquante';
      const state = stationStatus(station);
      const stateBadge = document.createElement('span');
      stateBadge.className = `station-state ${state.className}`;
      stateBadge.textContent = state.label;
      const scoreRow = document.createElement('span');
      scoreRow.className = 'station-ergonomics';
      scoreRow.append(
        makeScoreChip('RULA', station.latest_rula_score, station.latest_rula_level),
        makeScoreChip('REBA', station.latest_reba_score, station.latest_reba_level),
      );
      copy.append(name, badge, scoreRow);
      link.append(copy, stateBadge);
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'danger';
      remove.textContent = 'Supprimer';
      remove.setAttribute('aria-label', `Supprimer le poste ${station.nom}, sa vidéo et ses données`);
      remove.addEventListener('click', async () => {
        if (!window.confirm(`Supprimer définitivement « ${station.nom} », sa vidéo et toutes ses phases ? Cette action est irréversible.`)) return;
        remove.disabled = true;
        messageFor(projectMessage, `Suppression de « ${station.nom} »…`);
        try {
          const result = await apiRequest(`/api/stations/${station.id}`, { method: 'DELETE' });
          messageFor(
            projectMessage,
            result.warning || `Le poste « ${station.nom} », sa vidéo et ses données ont été supprimés.`,
            result.warning ? 'error' : 'success',
          );
          await loadProjects();
        } catch (error) {
          messageFor(projectMessage, error.message, 'error');
          remove.disabled = false;
        }
      });
      row.append(link, remove);
      stationList.appendChild(row);
    }
  }

  const actions = document.createElement('div');
  actions.className = 'project-actions';
  const summaryLink = document.createElement('a');
  summaryLink.href = `/projects/${project.id}/summary`;
  summaryLink.textContent = 'Synthèse Yamazumi';
  const deleteProject = document.createElement('button');
  deleteProject.type = 'button';
  deleteProject.className = 'danger';
  deleteProject.textContent = 'Supprimer';
  deleteProject.setAttribute('aria-label', `Supprimer le projet ${project.nom}`);
  deleteProject.addEventListener('click', async () => {
    if (!window.confirm(`Supprimer définitivement le projet « ${project.nom} », tous ses postes, phases et vidéos ? Cette action est irréversible.`)) return;
    deleteProject.disabled = true;
    messageFor(projectMessage, `Suppression du projet « ${project.nom} »…`);
    try {
      const result = await apiRequest(`/api/projects/${project.id}`, { method: 'DELETE' });
      messageFor(
        projectMessage,
        result.warning || `Le projet « ${project.nom} » et toutes ses données ont été supprimés.`,
        result.warning ? 'error' : 'success',
      );
      await loadProjects();
    } catch (error) {
      messageFor(projectMessage, error.message, 'error');
      deleteProject.disabled = false;
    }
  });
  actions.append(summaryLink, deleteProject);

  const stationDetails = document.createElement('details');
  stationDetails.className = 'station-add';
  const stationSummary = document.createElement('summary');
  stationSummary.textContent = 'Ajouter un poste et sa vidéo';
  stationDetails.append(stationSummary, makeStationForm(project.id));

  article.append(cardHeader, overview, progress, actions, stationList, stationDetails);
  return article;
}

function renderProjects() {
  projectGrid.replaceChildren();
  const query = projectSearch.value.trim().toLocaleLowerCase('fr');
  const filter = projectFilter.value;
  const filtered = dashboardProjects.filter((project) => {
    const matchesSearch = !query || project.nom.toLocaleLowerCase('fr').includes(query)
      || project.stations.some((station) => station.nom.toLocaleLowerCase('fr').includes(query));
    const needsAnalysis = project.stations.some((station) => station.has_video && station.phase_count === 0);
    const needsAssessment = project.stations.some((station) => station.phase_count > 0 && station.assessment_count === 0);
    const hasAssessment = project.assessment_count > 0;
    const matchesFilter = filter === 'all'
      || (filter === 'pending' && needsAnalysis)
      || (filter === 'assess' && needsAssessment)
      || (filter === 'assessed' && hasAssessment);
    return matchesSearch && matchesFilter;
  });
  if (projectSort.value === 'name') {
    filtered.sort((first, second) => first.nom.localeCompare(second.nom, 'fr'));
  } else if (projectSort.value === 'assessments') {
    filtered.sort((first, second) => second.assessment_count - first.assessment_count);
  } else {
    filtered.sort((first, second) => second.cree_le.localeCompare(first.cree_le));
  }
  if (!filtered.length) {
    const empty = document.createElement('section');
    empty.className = 'empty-state';
    const heading = document.createElement('h3');
    heading.textContent = dashboardProjects.length
      ? 'Aucun projet ne correspond à ces filtres'
      : 'Aucun projet pour le moment';
    const explanation = document.createElement('p');
    explanation.textContent = dashboardProjects.length
      ? 'Modifie la recherche ou le filtre pour retrouver une étude.'
      : 'Renseigne le nom et le takt ci-dessus pour créer ta première étude.';
    empty.append(heading, explanation);
    projectGrid.appendChild(empty);
    return;
  }
  for (const project of filtered) projectGrid.appendChild(makeProjectCard(project));
}

async function loadProjects() {
  projectGrid.replaceChildren();
  try {
    const dashboard = await apiRequest('/api/dashboard');
    dashboardProjects = dashboard.projects;
    document.getElementById('projectCount').textContent = dashboard.project_count;
    document.getElementById('stationCount').textContent = dashboard.station_count;
    document.getElementById('assessmentCount').textContent = dashboard.assessment_count;
    document.getElementById('pendingProjectCount').textContent = dashboard.projects.filter((project) =>
      project.stations.some((station) => station.has_video && station.phase_count > 0 && station.assessment_count === 0),
    ).length;
    messageFor(projectLoadMessage, `${dashboard.project_count} projet${dashboard.project_count === 1 ? '' : 's'} · ${dashboard.station_count} poste${dashboard.station_count === 1 ? '' : 's'} · données locales`);
    renderProjects();
  } catch (error) {
    dashboardProjects = [];
    const failure = document.createElement('section');
    failure.className = 'empty-state';
    const heading = document.createElement('h3');
    heading.textContent = 'Impossible de charger les projets';
    const explanation = document.createElement('p');
    explanation.textContent = error.message;
    failure.append(heading, explanation);
    projectGrid.appendChild(failure);
    messageFor(projectLoadMessage, 'Échec du chargement du tableau de bord.', 'error');
  }
}

async function loadRetentionSettings() {
  const account = await apiRequest('/api/auth/me');
  const retentionPanel = document.querySelector('.retention-panel');
  if (!account.is_admin) {
    retentionPanel.hidden = true;
    return;
  }
  retentionPanel.hidden = false;
  try {
    const settings = await apiRequest('/api/settings');
    document.getElementById('purgeDays').value = settings.purge_days || '90';
    document.getElementById('videoMaxMb').value = settings.video_max_mb || '2048';
  } catch (error) {
    messageFor(retentionMessage, `Impossible de charger le délai de conservation : ${error.message}`, 'error');
  }
}

async function initializeDashboard() {
  await loadProjects();
  await loadRetentionSettings();
}

projectForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = projectForm.querySelector('button[type="submit"]');
  const formData = new FormData(projectForm);
  button.disabled = true;
  messageFor(projectMessage, 'Création du projet…');
  try {
    await apiRequest('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        nom: String(formData.get('nom')).trim(),
        takt_s: Number(formData.get('takt_s')),
      }),
    });
    projectForm.reset();
    messageFor(projectMessage, 'Projet créé. Ajoute maintenant un poste et sa vidéo.', 'success');
    await loadProjects();
  } catch (error) {
    messageFor(projectMessage, error.message, 'error');
  } finally {
    button.disabled = false;
  }
});

retentionForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = retentionForm.querySelector('button[type="submit"]');
  button.disabled = true;
  messageFor(retentionMessage, 'Enregistrement des réglages…');
  try {
    const settings = await apiRequest('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        purge_days: document.getElementById('purgeDays').value,
        video_max_mb: document.getElementById('videoMaxMb').value,
      }),
    });
    document.getElementById('purgeDays').value = settings.purge_days;
    document.getElementById('videoMaxMb').value = settings.video_max_mb;
    messageFor(retentionMessage, 'Réglages enregistrés. La purge automatique s’exécute au démarrage et chaque jour.', 'success');
  } catch (error) {
    messageFor(retentionMessage, error.message, 'error');
  } finally {
    button.disabled = false;
  }
});

purgeButton.addEventListener('click', async () => {
  if (!window.confirm('Supprimer maintenant tous les projets plus anciens que le délai configuré, avec leurs vidéos et données ? Cette action est irréversible.')) return;
  purgeButton.disabled = true;
  messageFor(retentionMessage, 'Recherche des données expirées…');
  try {
    const result = await apiRequest('/api/maintenance/purge', { method: 'POST' });
    messageFor(
      retentionMessage,
      `Purge terminée : ${result.projects_deleted} projet(s) et ${result.videos_deleted} vidéo(s) supprimés.${result.external_files_preserved ? ` ${result.external_files_preserved} fichier(s) référencé(s) hors du dossier géré ont été conservés.` : ''}`,
      result.external_files_preserved ? 'error' : 'success',
    );
    await loadProjects();
  } catch (error) {
    messageFor(retentionMessage, error.message, 'error');
  } finally {
    purgeButton.disabled = false;
  }
});

projectSearch.addEventListener('input', renderProjects);
projectFilter.addEventListener('change', renderProjects);
projectSort.addEventListener('change', renderProjects);

initializeDashboard().catch((error) => {
  messageFor(retentionMessage, `Impossible de charger les réglages : ${error.message}`, 'error');
});
