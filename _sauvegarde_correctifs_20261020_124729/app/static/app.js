const stationFromPath = window.location.pathname.match(/^\/review\/(\d+)\/?$/);
const stationId = new URLSearchParams(window.location.search).get('station_id')
  || (stationFromPath ? stationFromPath[1] : null);
const video = document.getElementById('videoPlayer');
const sharedVideoTime = document.getElementById('sharedVideoTime');
const timeline = document.getElementById('timeline');
const selectedInterval = document.getElementById('selectedInterval');
const playFullVideoButton = document.getElementById('playFullVideo');
const phaseList = document.getElementById('phaseList');
const phaseCount = document.getElementById('phaseCount');
const phaseSearch = document.getElementById('phaseSearch');
const phaseTypeFilter = document.getElementById('phaseTypeFilter');
const phaseCategoryFilter = document.getElementById('phaseCategoryFilter');
const phaseFilterCount = document.getElementById('phaseFilterCount');
const stationTitle = document.getElementById('stationTitle');
const configurationSaveStatus = document.getElementById('configurationSaveStatus');
const thresholdSlider = document.getElementById('thresholdSlider');
const minLengthSlider = document.getElementById('minLengthSlider');
const rangeValues = document.getElementById('rangeValues');
const playToggle = document.getElementById('playToggle');
const motionChart = document.getElementById('motionChart');
const analyzeButton = document.getElementById('analyzeButton');
const analysisStatus = document.getElementById('analysisStatus');
const analysisProgress = document.getElementById('analysisProgress');
const roiFrame = document.getElementById('roiFrame');
const roiCanvas = document.getElementById('roiCanvas');
const roiPreview = document.getElementById('roiPreview');
const roiList = document.getElementById('roiList');
const roiStatus = document.getElementById('roiStatus');
const addRoiButton = document.getElementById('addRoi');
const clearRoiButton = document.getElementById('clearRoi');
const postureOverlay = document.getElementById('postureOverlay');
const postureProgress = document.getElementById('postureProgress');
const postureStatus = document.getElementById('postureStatus');
const postureReadout = document.getElementById('postureReadout');
const postureCandidateList = document.getElementById('postureCandidateList');
const postureCandidateSummary = document.getElementById('postureCandidateSummary');
const analyzePostureButton = document.getElementById('analyzePosture');
const assessmentForm = document.getElementById('ergonomicAssessmentForm');
const assessmentMessage = document.getElementById('assessmentMessage');
const assessmentHistory = document.getElementById('ergonomicAssessmentHistory');
const assessmentTimeInput = document.getElementById('assessmentTime');
const assessmentAngleHint = document.getElementById('assessmentAngleHint');
const useCurrentAssessmentTime = document.getElementById('useCurrentAssessmentTime');
const prefillAssessmentButton = document.getElementById('prefillAssessment');
const scoringResult = document.getElementById('scoringResult');
const cameraView = document.getElementById('cameraView');
const operationCatalog = document.getElementById('operationCatalog');
const operationSuggestions = document.getElementById('operationSuggestions');
const operationForm = document.getElementById('operationForm');
const operationName = document.getElementById('operationName');
const operationStatus = document.getElementById('operationStatus');
const datasetSplit = document.getElementById('datasetSplit');
const annotationDatasetSummary = document.getElementById('annotationDatasetSummary');
const downloadAnnotationManifest = document.getElementById('downloadAnnotationManifest');
const trainOperationModelButton = document.getElementById('trainOperationModel');
const suggestOperationsButton = document.getElementById('suggestOperations');
const operationModelStatus = document.getElementById('operationModelStatus');
const operationModelResults = document.getElementById('operationModelResults');
const modelSuggestionStatus = document.getElementById('modelSuggestionStatus');
const modelSuggestions = document.getElementById('modelSuggestions');
const annotationTimeline = document.getElementById('annotationTimeline');
const annotationForm = document.getElementById('annotationForm');
const annotationOperation = document.getElementById('annotationOperation');
const annotationStart = document.getElementById('annotationStart');
const annotationEnd = document.getElementById('annotationEnd');
const annotationStatus = document.getElementById('annotationStatus');
const annotationVideoTime = document.getElementById('annotationVideoTime');
const videoAnnotationList = document.getElementById('videoAnnotationList');
const saveAnnotation = document.getElementById('saveAnnotation');
const cancelAnnotationEdit = document.getElementById('cancelAnnotationEdit');
const cycleStartInput = document.getElementById('cycleStart');
const cycleEndInput = document.getElementById('cycleEnd');
const cycleStatus = document.getElementById('cycleStatus');
const cycleList = document.getElementById('cycleList');
const cycleCandidates = document.getElementById('cycleCandidates');
const cycleControls = [
  cycleStartInput,
  cycleEndInput,
  document.getElementById('setCycleStart'),
  document.getElementById('setCycleEnd'),
  document.getElementById('saveCycle'),
  document.getElementById('suggestCycles'),
  document.getElementById('minimumStop'),
  document.getElementById('minimumCycle'),
];
const selectedPhases = new Set();

for (const select of assessmentForm.querySelectorAll('[data-boolean-factor]')) {
  for (const [value, label] of [['', 'Non renseigné'], ['true', 'Oui'], ['false', 'Non']]) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }
}

const state = {
  station: null,
  phases: [],
  operations: [],
  annotations: [],
  annotationEditId: null,
  annotationDataset: null,
  operationModel: null,
  modelSuggestions: [],
  postureSamples: [],
  selectedPostureSample: null,
  ergonomicAssessments: [],
  motionSamples: [],
  cycles: [],
  cycleSuggestions: [],
  selectedPhaseId: null,
  playbackEnd: null,
  detectedThreshold: 0,
  rois: [],
  threshold: Number(thresholdSlider.value),
  minLength: Number(minLengthSlider.value),
  busy: false,
};

const categoryOptions = ['Non classé', 'VA', 'NVA nécessaire', 'Gaspillage'];

async function apiRequest(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `Erreur serveur (${response.status}).`;
    try {
      message = (await response.json()).detail || message;
    } catch (error) {
      console.error('Réponse API non JSON', error);
    }
    throw new Error(message);
  }
  return response.json();
}

const configurationSaveTimers = new Map();
const configurationSaveQueues = new Map();

function readConfigurationSection(section) {
  if (section === 'review') {
    const endValue = document.getElementById('windowEnd').value;
    return {
      threshold_pct: Number(thresholdSlider.value),
      min_phase_seconds: Number(minLengthSlider.value),
      window_start: Number(document.getElementById('windowStart').value || 0),
      window_end: endValue === '' ? null : Number(endValue),
    };
  }
  if (section === 'operations') {
    return {
      operation_name: operationName.value,
      annotation_operation: annotationOperation.value,
      annotation_start: annotationStart.value,
      annotation_end: annotationEnd.value,
    };
  }
  if (section === 'cycles') {
    return {
      cycle_start: cycleStartInput.value,
      cycle_end: cycleEndInput.value,
      minimum_stop: document.getElementById('minimumStop').value === ''
        ? null : Number(document.getElementById('minimumStop').value),
      minimum_cycle: document.getElementById('minimumCycle').value === ''
        ? null : Number(document.getElementById('minimumCycle').value),
    };
  }
  if (section === 'ergonomics') {
    const values = {};
    for (const control of assessmentForm.elements) {
      if (!control.name || control.name === 'official_method_confirmed' || control.type === 'checkbox') continue;
      values[control.name] = control.value;
    }
    return values;
  }
  throw new Error(`Section de configuration inconnue : ${section}`);
}

function applyAnalysisConfiguration(payload) {
  const configuration = payload.analysis_configuration || {};
  const review = configuration.review || {};
  thresholdSlider.value = review.threshold_pct ?? 0;
  minLengthSlider.value = review.min_phase_seconds ?? 1;
  document.getElementById('windowStart').value = review.window_start ?? payload.fenetre_debut ?? 0;
  document.getElementById('windowEnd').value =
    review.window_end ?? payload.fenetre_fin ?? payload.video_duration_s ?? '';
  state.threshold = Number(thresholdSlider.value);
  state.minLength = Number(minLengthSlider.value);

  const operations = configuration.operations || {};
  operationName.value = operations.operation_name ?? '';
  annotationOperation.value = operations.annotation_operation ?? '';
  annotationStart.value = operations.annotation_start ?? '';
  annotationEnd.value = operations.annotation_end ?? '';

  const cycles = configuration.cycles || {};
  cycleStartInput.value = cycles.cycle_start ?? '';
  cycleEndInput.value = cycles.cycle_end ?? '';
  document.getElementById('minimumStop').value = cycles.minimum_stop ?? 2;
  document.getElementById('minimumCycle').value = cycles.minimum_cycle ?? 5;

  const ergonomics = configuration.ergonomics || {};
  for (const [name, value] of Object.entries(ergonomics)) {
    const control = assessmentForm.elements.namedItem(name);
    if (control && control.name !== 'official_method_confirmed') control.value = value ?? '';
  }
  assessmentForm.elements.official_method_confirmed.checked = false;
}

function scheduleConfigurationSave(section) {
  if (!state.station || !stationId) return;
  window.clearTimeout(configurationSaveTimers.get(section));
  configurationSaveTimers.set(section, window.setTimeout(() => {
    const previous = configurationSaveQueues.get(section) || Promise.resolve();
    const request = previous.catch(() => {}).then(() => apiRequest(
      `/api/stations/${stationId}/analysis-configuration`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ section, values: readConfigurationSection(section) }),
      },
    ));
    configurationSaveQueues.set(section, request);
    configurationSaveStatus.textContent = 'Enregistrement des paramètres sur cet ordinateur…';
    configurationSaveStatus.className = 'configuration-save-status subtle';
    request.then(() => {
      if (configurationSaveQueues.get(section) === request) {
        configurationSaveStatus.textContent = 'Paramètres enregistrés localement.';
        configurationSaveStatus.className = 'configuration-save-status subtle success';
      }
    }).catch((error) => {
      console.error(`Échec de la sauvegarde des paramètres « ${section} »`, error);
      configurationSaveStatus.textContent = `Échec de sauvegarde des paramètres : ${error.message}`;
      configurationSaveStatus.className = 'configuration-save-status form-message error';
    });
  }, 350));
}

function formatSeconds(value) {
  if (value == null || Number.isNaN(Number(value))) return '0.0 s';
  const seconds = Number(value);
  if (seconds >= 3600) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = (seconds % 60).toFixed(1).padStart(4, '0');
    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${remainder}`;
  }
  return `${seconds.toFixed(1)} s`;
}

function phaseLabel(phase) {
  return phase.type_auto === 'activity' ? 'Activité' : 'Arrêt';
}

function phaseDisplayLabel(phase) {
  return `${phase.ordre}. ${phaseLabel(phase)}`;
}

function normalizePhaseSearch(value) {
  return String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('fr');
}

function keepTimelineSegmentVisible(segment) {
  if (!segment) return;
  const timelineBounds = timeline.getBoundingClientRect();
  const segmentBounds = segment.getBoundingClientRect();
  if (segmentBounds.left < timelineBounds.left) {
    timeline.scrollBy({ left: segmentBounds.left - timelineBounds.left, behavior: 'smooth' });
  } else if (segmentBounds.right > timelineBounds.right) {
    timeline.scrollBy({ left: segmentBounds.right - timelineBounds.right, behavior: 'smooth' });
  }
}

function updateSelectedPhaseCard(phaseId) {
  phaseList.querySelectorAll('.phase-item[data-phase-id]').forEach((item) => {
    const selected = item.dataset.phaseId === String(phaseId);
    item.classList.toggle('selected-phase', selected);
    if (selected) item.setAttribute('aria-current', 'true');
    else item.removeAttribute('aria-current');
  });
}

function updateSelectedTimelineSegment(phaseId) {
  timeline.querySelectorAll('.timeline-segment[data-phase-id]').forEach((segment) => {
    const selected = segment.dataset.phaseId === String(phaseId);
    segment.classList.toggle('selected', selected);
    segment.setAttribute('aria-pressed', String(selected));
  });
}

function selectPhase(phase, play = true) {
  state.selectedPhaseId = phase.id;
  const start = Number(phase.debut_s);
  const end = Number(phase.fin_s);
  selectedInterval.textContent =
    `${phaseDisplayLabel(phase)} · ${formatSeconds(start)} → ${formatSeconds(end)} · intervalle ${formatSeconds(end - start)}`;
  updateSelectedTimelineSegment(phase.id);
  renderMotionChart();
  const segment = timeline.querySelector(`[data-phase-id="${phase.id}"]`);
  keepTimelineSegmentVisible(segment);
  updateSelectedPhaseCard(phase.id);
  video.currentTime = start;
  if (play) {
    state.playbackEnd = end;
    video.play().catch((error) => {
      state.playbackEnd = null;
      showAnalysisStatus(`Lecture de la phase impossible : ${error.message}`, true);
    });
  } else {
    state.playbackEnd = null;
  }
}

function showAnalysisStatus(text, isError = false) {
  analysisStatus.textContent = text;
  analysisStatus.className = `form-message${isError ? ' error' : ''}`;
}

function drawPostureOverlay() {
  if (!postureOverlay || !video.videoWidth || !video.clientWidth) return;
  const pixelRatio = window.devicePixelRatio || 1;
  const width = video.clientWidth;
  const height = video.clientHeight;
  postureOverlay.width = Math.round(width * pixelRatio);
  postureOverlay.height = Math.round(height * pixelRatio);
  postureOverlay.style.width = `${width}px`;
  postureOverlay.style.height = `${height}px`;
  postureOverlay.style.left = `${video.offsetLeft}px`;
  postureOverlay.style.top = `${video.offsetTop}px`;
  const context = postureOverlay.getContext('2d');
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  context.clearRect(0, 0, width, height);
  if (!state.postureSamples.length) return;

  let nearest = null;
  let difference = Infinity;
  for (const sample of state.postureSamples) {
    const distance = Math.abs(Number(sample.time_s) - video.currentTime);
    if (distance < difference) {
      nearest = sample;
      difference = distance;
    }
  }
  if (!nearest || difference > 0.8) {
    postureReadout.textContent = 'Aucune image de posture proche de cet instant.';
    return;
  }

  const points = nearest.points;
  const links = [
    ['left_shoulder', 'right_shoulder'],
    ['left_shoulder', 'left_elbow'], ['left_elbow', 'left_wrist'],
    ['right_shoulder', 'right_elbow'], ['right_elbow', 'right_wrist'],
    ['left_shoulder', 'left_hip'], ['right_shoulder', 'right_hip'],
    ['left_hip', 'right_hip'],
    ['left_hip', 'left_knee'], ['left_knee', 'left_ankle'],
    ['right_hip', 'right_knee'], ['right_knee', 'right_ankle'],
  ];
  context.lineWidth = 3;
  context.strokeStyle = '#20d878';
  for (const [first, second] of links) {
    const a = points[first];
    const b = points[second];
    if (!a || !b || a.visibility < 0.35 || b.visibility < 0.35) continue;
    context.beginPath();
    context.moveTo(a.x * width, a.y * height);
    context.lineTo(b.x * width, b.y * height);
    context.stroke();
  }
  context.fillStyle = '#f3c623';
  for (const point of Object.values(points)) {
    if (point.visibility < 0.35) continue;
    context.beginPath();
    context.arc(point.x * width, point.y * height, 4, 0, Math.PI * 2);
    context.fill();
  }
  const angleLabels = {
    left_elbow: 'Coude G',
    right_elbow: 'Coude D',
    left_shoulder: 'Épaule G',
    right_shoulder: 'Épaule D',
    left_knee: 'Genou G',
    right_knee: 'Genou D',
    trunk_inclination: 'Inclinaison du tronc',
  };
  postureReadout.replaceChildren();
  const heading = document.createElement('strong');
  heading.textContent = `Image analysée à ${Number(nearest.time_s).toFixed(1)} s — angles 2D estimés`;
  postureReadout.appendChild(heading);
  const details = document.createElement('div');
  details.textContent = Object.entries(nearest.angles)
    .map(([key, value]) => `${angleLabels[key]} : ${value == null ? 'non visible' : `${value}°`}`)
    .join(' · ');
  postureReadout.appendChild(details);
}

function postureSummaryAt(timeSeconds) {
  if (!state.postureSamples.length) return null;
  return state.postureSamples.reduce((nearest, sample) =>
    Math.abs(Number(sample.time_s) - timeSeconds) < Math.abs(Number(nearest.time_s) - timeSeconds)
      ? sample
      : nearest,
  );
}

const postureAngleLabels = {
  left_elbow: 'Coude G',
  right_elbow: 'Coude D',
  left_shoulder: 'Épaule G',
  right_shoulder: 'Épaule D',
  left_knee: 'Genou G',
  right_knee: 'Genou D',
  trunk_inclination: 'Tronc',
};

function availablePostureAngles(sample) {
  return Object.keys(postureAngleLabels).filter((key) => {
    const value = sample.angles?.[key];
    return value != null && Number.isFinite(Number(value));
  });
}

function renderPostureCandidates() {
  postureCandidateList.replaceChildren();
  if (!state.postureSamples.length) {
    postureCandidateSummary.textContent = 'Aucune image analysée à afficher.';
    return;
  }
  const samples = [...state.postureSamples].sort((first, second) => Number(first.time_s) - Number(second.time_s));
  const usableCount = samples.filter((sample) => Number.isFinite(Number(sample.time_s))
    && availablePostureAngles(sample).length > 0).length;
  postureCandidateSummary.textContent = `${samples.length} image(s) analysée(s), dont ${usableCount} avec au moins un angle exploitable. Les angles manquants sont indiqués pour chaque image ; ils ne sont pas inventés.`;
  for (const sample of samples) {
    const available = availablePostureAngles(sample);
    const missing = Object.keys(postureAngleLabels).filter((key) => !available.includes(key));
    const item = document.createElement('div');
    item.className = 'posture-candidate-item';
    item.setAttribute('role', 'listitem');
    const candidate = document.createElement('button');
    candidate.type = 'button';
    candidate.className = `posture-candidate${state.selectedPostureSample === sample ? ' selected' : ''}`;
    candidate.setAttribute('aria-pressed', String(state.selectedPostureSample === sample));
    candidate.disabled = !Number.isFinite(Number(sample.time_s)) || available.length === 0;
    const heading = document.createElement('strong');
    heading.textContent = `${Number.isFinite(Number(sample.time_s)) ? `${Number(sample.time_s).toFixed(1)} s` : 'Instant indisponible'} · ${available.length}/${Object.keys(postureAngleLabels).length} angles`;
    const values = document.createElement('span');
    values.textContent = available.length
      ? `Détectés : ${available.map((key) => `${postureAngleLabels[key]} ${Number(sample.angles[key]).toFixed(1)}°`).join(' · ')}`
      : 'Aucun angle exploitable sur cette image.';
    const missingValues = document.createElement('span');
    missingValues.className = 'posture-candidate-missing';
    missingValues.textContent = missing.length
      ? `Non visibles / indisponibles : ${missing.map((key) => postureAngleLabels[key]).join(', ')}`
      : 'Tous les angles suivis sont disponibles.';
    candidate.append(heading, values, missingValues);
    candidate.addEventListener('click', () => selectPostureCandidate(sample));
    item.appendChild(candidate);
    postureCandidateList.appendChild(item);
  }
}

function updateAssessmentAngleHint(timeSeconds, preferredSample = null) {
  const availableSamples = state.postureSamples.filter((sample) => availablePostureAngles(sample).length > 0
    && Number.isFinite(Number(sample.time_s)));
  const sample = preferredSample || availableSamples.reduce((nearest, candidate) =>
    !nearest || Math.abs(Number(candidate.time_s) - timeSeconds) < Math.abs(Number(nearest.time_s) - timeSeconds)
      ? candidate
      : nearest,
  null);
  if (!sample) {
    assessmentAngleHint.textContent = 'Aucune image avec des angles exploitables ; relancez le suivi et vérifiez le cadrage.';
    return;
  }
  const delta = Math.abs(Number(sample.time_s) - timeSeconds);
  const available = availablePostureAngles(sample);
  const missing = Object.keys(postureAngleLabels).filter((key) => !available.includes(key));
  const readings = Object.keys(postureAngleLabels).map((key) => {
    const value = sample.angles?.[key];
    return `${postureAngleLabels[key]} ${value == null || !Number.isFinite(Number(value)) ? 'non visible' : `${Number(value).toFixed(1)}°`}`;
  });
  assessmentAngleHint.textContent = `Image sélectionnée à ${Number(sample.time_s).toFixed(1)} s (${delta.toFixed(1)} s de l’instant demandé) — ${readings.join(' · ')}. ${missing.length} angle(s) manquant(s) : ils élargiront les fourchettes de pré-cotation.`;
}

function selectPostureCandidate(sample) {
  if (!availablePostureAngles(sample).length || !Number.isFinite(Number(sample.time_s))) return;
  state.selectedPostureSample = sample;
  const time = Number(sample.time_s);
  assessmentTimeInput.value = time.toFixed(1);
  if (video.readyState >= 1 && Math.abs(video.currentTime - time) > 0.01) video.currentTime = time;
  renderPostureCandidates();
  updateAssessmentAngleHint(time, sample);
  drawPostureOverlay();
}

const ergonomicFactorLabels = {
  charge_kg: 'Charge (kg)',
  type_effort: 'Type d’effort',
  prise: 'Qualité de prise',
  torsion_tronc: 'Torsion du tronc',
  inclinaison_laterale_tronc: 'Inclinaison latérale du tronc',
  torsion_cou: 'Torsion du cou',
  inclinaison_laterale_cou: 'Inclinaison latérale du cou',
  epaule_surelevee: 'Épaule surélevée',
  abduction_bras: 'Abduction du bras',
  bras_soutenu: 'Bras soutenu',
  avant_bras_croise_ligne_mediane: 'Avant-bras croisé / sur le côté',
  deviation_poignet: 'Déviation du poignet',
  rotation_poignet: 'Rotation du poignet',
  appui_jambes: 'Appui des jambes',
  frequence_geste_par_min: 'Fréquence des gestes/min',
  posture_statique_sup_1min: 'Posture statique > 1 min',
};

function readErgonomicFactors(formData) {
  const factors = {};
  for (const [key, value] of Object.entries(ergonomicFactorLabels)) {
    const raw = String(formData.get(key) ?? '').trim();
    if (!raw) {
      factors[key] = null;
    } else if (key === 'charge_kg' || key === 'frequence_geste_par_min') {
      factors[key] = Number(raw);
    } else if (raw === 'true' || raw === 'false') {
      factors[key] = raw === 'true';
    } else {
      factors[key] = raw;
    }
  }
  return factors;
}

function appendScoringText(container, label, value) {
  const line = document.createElement('p');
  line.textContent = `${label} : ${value}`;
  container.appendChild(line);
}

function renderScoringResult(result) {
  scoringResult.replaceChildren();
  scoringResult.classList.add('has-result');
  scoringResult.classList.remove('has-error');
  const heading = document.createElement('h4');
  heading.textContent = `Pré-cotation à ${Number(result.instant_s).toFixed(1)} s · fiabilité ${result.fiabilite}`;
  scoringResult.appendChild(heading);

  const scoreGrid = document.createElement('div');
  scoreGrid.className = 'scoring-summary-grid';
  for (const method of ['rula', 'reba']) {
    const card = document.createElement('section');
    card.className = 'scoring-summary-card';
    const title = document.createElement('h5');
    title.textContent = method.toUpperCase();
    card.appendChild(title);
    appendScoringText(card, 'Scores min / probable / max',
      `${result[method].score_min} / ${result[method].score_probable} / ${result[method].score_max}`);
    appendScoringText(card, 'Côté retenu', `${result[method].cote_retenu} · ${result[method].niveau}`);
    for (const side of result[method].cotes) {
      appendScoringText(card, `Détail ${side.cote} (min/probable/max ${side.score_min}/${side.score_probable}/${side.score_max})`,
        Object.entries(side.detail).map(([key, value]) => `${key.replaceAll('_', ' ')} ${value}`).join(' · '));
      for (const tableReading of side.lectures_tables) {
        appendScoringText(card, 'Lecture de table', tableReading);
      }
    }
    scoreGrid.appendChild(card);
  }
  scoringResult.appendChild(scoreGrid);

  const conversions = document.createElement('p');
  conversions.textContent = `Conversions MediaPipe : ${Object.entries(result.angles_convertis)
    .filter(([key]) => !key.startsWith('interpretation_'))
    .map(([key, value]) => `${key.replaceAll('_', ' ')} ${value == null ? 'n/d' : `${value}°`}`).join(' · ')}`;
  scoringResult.appendChild(conversions);
  appendScoringText(
    scoringResult,
    'Interprétation caméra',
    `${result.angles_convertis.interpretation_epaule} ; ${result.angles_convertis.interpretation_tronc}`,
  );

  if (result.serie_temporelle) {
    const series = result.serie_temporelle;
    const temporal = document.createElement('div');
    temporal.className = 'scoring-temporal-summary';
    temporal.textContent = series.posture_plus_defavorable
      ? `Série : posture la plus défavorable à ${Number(series.posture_plus_defavorable.instant_s).toFixed(1)} s (RULA ${series.posture_plus_defavorable.rula}, REBA ${series.posture_plus_defavorable.reba}) ; posture la plus fréquente à ${Number(series.posture_plus_frequente.instant_s).toFixed(1)} s (${series.posture_plus_frequente.occurrences} occurrence(s)) ; fréquence estimée ${series.frequence_estimee_gestes_min} geste(s)/min ; statisme > 60 s : ${series.posture_statique_sup_60s ? 'oui' : 'non'} ; ${series.images_occultees_ecartees} image(s) occultée(s) et ${series.images_saut_aberrant_ecartees} image(s) aberrante(s) écartée(s).`
      : 'Série temporelle : aucune image exploitable après filtrage des occultations et sauts aberrants.';
    scoringResult.appendChild(temporal);
  }

  const hypotheses = document.createElement('details');
  const hypothesesTitle = document.createElement('summary');
  hypothesesTitle.textContent = `Hypothèses et données manquantes (${result.hypotheses.length})`;
  hypotheses.appendChild(hypothesesTitle);
  const list = document.createElement('ul');
  for (const hypothesis of result.hypotheses) {
    const item = document.createElement('li');
    item.textContent = hypothesis;
    list.appendChild(item);
  }
  if (!result.hypotheses.length) {
    const item = document.createElement('li');
    item.textContent = 'Aucune hypothèse automatique ; la posture et les facteurs doivent tout de même être validés.';
    list.appendChild(item);
  }
  hypotheses.appendChild(list);
  scoringResult.appendChild(hypotheses);

  if (result.questions_evaluateur?.length) {
    const questions = document.createElement('details');
    const questionTitle = document.createElement('summary');
    questionTitle.textContent = 'Questions à confirmer avec l’évaluateur';
    questions.appendChild(questionTitle);
    const questionList = document.createElement('ul');
    for (const question of result.questions_evaluateur) {
      const item = document.createElement('li');
      item.textContent = question;
      questionList.appendChild(item);
    }
    questions.appendChild(questionList);
    scoringResult.appendChild(questions);
  }

  const warning = document.createElement('strong');
  warning.textContent = result.avertissement;
  scoringResult.appendChild(warning);
}

function showScoringFeedback(message, isError = false) {
  scoringResult.textContent = message;
  scoringResult.classList.remove('has-result');
  scoringResult.classList.toggle('has-error', isError);
}

async function prefillErgonomicAssessment() {
  const formData = new FormData(assessmentForm);
  const rawTime = String(formData.get('time_s') ?? '').trim();
  const time = Number(rawTime);
  if (!rawTime || !Number.isFinite(time) || time < 0) {
    showScoringFeedback('Choisissez d’abord un instant vidéo avec « Utiliser l’instant vidéo courant » ou saisissez un temps en secondes.', true);
    assessmentTimeInput.focus();
    return;
  }
  if (!state.selectedPostureSample) {
    showScoringFeedback('Choisissez une image de posture dans la liste avant de lancer la pré-cotation. Les images partielles restent utilisables.', true);
    return;
  }
  const sample = state.selectedPostureSample;
  if (Math.abs(Number(sample.time_s) - time) > 0.051) {
    showScoringFeedback('L’instant a changé depuis la sélection. Choisissez à nouveau l’image à coter dans la liste.', true);
    return;
  }
  if (!availablePostureAngles(sample).length) {
    showScoringFeedback('Cette image ne contient aucun angle exploitable. Choisissez une autre image dans la liste.', true);
    return;
  }
  prefillAssessmentButton.disabled = true;
  showScoringFeedback('Calcul local des grilles RULA et REBA…');
  try {
    const result = await apiRequest('/api/ergonomics/score', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        instant_s: Number(sample.time_s),
        view_camera: cameraView.value,
        angles: sample.angles || {},
        evaluator_factors: readErgonomicFactors(formData),
        series: state.postureSamples,
      }),
    });
    renderScoringResult(result);
    assessmentForm.elements.rula_score.value = String(result.rula.score_probable);
    assessmentForm.elements.reba_score.value = String(result.reba.score_probable);
    assessmentForm.elements.factors_notes.value = [
      `Pré-cotation à valider par l’évaluateur — vue caméra : ${cameraView.options[cameraView.selectedIndex].text}.`,
      `RULA ${result.rula.score_min}/${result.rula.score_probable}/${result.rula.score_max} (${result.rula.cote_retenu}, ${result.rula.niveau}) ; REBA ${result.reba.score_min}/${result.reba.score_probable}/${result.reba.score_max} (${result.reba.cote_retenu}, ${result.reba.niveau}) ; fiabilité ${result.fiabilite}.`,
      `Conversions des angles : ${Object.entries(result.angles_convertis).map(([key, value]) => `${key} ${value == null ? 'n/d' : `${value}°`}`).join(' ; ')}.`,
      `Facteurs évaluateur : ${Object.entries(readErgonomicFactors(formData)).map(([key, value]) => `${ergonomicFactorLabels[key]} ${value == null ? 'non renseigné' : value}`).join(' ; ')}.`,
      result.hypotheses.length ? `Hypothèses : ${result.hypotheses.join(' ')}` : '',
      result.serie_temporelle
        ? `Série temporelle : ${result.serie_temporelle.nombre_images_valides} images valides ; posture la plus défavorable ${result.serie_temporelle.posture_plus_defavorable ? `${Number(result.serie_temporelle.posture_plus_defavorable.instant_s).toFixed(1)} s` : 'n/d'} ; répétitivité > 4/min ${result.serie_temporelle.repetitivite_superieure_4_min ? 'oui' : 'non'} ; statisme > 60 s ${result.serie_temporelle.posture_statique_sup_60s ? 'oui' : 'non'} ; images écartées ${result.serie_temporelle.images_occultees_ecartees + result.serie_temporelle.images_saut_aberrant_ecartees}.`
        : '',
      result.avertissement,
    ].filter(Boolean).join('\n').slice(0, 4000);
    assessmentForm.elements.official_method_confirmed.checked = false;
    assessmentTimeInput.value = Number(result.instant_s).toFixed(1);
    scheduleConfigurationSave('ergonomics');
    assessmentMessage.textContent = 'Scores pré-remplis et modifiables. La case de validation est restée décochée.';
    assessmentMessage.className = 'form-message';
  } catch (error) {
    showScoringFeedback(`Pré-cotation impossible : ${error.message}`, true);
  } finally {
    prefillAssessmentButton.disabled = false;
  }
}

function renderErgonomicAssessments() {
  assessmentHistory.replaceChildren();
  if (!state.ergonomicAssessments.length) {
    const empty = document.createElement('p');
    empty.className = 'subtle';
    empty.textContent = 'Aucune cotation enregistrée pour ce poste.';
    assessmentHistory.appendChild(empty);
    return;
  }
  for (const assessment of state.ergonomicAssessments) {
    const entry = document.createElement('article');
    entry.className = 'assessment-entry';
    const details = document.createElement('div');
    const scores = [];
    if (assessment.rula_score != null) scores.push(`RULA ${assessment.rula_score} — ${assessment.rula_level || ''}`);
    if (assessment.reba_score != null) scores.push(`REBA ${assessment.reba_score} — ${assessment.reba_level || ''}`);
    const heading = document.createElement('strong');
    heading.textContent = `${Number(assessment.time_s).toFixed(1)} s · ${scores.join(' · ')}`;
    const notes = document.createElement('p');
    notes.textContent = `${assessment.evaluator} · ${assessment.factors_notes}`;
    details.append(heading, notes);
    entry.appendChild(details);
    assessmentHistory.appendChild(entry);
  }
}

async function saveErgonomicAssessment(event) {
  event.preventDefault();
  const formData = new FormData(assessmentForm);
  const rulaValue = String(formData.get('rula_score') || '');
  const rebaValue = String(formData.get('reba_score') || '');
  if (!rulaValue && !rebaValue) {
    assessmentMessage.textContent = 'Saisissez au moins un score RULA ou REBA.';
    assessmentMessage.className = 'form-message error';
    return;
  }
  const submit = assessmentForm.querySelector('button[type="submit"]');
  submit.disabled = true;
  assessmentMessage.textContent = 'Enregistrement local de la cotation…';
  assessmentMessage.className = 'form-message';
  try {
    const assessment = await apiRequest(`/api/stations/${stationId}/ergonomic-assessments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        time_s: Number(formData.get('time_s')),
        rula_score: rulaValue ? Number(rulaValue) : null,
        reba_score: rebaValue ? Number(rebaValue) : null,
        evaluator: String(formData.get('evaluator')).trim(),
        factors_notes: String(formData.get('factors_notes')).trim(),
        official_method_confirmed: formData.get('official_method_confirmed') === 'on',
      }),
    });
    state.ergonomicAssessments.push(assessment);
    state.ergonomicAssessments.sort((first, second) => first.time_s - second.time_s || first.id - second.id);
    renderErgonomicAssessments();
    assessmentForm.elements.rula_score.value = '';
    assessmentForm.elements.reba_score.value = '';
    assessmentForm.elements.factors_notes.value = '';
    assessmentForm.elements.official_method_confirmed.checked = false;
    scheduleConfigurationSave('ergonomics');
    assessmentMessage.textContent = 'Cotation enregistrée localement. Elle reste à interpréter par un professionnel compétent.';
    assessmentMessage.className = 'form-message success';
  } catch (error) {
    assessmentMessage.textContent = error.message;
    assessmentMessage.className = 'form-message error';
  } finally {
    submit.disabled = false;
  }
}

async function startPostureAnalysis() {
  if (state.busy || !state.station) return;
  constrainAnalysisWindowToVideo();
  const start = Number(document.getElementById('windowStart').value || 0);
  const end = Number(document.getElementById('windowEnd').value || state.station.video_duration_s);
  if (!Number.isFinite(end) || end <= start) {
    postureStatus.textContent = 'La fin de fenêtre doit être supérieure au début.';
    postureStatus.className = 'form-message error';
    return;
  }
  state.postureSamples = [];
  state.selectedPostureSample = null;
  renderPostureCandidates();
  state.busy = true;
  analyzePostureButton.disabled = true;
  postureProgress.value = 0;
  postureStatus.textContent = 'Démarrage du suivi local des postures…';
  postureStatus.className = 'form-message';
  try {
    const submitted = await apiRequest(`/api/stations/${stationId}/posture-analysis`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fenetre_debut: start, fenetre_fin: end, fps: 2 }),
    });
    let result;
    do {
      await new Promise((resolve) => window.setTimeout(resolve, 400));
      result = await apiRequest(submitted.poll_url);
      postureProgress.value = result.progress || 0;
      postureStatus.textContent = result.status === 'running'
        ? `Suivi local en cours… ${result.progress || 0} %`
        : result.status === 'queued'
          ? 'Suivi en attente…'
          : 'Enregistrement des repères…';
    } while (result.status === 'queued' || result.status === 'running');
    if (result.status !== 'completed') throw new Error(result.error || 'Le suivi de posture a échoué.');
    state.postureSamples = result.posture_samples || [];
    state.selectedPostureSample = null;
    renderPostureCandidates();
    postureProgress.value = 100;
    postureStatus.textContent = `${result.sample_count} images échantillonnées. Repères 2D uniquement ; vérifier chaque posture dans la vidéo.`;
    drawPostureOverlay();
  } catch (error) {
    postureStatus.textContent = error.message;
    postureStatus.className = 'form-message error';
  } finally {
    state.busy = false;
    analyzePostureButton.disabled = false;
  }
}

function renderTimeline() {
  if (!state.phases.some((phase) => phase.id === state.selectedPhaseId)) {
    state.selectedPhaseId = null;
    state.playbackEnd = null;
  }
  if (!state.station || !state.phases.length) {
    timeline.replaceChildren();
    const empty = document.createElement('div');
    empty.className = 'timeline-segment';
    empty.style.width = '100%';
    empty.textContent = 'Aucune phase analysée';
    timeline.appendChild(empty);
    phaseCount.textContent = '0 phase';
    selectedInterval.textContent = 'Aucune phase à sélectionner.';
    return;
  }

  const firstStart = Math.min(...state.phases.map((phase) => Number(phase.debut_s)));
  const maxEnd = Math.max(...state.phases.map((phase) => Number(phase.fin_s))) || 1;
  const totalDuration = Math.max(maxEnd - firstStart, 1);
  const minimumSegmentWidth = 94;
  const contentWidth = Math.max(timeline.clientWidth, state.phases.length * minimumSegmentWidth);
  const scale = contentWidth / totalDuration;
  timeline.replaceChildren();
  for (const phase of state.phases) {
    const start = Number(phase.debut_s);
    const end = Number(phase.fin_s);
    const item = document.createElement('button');
    item.type = 'button';
    item.className = `timeline-segment ${phase.type_auto === 'activity' ? 'activity' : 'stop'}${phase.id === state.selectedPhaseId ? ' selected' : ''}`;
    item.dataset.phaseId = phase.id;
    item.style.flexBasis = `${Math.max((end - start) * scale, minimumSegmentWidth)}px`;
    item.setAttribute('aria-pressed', String(phase.id === state.selectedPhaseId));
    item.title = `${phaseDisplayLabel(phase)} • ${formatSeconds(start)} → ${formatSeconds(end)}`;
    const label = document.createElement('span');
    label.textContent = phaseDisplayLabel(phase);
    const timeLabel = document.createElement('small');
    timeLabel.textContent = `${formatSeconds(start)}–${formatSeconds(end)}`;
    item.append(label, timeLabel);
    item.addEventListener('click', () => selectPhase(phase));
    timeline.appendChild(item);
  }
  phaseCount.textContent = `${state.phases.length} phase${state.phases.length === 1 ? '' : 's'}`;
  const selected = state.phases.find((phase) => phase.id === state.selectedPhaseId);
  if (selected) {
    const start = Number(selected.debut_s);
    const end = Number(selected.fin_s);
    selectedInterval.textContent =
      `${phaseDisplayLabel(selected)} · ${formatSeconds(start)} → ${formatSeconds(end)} · intervalle ${formatSeconds(end - start)}`;
  } else {
    selectedInterval.textContent = 'Clique sur une phase pour afficher son intervalle et lire uniquement cette zone.';
  }
}

function renderMotionChart() {
  const displayWidth = Math.max(motionChart.clientWidth, 320);
  const chartHeight = 180;
  const labelHeight = 30;
  const height = chartHeight + labelHeight;
  const pixelRatio = window.devicePixelRatio || 1;
  motionChart.width = Math.round(displayWidth * pixelRatio);
  motionChart.height = Math.round(height * pixelRatio);
  const ctx = motionChart.getContext('2d');
  ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  ctx.clearRect(0, 0, displayWidth, height);
  ctx.strokeStyle = '#d8e1ed';
  ctx.lineWidth = 1;
  for (let index = 0; index <= 4; index += 1) {
    const y = (chartHeight / 4) * index;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(displayWidth, y);
    ctx.stroke();
  }
  if (!state.motionSamples.length) return;

  const firstTime = Number(state.motionSamples[0].time_s);
  const lastTime = Number(state.motionSamples[state.motionSamples.length - 1].time_s);
  const xForTime = (time) => ((time - firstTime) / (lastTime - firstTime || 1)) * displayWidth;
  const selected = state.phases.find((phase) => phase.id === state.selectedPhaseId);
  if (selected) {
    const x1 = Math.max(0, xForTime(Number(selected.debut_s)));
    const x2 = Math.min(displayWidth, xForTime(Number(selected.fin_s)));
    if (x2 > x1) {
      ctx.fillStyle = 'rgba(46, 139, 87, 0.14)';
      ctx.fillRect(x1, 0, x2 - x1, chartHeight);
      ctx.strokeStyle = '#174d7c';
      ctx.lineWidth = 2;
      ctx.strokeRect(x1, 1, x2 - x1, chartHeight - 2);
    }
  }
  const chartMax = Math.max(
    ...state.motionSamples.map((sample) => Number(sample.motion_pct)),
    state.threshold || state.detectedThreshold,
    1,
  ) * 1.1;
  ctx.beginPath();
  state.motionSamples.forEach((sample, index) => {
    const x = xForTime(Number(sample.time_s));
    const y = chartHeight - (Number(sample.motion_pct) / chartMax) * chartHeight;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = '#1f4e79';
  ctx.lineWidth = 2;
  ctx.stroke();

  const threshold = state.threshold || state.detectedThreshold;
  if (threshold > 0) {
    const thresholdY = chartHeight - (threshold / chartMax) * chartHeight;
    ctx.beginPath();
    ctx.setLineDash([6, 6]);
    ctx.moveTo(0, thresholdY);
    ctx.lineTo(displayWidth, thresholdY);
    ctx.strokeStyle = '#d16838';
    ctx.stroke();
    ctx.setLineDash([]);
  }

  const labelY = chartHeight + 20;
  ctx.fillStyle = '#5d6470';
  ctx.font = '11px Segoe UI, Arial, sans-serif';
  ctx.textAlign = 'left';
  for (let index = 0; index <= 4; index += 1) {
    const time = firstTime + ((lastTime - firstTime) * index) / 4;
    const x = (displayWidth * index) / 4;
    ctx.fillText(formatSeconds(time), Math.min(x, displayWidth - 62), labelY);
  }
  if (selected) {
    const startX = xForTime(Number(selected.debut_s));
    const endX = xForTime(Number(selected.fin_s));
    ctx.strokeStyle = '#174d7c';
    ctx.lineWidth = 2;
    for (const x of [startX, endX]) {
      if (x < 0 || x > displayWidth) continue;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, chartHeight);
      ctx.stroke();
    }
  }
  if (state.selectedPhaseId != null && video.currentTime >= firstTime && video.currentTime <= lastTime) {
    const playheadX = xForTime(video.currentTime);
    ctx.strokeStyle = '#bc3a2b';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(playheadX, 0);
    ctx.lineTo(playheadX, chartHeight);
    ctx.stroke();
  }
}

function addField(container, labelText, value, type, onSave, options = {}) {
  const label = document.createElement('label');
  label.textContent = labelText;
  const input = document.createElement(type === 'select' ? 'select' : type === 'textarea' ? 'textarea' : 'input');
  if (type !== 'select' && type !== 'textarea') {
    input.type = type;
    if (type === 'number') input.step = options.step || '0.1';
    if (options.list) input.setAttribute('list', options.list);
    if (options.placeholder) input.placeholder = options.placeholder;
  }
  if (type === 'select') {
    const values = options.values || categoryOptions.map((value) => ({ value, label: value }));
    for (const item of values) {
      const option = document.createElement('option');
      option.value = item.value;
      option.textContent = item.label;
      option.selected = item.value === value;
      input.appendChild(option);
    }
  } else {
    input.value = value ?? '';
  }
  input.addEventListener('change', () => onSave(input.value));
  input.addEventListener('click', (event) => event.stopPropagation());
  label.appendChild(input);
  container.appendChild(label);
}

async function updatePhase(phaseId, patch) {
  try {
    const updated = await apiRequest(`/api/stations/${stationId}/phases/${phaseId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    state.phases = state.phases.map((phase) => (phase.id === phaseId ? updated : phase));
    await refreshAnnotationData();
    refreshDisplay();
    configurationSaveStatus.textContent = 'Les réglages de chaque onglet sont enregistrés localement pour ce poste.';
    configurationSaveStatus.className = 'configuration-save-status subtle';
    showAnalysisStatus('Modifications de phase enregistrées.');
  } catch (error) {
    showAnalysisStatus(error.message, true);
    await loadStation();
  }
}

function renderPhaseList() {
  const previousScrollTop = phaseList.scrollTop;
  const query = normalizePhaseSearch(phaseSearch.value.trim());
  const phaseNumberQuery = query.match(/^(?:(?:phase|activite)\s*#?\s*(\d+)|#?(\d+)(?:\s*(?:phase|activite))?)$/);
  const typeFilter = phaseTypeFilter.value;
  const categoryFilter = phaseCategoryFilter.value;
  const matchingPhases = state.phases.filter((phase) => {
    if (typeFilter && phase.type_auto !== typeFilter) return false;
    if (categoryFilter && (phase.categorie || 'Non classé') !== categoryFilter) return false;
    if (!query) return true;
    if (phaseNumberQuery) {
      const requestedNumber = Number(phaseNumberQuery[1] || phaseNumberQuery[2]);
      return Number(phase.ordre) === requestedNumber;
    }
    const searchableText = normalizePhaseSearch([
      `phase ${phase.ordre}`,
      phaseLabel(phase),
      phase.description,
      phase.categorie || 'Non classé',
      phase.commentaire,
      phase.debut_s,
      phase.fin_s,
    ].join(' '));
    return searchableText.includes(query);
  });
  phaseFilterCount.textContent = matchingPhases.length === state.phases.length
    ? `${state.phases.length} étape${state.phases.length === 1 ? '' : 's'}`
    : `${matchingPhases.length} / ${state.phases.length} étapes`;
  phaseList.replaceChildren();
  if (!state.phases.length) {
    const empty = document.createElement('div');
    empty.className = 'phase-item';
    empty.textContent = 'Aucune phase détectée. Lance l’analyse du mouvement.';
    phaseList.appendChild(empty);
    return;
  }

  if (!matchingPhases.length) {
    const empty = document.createElement('div');
    empty.className = 'phase-filter-empty subtle';
    empty.textContent = 'Aucune étape ne correspond aux filtres.';
    phaseList.appendChild(empty);
    phaseList.scrollTop = previousScrollTop;
    return;
  }

  for (const phase of matchingPhases) {
    const item = document.createElement('article');
    item.className = `phase-item ${phase.type_auto === 'stop' ? 'stop' : ''}${phase.id === state.selectedPhaseId ? ' selected-phase' : ''}`;
    item.dataset.phaseId = phase.id;
    if (phase.id === state.selectedPhaseId) item.setAttribute('aria-current', 'true');

    const header = document.createElement('div');
    header.className = 'phase-item-header';
    const title = document.createElement('strong');
    title.textContent = phaseDisplayLabel(phase);
    const category = document.createElement('span');
    category.className = 'phase-category';
    category.textContent = phase.categorie || 'Non classé';
    header.append(title, category);
    const normalizedDescription = (phase.description || '').trim().toLocaleLowerCase('fr');
    const sharedOperation = state.operations.find(
      (operation) => operation.nom.trim().toLocaleLowerCase('fr') === normalizedDescription,
    );
    if (sharedOperation && sharedOperation.occurrences > 1) {
      const sharedBadge = document.createElement('span');
      sharedBadge.className = 'operation-shared';
      sharedBadge.textContent = `Opération partagée · ${sharedOperation.occurrences} phases`;
      header.appendChild(sharedBadge);
    }

    const meta = document.createElement('div');
    meta.className = 'phase-meta';
    const times = document.createElement('span');
    times.textContent = `${formatSeconds(phase.debut_s)} → ${formatSeconds(phase.fin_s)} · ${formatSeconds(Number(phase.fin_s) - Number(phase.debut_s))}`;
    const movement = document.createElement('span');
    movement.textContent = `mouvement moyen ${Number(phase.mouvement_moyen_pct || 0).toFixed(2)} %`;
    meta.append(times, movement);

    const fields = document.createElement('div');
    fields.className = 'phase-fields';
    addField(fields, 'Début (s)', Number(phase.debut_s).toFixed(1), 'number', (value) => updatePhase(phase.id, { debut_s: Number(value) }));
    addField(fields, 'Fin (s)', Number(phase.fin_s).toFixed(1), 'number', (value) => updatePhase(phase.id, { fin_s: Number(value) }));
    addField(
      fields,
      'Type de phase',
      phase.type_auto,
      'select',
      (value) => updatePhase(phase.id, { type_auto: value }),
      { values: [{ value: 'activity', label: 'Activité' }, { value: 'stop', label: 'Arrêt' }] },
    );
    addField(
      fields,
      'Opération observée',
      phase.description,
      'text',
      (value) => updatePhase(phase.id, { description: value }),
      {
        list: 'operationSuggestions',
        placeholder: 'Ex. prendre une pièce, visser, contrôler…',
      },
    );
    addField(fields, 'Catégorie', phase.categorie || 'Non classé', 'select', (value) => updatePhase(phase.id, { categorie: value }));
    addField(fields, 'Chrono réel (s)', phase.chrono_reel_s ?? '', 'number', (value) => updatePhase(phase.id, { chrono_reel_s: value === '' ? null : Number(value) }));
    addField(fields, 'Commentaire', phase.commentaire, 'textarea', (value) => updatePhase(phase.id, { commentaire: value }));

    const selectLabel = document.createElement('label');
    selectLabel.className = 'phase-meta';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'phase-select';
    checkbox.checked = selectedPhases.has(phase.id);
    checkbox.setAttribute('aria-label', `Sélectionner la phase ${phase.ordre} pour fusion`);
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) selectedPhases.add(phase.id);
      else selectedPhases.delete(phase.id);
    });
    selectLabel.append(checkbox, 'Sélectionner pour fusion');
    item.addEventListener('click', (event) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement) return;
      selectPhase(phase);
    });
    item.append(header, meta, fields, selectLabel);
    phaseList.appendChild(item);
  }
  phaseList.scrollTop = previousScrollTop;
}

async function loadOperationCatalog() {
  if (!state.station?.project_id) return;
  const operations = await apiRequest(`/api/projects/${state.station.project_id}/operations`);
  state.operations = operations;
  operationSuggestions.replaceChildren();
  operationCatalog.replaceChildren();
  annotationOperation.replaceChildren();
  const uncertainOption = document.createElement('option');
  uncertainOption.value = '';
  uncertainOption.textContent = 'Autre / incertain';
  annotationOperation.appendChild(uncertainOption);
  if (!operations.length) {
    const empty = document.createElement('p');
    empty.className = 'subtle';
    empty.textContent = 'Aucune opération définie. Ajoutez les classes connues du projet ci-dessus.';
    operationCatalog.appendChild(empty);
    return;
  }

  for (const operation of operations) {
    const option = document.createElement('option');
    option.value = operation.nom;
    operationSuggestions.appendChild(option);

    const selectOption = document.createElement('option');
    selectOption.value = String(operation.id);
    selectOption.textContent = operation.nom;
    annotationOperation.appendChild(selectOption);

    const chip = document.createElement('div');
    chip.className = 'operation-chip';
    const name = document.createElement('span');
    name.textContent = operation.nom;
    const count = document.createElement('span');
    count.className = 'operation-chip-count';
    count.textContent = `${operation.occurrences || 0} phase(s) · ${operation.annotations || 0} annotation(s)`;
    const rename = document.createElement('button');
    rename.type = 'button';
    rename.className = 'secondary';
    rename.textContent = 'Renommer';
    rename.addEventListener('click', () => {
      const input = document.createElement('input');
      input.value = operation.nom;
      input.maxLength = 200;
      input.setAttribute('aria-label', `Nouveau nom pour ${operation.nom}`);
      const save = document.createElement('button');
      save.type = 'button';
      save.textContent = 'Enregistrer';
      save.addEventListener('click', async () => {
        try {
          await apiRequest(`/api/projects/${state.station.project_id}/operations/${operation.id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nom: input.value.trim() }),
          });
          await refreshAnnotationData();
          showOperationStatus('Opération renommée.');
        } catch (error) {
          showOperationStatus(error.message, true);
        }
      });
      assessmentForm.addEventListener('input', () => scheduleConfigurationSave('ergonomics'));
      assessmentForm.addEventListener('change', () => scheduleConfigurationSave('ergonomics'));
      const cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'secondary';
      cancel.textContent = 'Annuler';
      cancel.addEventListener('click', () => { refreshAnnotationData().catch((error) => showOperationStatus(error.message, true)); });
      chip.replaceChildren(input, count, save, cancel);
      input.focus();
      input.select();
    });
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'secondary';
    remove.textContent = 'Supprimer';
    remove.addEventListener('click', async () => {
      if (!window.confirm(`Supprimer l’opération « ${operation.nom} » du référentiel ?`)) return;
      try {
        await apiRequest(`/api/projects/${state.station.project_id}/operations/${operation.id}`, { method: 'DELETE' });
        await refreshAnnotationData();
        showOperationStatus('Opération supprimée.');
      } catch (error) {
        showOperationStatus(error.message, true);
      }
    });
    chip.append(name, count, rename, remove);
    operationCatalog.appendChild(chip);
  }
}

function showOperationStatus(message, isError = false) {
  operationStatus.textContent = message;
  operationStatus.className = `form-message${isError ? ' error' : ' success'}`;
}

function showAnnotationStatus(message, isError = false) {
  annotationStatus.textContent = message;
  annotationStatus.className = `form-message${isError ? ' error' : ' success'}`;
}

function showDatasetSummary(dataset) {
  const splits = dataset.splits || {};
  const splitLabels = [
    ['train', 'entraînement'],
    ['validation', 'validation'],
    ['excluded', 'exclue'],
  ];
  const summary = splitLabels.map(([key, label]) => {
    const item = splits[key] || { videos: 0, annotations: 0 };
    return `${item.videos} vidéo(s) ${label}, ${item.annotations} annotation(s)`;
  }).join(' · ');
  const operations = (dataset.operations || []).map((item) =>
    `${item.nom} : ${item.annotations || 0} annotation(s) (train ${item.train || 0}, validation ${item.validation || 0})`,
  );
  annotationDatasetSummary.textContent = [
    `Jeu du projet — ${summary}.`,
    dataset.message,
    ...operations,
  ].filter(Boolean).join(' ');
}

function showOperationModelStatus(model) {
  state.operationModel = model;
  operationModelStatus.textContent = model.message || 'État du modèle local inconnu.';
  operationModelStatus.className = `form-message${model.model_status === 'trained' ? ' success' : ''}`;
  if (model.model_status === 'stale' || model.model_status === 'invalid') {
    operationModelStatus.classList.add('error');
  }
  suggestOperationsButton.disabled = !(
    model.model_status === 'trained'
    && state.station?.dataset_split === 'excluded'
    && Boolean(state.station?.video_path)
  );

  operationModelResults.replaceChildren();
  if (!model.validation) return;
  const validation = model.validation;
  const accuracy = document.createElement('p');
  accuracy.className = 'operation-model-result';
  accuracy.textContent = `Validation sur ${validation.examples} annotation(s) : ${validation.accuracy_pct} % de prédictions correctes (${validation.correct}/${validation.examples}). Cette mesure dépend du petit jeu disponible et ne garantit pas les résultats futurs.`;
  operationModelResults.appendChild(accuracy);
  for (const item of model.training_counts || []) {
    const count = document.createElement('p');
    count.className = 'operation-model-result';
    count.textContent = `Entraînement · ${item.operation} : ${item.count} annotation(s).`;
    operationModelResults.appendChild(count);
  }
  for (const item of validation.per_operation || []) {
    const score = document.createElement('p');
    score.className = 'operation-model-result';
    score.textContent = `Validation · ${item.operation} : précision ${item.precision_pct} %, rappel ${item.recall_pct} % (${item.validation} exemple(s)).`;
    operationModelResults.appendChild(score);
  }
  for (const item of model.excluded_operations || []) {
    const warning = document.createElement('p');
    warning.className = 'operation-model-result';
    warning.textContent = `${item.operation} ignorée : ${item.count} annotation(s), il en faut au moins 2 dans l'entraînement.`;
    operationModelResults.appendChild(warning);
  }
  for (const item of model.validation_untrained_operations || []) {
    const warning = document.createElement('p');
    warning.className = 'operation-model-result';
    warning.textContent = `${item.operation} non évaluée : cette opération n'a pas assez d'exemples d'entraînement.`;
    operationModelResults.appendChild(warning);
  }
}

function renderModelSuggestions() {
  modelSuggestions.replaceChildren();
  for (const suggestion of state.modelSuggestions) {
    const row = document.createElement('div');
    row.className = 'model-suggestion-row';
    const text = document.createElement('span');
    text.textContent = `${formatSeconds(suggestion.debut_s)} → ${formatSeconds(suggestion.fin_s)} · ${suggestion.operation} · score indicatif ${Math.round(suggestion.confidence * 100)} %`;
    const view = document.createElement('button');
    view.type = 'button';
    view.className = 'secondary';
    view.textContent = 'Vérifier';
    view.addEventListener('click', () => { video.currentTime = Number(suggestion.debut_s); });
    const accept = document.createElement('button');
    accept.type = 'button';
    accept.textContent = 'Accepter';
    accept.addEventListener('click', async () => {
      accept.disabled = true;
      try {
        await apiRequest(`/api/stations/${stationId}/annotations`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            operation_id: suggestion.operation_id,
            debut_s: suggestion.debut_s,
            fin_s: suggestion.fin_s,
          }),
        });
        state.modelSuggestions = state.modelSuggestions.filter((item) => item.phase_id !== suggestion.phase_id);
        renderModelSuggestions();
        await refreshAnnotationData();
        modelSuggestionStatus.textContent = 'Suggestion acceptée et enregistrée comme annotation. Vérifiez-la sur la vidéo.';
        modelSuggestionStatus.className = 'form-message success';
      } catch (error) {
        modelSuggestionStatus.textContent = `Impossible d'accepter la suggestion : ${error.message}`;
        modelSuggestionStatus.className = 'form-message error';
        accept.disabled = false;
      }
    });
    row.append(text, view, accept);
    modelSuggestions.appendChild(row);
  }
}

function renderVideoAnnotations() {
  videoAnnotationList.replaceChildren();
  annotationTimeline.replaceChildren();
  const duration = Number(video.duration || state.station?.video_duration_s || 0);
  if (!state.annotations.length) {
    const empty = document.createElement('p');
    empty.className = 'subtle';
    empty.textContent = 'Aucune annotation pour cette vidéo. Délimitez une occurrence et choisissez une opération, ou « Autre / incertain ».';
    videoAnnotationList.appendChild(empty);
  }
  for (const annotation of state.annotations) {
    const row = document.createElement('div');
    row.className = 'video-annotation-row';
    const label = document.createElement('span');
    label.textContent = `${formatSeconds(annotation.debut_s)} → ${formatSeconds(annotation.fin_s)} · ${annotation.operation}`;
    const seek = document.createElement('button');
    seek.type = 'button';
    seek.className = 'secondary';
    seek.textContent = 'Voir';
    seek.addEventListener('click', () => { video.currentTime = Number(annotation.debut_s); });
    const edit = document.createElement('button');
    edit.type = 'button';
    edit.className = 'secondary';
    edit.textContent = 'Modifier';
    edit.addEventListener('click', () => {
      state.annotationEditId = annotation.id;
      annotationOperation.value = annotation.operation_id == null ? '' : String(annotation.operation_id);
      annotationStart.value = Number(annotation.debut_s).toFixed(1);
      annotationEnd.value = Number(annotation.fin_s).toFixed(1);
      saveAnnotation.textContent = 'Enregistrer la modification';
      cancelAnnotationEdit.hidden = false;
      showAnnotationStatus('Modification d’une annotation existante.');
    });
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'secondary';
    remove.textContent = 'Supprimer';
    remove.addEventListener('click', async () => {
      try {
        await apiRequest(`/api/stations/${stationId}/annotations/${annotation.id}`, { method: 'DELETE' });
        await refreshAnnotationData();
        showAnnotationStatus('Annotation supprimée.');
      } catch (error) {
        showAnnotationStatus(error.message, true);
      }
    });
    row.append(label, seek, edit, remove);
    videoAnnotationList.appendChild(row);

    if (duration > 0) {
      const segment = document.createElement('button');
      segment.type = 'button';
      segment.className = `annotation-segment${annotation.operation_id == null ? ' uncertain' : ''}`;
      segment.style.left = `${Math.max(0, Number(annotation.debut_s) / duration * 100)}%`;
      segment.style.width = `${Math.max(.5, (Number(annotation.fin_s) - Number(annotation.debut_s)) / duration * 100)}%`;
      segment.title = `${annotation.operation} · ${formatSeconds(annotation.debut_s)}–${formatSeconds(annotation.fin_s)}`;
      segment.textContent = annotation.operation;
      segment.addEventListener('click', () => {
        video.currentTime = Number(annotation.debut_s);
      });
      annotationTimeline.appendChild(segment);
    }
  }
}

async function refreshAnnotationData() {
  if (!state.station?.project_id) return;
  const [annotations, dataset] = await Promise.all([
    apiRequest(`/api/stations/${stationId}/annotations`),
    apiRequest(`/api/projects/${state.station.project_id}/annotation-dataset`),
  ]);
  state.annotations = annotations;
  state.annotationDataset = dataset;
  datasetSplit.value = state.station.dataset_split || 'excluded';
  showDatasetSummary(dataset);
  showOperationModelStatus(dataset.model || {
    model_status: dataset.model_status,
    message: dataset.message,
  });
  renderVideoAnnotations();
  await loadOperationCatalog();
}

function showCycleStatus(message, isError = false) {
  cycleStatus.textContent = message;
  cycleStatus.className = `form-message${isError ? ' error' : ''}`;
}

function renderCycleList() {
  cycleList.replaceChildren();
  if (!state.cycles.length) {
    const empty = document.createElement('p');
    empty.className = 'subtle';
    empty.textContent = 'Aucun cycle enregistré.';
    cycleList.appendChild(empty);
    return;
  }
  state.cycles.forEach((cycle, index) => {
    const row = document.createElement('div');
    row.className = 'cycle-row';
    const label = document.createElement('span');
    label.textContent = `Cycle ${index + 1} · ${formatSeconds(cycle.debut_s)} → ${formatSeconds(cycle.fin_s)} · ${formatSeconds(cycle.fin_s - cycle.debut_s)} · ${cycle.source === 'auto' ? 'proposé automatiquement, vérifié' : 'défini manuellement'}`;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'danger';
    remove.textContent = 'Supprimer';
    remove.setAttribute('aria-label', `Supprimer le cycle ${index + 1}`);
    remove.addEventListener('click', async () => {
      remove.disabled = true;
      try {
        await apiRequest(`/api/stations/${stationId}/cycles/${cycle.id}`, { method: 'DELETE' });
        await loadCycles();
        showCycleStatus('Cycle supprimé.');
      } catch (error) {
        showCycleStatus(error.message, true);
        remove.disabled = false;
      }
    });
    row.append(label, remove);
    cycleList.appendChild(row);
  });
}

function renderCycleSuggestions() {
  cycleCandidates.replaceChildren();
  for (const [index, candidate] of state.cycleSuggestions.entries()) {
    const row = document.createElement('div');
    row.className = 'cycle-row';
    const label = document.createElement('span');
    label.textContent = `Proposition ${index + 1} · ${formatSeconds(candidate.debut_s)} → ${formatSeconds(candidate.fin_s)} · ${formatSeconds(candidate.fin_s - candidate.debut_s)}`;
    const add = document.createElement('button');
    add.type = 'button';
    add.textContent = 'Vérifier et ajouter';
    add.addEventListener('click', async () => {
      add.disabled = true;
      try {
        await apiRequest(`/api/stations/${stationId}/cycles`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...candidate, source: 'auto' }),
        });
        state.cycleSuggestions.splice(index, 1);
        renderCycleSuggestions();
        await loadCycles();
        showCycleStatus('Proposition ajoutée. Vérifiez visuellement les limites du cycle.');
      } catch (error) {
        showCycleStatus(error.message, true);
        add.disabled = false;
      }
    });
    row.append(label, add);
    cycleCandidates.appendChild(row);
  }
}

async function loadCycles() {
  state.cycles = await apiRequest(`/api/stations/${stationId}/cycles`);
  renderCycleList();
  if (!state.cycles.length) showCycleStatus('Aucun cycle enregistré. Définissez des limites ou demandez des propositions.');
  else showCycleStatus(`${state.cycles.length} cycle${state.cycles.length === 1 ? '' : 's'} enregistré${state.cycles.length === 1 ? '' : 's'}.`);
}

function refreshDisplay() {
  rangeValues.textContent = `${state.threshold === 0 ? 'Auto' : `${state.threshold.toFixed(1)} %`} · ${state.minLength.toFixed(1)} s`;
  renderTimeline();
  renderMotionChart();
  renderPhaseList();
}

let roiDrawingEnabled = false;
let roiDraft = null;
let roiDragStart = null;

function drawRoi() {
  renderRoiList();
  roiPreview.classList.toggle('drawing', roiDrawingEnabled);
  if (!roiFrame.naturalWidth || !roiFrame.naturalHeight) return;
  roiCanvas.width = roiFrame.naturalWidth;
  roiCanvas.height = roiFrame.naturalHeight;
  const context = roiCanvas.getContext('2d');
  context.clearRect(0, 0, roiCanvas.width, roiCanvas.height);
  const drawRectangle = (rectangle, index, color) => {
    const [x, y, width, height] = rectangle;
    const left = x * roiCanvas.width;
    const top = y * roiCanvas.height;
    context.fillStyle = color === '#f59e0b' ? 'rgba(245, 158, 11, 0.22)' : 'rgba(34, 197, 94, 0.18)';
    context.strokeStyle = color;
    context.lineWidth = Math.max(2, roiCanvas.width / 400);
    context.fillRect(left, top, width * roiCanvas.width, height * roiCanvas.height);
    context.strokeRect(left, top, width * roiCanvas.width, height * roiCanvas.height);
    context.fillStyle = color;
    context.font = `bold ${Math.max(14, roiCanvas.width / 40)}px sans-serif`;
    context.fillText(String(index), left + 4, top + Math.max(16, roiCanvas.width / 35));
  };
  state.rois.forEach((rectangle, index) => drawRectangle(rectangle, index + 1, '#22c55e'));
  if (roiDraft) drawRectangle(roiDraft, state.rois.length + 1, '#f59e0b');
  document.getElementById('roiCoordinates').textContent = state.rois.length
    ? `${state.rois.length} zone${state.rois.length > 1 ? 's' : ''} définie${state.rois.length > 1 ? 's' : ''}.`
    : 'Aucune ROI définie (image entière utilisée).';
}

function renderRoiList() {
  roiList.replaceChildren();
  clearRoiButton.disabled = state.rois.length === 0;
  state.rois.forEach((rectangle, index) => {
    const item = document.createElement('div');
    item.className = 'roi-list-item';
    const label = document.createElement('span');
    label.textContent = `Zone ${index + 1} · x ${rectangle[0].toFixed(3)}, y ${rectangle[1].toFixed(3)}, ${rectangle[2].toFixed(3)} × ${rectangle[3].toFixed(3)}`;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'secondary';
    remove.textContent = 'Supprimer';
    remove.setAttribute('aria-label', `Supprimer la zone ${index + 1}`);
    remove.addEventListener('click', async () => {
      const [removed] = state.rois.splice(index, 1);
      drawRoi();
      try {
        await saveRoi();
      } catch (error) {
        state.rois.splice(index, 0, removed);
        drawRoi();
        setRoiStatus(error.message, true);
      }
    });
    item.append(label, remove);
    roiList.appendChild(item);
  });
}

function parseRois(value) {
  if (!value) return [];
  let parsed;
  if (typeof value === 'string' && value.trim().startsWith('[')) {
    try {
      parsed = JSON.parse(value);
    } catch (error) {
      console.error('Liste de ROI locale illisible', error);
      return [];
    }
  } else if (typeof value === 'string') {
    parsed = value.split(',').map(Number);
  } else {
    parsed = value;
  }
  if (!Array.isArray(parsed)) return [];
  const rectangles = parsed.length === 4 && parsed.every((part) => Number.isFinite(Number(part)))
    ? [parsed]
    : parsed;
  return rectangles
    .filter((rectangle) => Array.isArray(rectangle) && rectangle.length === 4
      && rectangle.every((part) => Number.isFinite(Number(part))))
    .map((rectangle) => rectangle.map(Number));
}

function roiPayload() {
  return state.rois.length ? JSON.stringify(state.rois) : null;
}

function setRoiStatus(message, isError = false) {
  roiStatus.textContent = message;
  roiStatus.className = isError ? 'form-message error' : 'form-message';
}

async function saveRoi() {
  constrainAnalysisWindowToVideo();
  const payload = await apiRequest(`/api/stations/${stationId}/analysis-settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      roi: roiPayload(),
      fenetre_debut: Number(document.getElementById('windowStart').value || 0),
      fenetre_fin: Number(document.getElementById('windowEnd').value) || null,
    }),
  });
  state.station = { ...state.station, ...payload };
  drawRoi();
  setRoiStatus(state.rois.length
    ? `${state.rois.length} zone${state.rois.length > 1 ? 's' : ''} enregistrée${state.rois.length > 1 ? 's' : ''} localement.`
    : 'Toutes les zones ont été effacées.');
}

function frameUrl(time) {
  return `/api/stations/${stationId}/frame?time_s=${encodeURIComponent(time)}&cache=${Date.now()}`;
}

let frameLoadTimer = null;
let loadedFrameTime = null;
function scheduleFrameLoad() {
  if (!state.station?.video_path) return;
  window.clearTimeout(frameLoadTimer);
  frameLoadTimer = window.setTimeout(() => {
    roiFrame.src = frameUrl(Number(video.currentTime) || 0);
    roiPreview.style.display = 'inline-block';
  }, 150);
}

async function loadStation() {
  if (!stationId) {
    stationTitle.textContent = 'Aucun poste sélectionné';
    return;
  }
  try {
    const payload = await apiRequest(`/api/stations/${stationId}`);
    state.station = payload;
    state.phases = payload.phases || [];
    try {
      await loadCycles();
    } catch (error) {
      state.cycles = [];
      renderCycleList();
      cycleControls.forEach((control) => {
        control.disabled = true;
      });
      showCycleStatus(
        `La comparaison des cycles n’est pas disponible sur le serveur actuel. Redémarrez Kaizen Studio pour activer cette fonction. (${error.message})`,
        true,
      );
    }
    state.ergonomicAssessments = payload.ergonomic_assessments || [];
    renderErgonomicAssessments();
    try {
      state.postureSamples = JSON.parse(payload.posture_signal_json || '[]');
    } catch (error) {
      console.error('Signal de posture local illisible', error);
      state.postureSamples = [];
    }
    state.selectedPostureSample = null;
    renderPostureCandidates();
    if (state.postureSamples.length) {
      postureStatus.textContent = `${state.postureSamples.length} images de posture chargées depuis l’analyse locale.`;
    }
    await loadOperationCatalog();
    applyAnalysisConfiguration(payload);
    state.rois = parseRois(payload.roi);
    try {
      state.motionSamples = JSON.parse(payload.motion_signal_json || '[]');
    } catch (error) {
      console.error('Signal de mouvement local illisible', error);
      state.motionSamples = [];
    }
    state.detectedThreshold = Number(payload.motion_threshold_pct || 0);
    stationTitle.textContent = payload.nom || 'Poste';
    document.getElementById('windowStart').value = payload.fenetre_debut ?? 0;
    document.getElementById('windowEnd').value = payload.fenetre_fin ?? payload.video_duration_s ?? '';
    if (payload.video_path) {
      video.src = `/api/stations/${stationId}/video`;
      addRoiButton.disabled = false;
      scheduleFrameLoad();
    } else {
      video.style.display = 'none';
      addRoiButton.disabled = true;
    }

    refreshDisplay();
  } catch (error) {
    console.error(error);
    stationTitle.textContent = 'Erreur de chargement';
    showAnalysisStatus(error.message, true);
  }
}

function constrainAnalysisWindowToVideo() {
  const duration = Number.isFinite(video.duration) && video.duration > 0
    ? video.duration
    : Number(state.station?.video_duration_s);
  if (!Number.isFinite(duration) || duration <= 0) return;
  const startInput = document.getElementById('windowStart');
  const endInput = document.getElementById('windowEnd');
  startInput.max = String(duration);
  endInput.max = String(duration);

  const start = Math.max(0, Math.min(Number(startInput.value) || 0, duration));
  const end = Number(endInput.value);
  const safeStart = Math.floor(start * 10 + 1e-8) / 10;
  const safeEnd = Math.floor(duration * 10 + 1e-8) / 10;
  startInput.value = safeStart.toFixed(1);
  if (!Number.isFinite(end) || end > duration || end <= safeStart) {
    endInput.value = safeEnd > safeStart
      ? safeEnd.toFixed(1)
      : duration.toFixed(3);
    showAnalysisStatus(
      `La fenêtre de fin a été ajustée à la durée de la vidéo (${formatSeconds(duration)}).`,
    );
  }
}

video.addEventListener('loadedmetadata', constrainAnalysisWindowToVideo);
video.addEventListener('loadedmetadata', drawPostureOverlay);
video.addEventListener('loadedmetadata', () => {
  updateVideoTimeReadouts();
});
video.addEventListener('timeupdate', drawPostureOverlay);
video.addEventListener('seeked', () => {
  drawPostureOverlay();
  updateVideoTimeReadouts();
});
video.addEventListener('timeupdate', () => {
  updateVideoTimeReadouts();
  if (state.playbackEnd != null && video.currentTime >= state.playbackEnd) {
    video.pause();
    video.currentTime = state.playbackEnd;
    state.playbackEnd = null;
  }
  renderMotionChart();
});
video.addEventListener('play', () => {
  playToggle.textContent = 'Pause';
  roiDrawingEnabled = false;
  roiDraft = null;
  drawRoi();
  setRoiStatus('Mets la vidéo en pause pour capturer une image et sélectionner une zone.');
});
video.addEventListener('pause', () => {
  playToggle.textContent = 'Lecture';
  scheduleFrameLoad();
});
window.addEventListener('resize', drawPostureOverlay);
analyzePostureButton.addEventListener('click', startPostureAnalysis);
assessmentForm.addEventListener('submit', saveErgonomicAssessment);
prefillAssessmentButton.addEventListener('click', prefillErgonomicAssessment);
assessmentTimeInput.addEventListener('input', () => {
  scheduleConfigurationSave('ergonomics');
  const time = Number(assessmentTimeInput.value);
  if (state.selectedPostureSample && Math.abs(Number(state.selectedPostureSample.time_s) - time) > 0.051) {
    state.selectedPostureSample = null;
    renderPostureCandidates();
  }
  updateAssessmentAngleHint(time);
});
useCurrentAssessmentTime.addEventListener('click', () => {
  const samples = state.postureSamples.filter((sample) => Number.isFinite(Number(sample.time_s))
    && availablePostureAngles(sample).length > 0);
  const nearest = samples.reduce((best, sample) =>
    !best || Math.abs(Number(sample.time_s) - video.currentTime) < Math.abs(Number(best.time_s) - video.currentTime)
      ? sample
      : best,
  null);
  if (!nearest) {
    showScoringFeedback('Aucune image avec des angles exploitables. Lancez d’abord « Analyser les postures ».', true);
    return;
  }
  selectPostureCandidate(nearest);
});

async function startAnalysis() {
  if (state.busy) return;
  constrainAnalysisWindowToVideo();
  const start = Number(document.getElementById('windowStart').value || 0);
  const end = Number(document.getElementById('windowEnd').value);
  if (!Number.isFinite(end) || end <= start) {
    showAnalysisStatus('La fin de fenêtre doit être supérieure au début.', true);
    return;
  }
  state.busy = true;
  analyzeButton.disabled = true;
  analysisProgress.value = 0;
  showAnalysisStatus('Mise en file de l’analyse locale…');
  try {
    const job = await apiRequest(`/api/stations/${stationId}/analysis`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        fenetre_debut: start,
        fenetre_fin: end,
        roi: roiPayload(),
        fps: 5,
        seuil_pct: state.threshold,
        duree_min_s: state.minLength,
      }),
    });
    let result;
    do {
      await new Promise((resolve) => window.setTimeout(resolve, 400));
      result = await apiRequest(job.poll_url);
      analysisProgress.value = result.progress || 0;
      showAnalysisStatus(
        result.status === 'running'
          ? `Analyse locale en cours… ${result.progress || 0} %`
          : result.status === 'queued'
            ? 'Analyse en attente…'
            : 'Enregistrement des phases…',
      );
    } while (result.status === 'queued' || result.status === 'running');

    if (result.status !== 'completed') {
      throw new Error(result.error || 'L’analyse a échoué.');
    }
    state.motionSamples = result.motion_samples || [];
    state.detectedThreshold = Number(result.threshold_pct || 0);
    await loadStation();
    analysisProgress.value = 100;
    showAnalysisStatus(`${result.phase_count} phases produites. Ce sont des estimations à valider au chronomètre.`);
  } catch (error) {
    showAnalysisStatus(error.message, true);
  } finally {
    state.busy = false;
    analyzeButton.disabled = false;
  }
}

async function resegmentPhases() {
  if (state.busy) return;
  state.busy = true;
  analyzeButton.disabled = true;
  try {
    state.phases = await apiRequest(`/api/stations/${stationId}/resegment`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        seuil_pct: state.threshold || null,
        duree_min_s: state.minLength,
      }),
    });
    refreshDisplay();
    showAnalysisStatus('Phases recalculées à partir du signal enregistré, sans relire la vidéo.');
  } catch (error) {
    showAnalysisStatus(error.message, true);
  } finally {
    state.busy = false;
    analyzeButton.disabled = false;
  }
}

thresholdSlider.addEventListener('input', () => {
  state.threshold = Number(thresholdSlider.value);
  refreshDisplay();
  scheduleConfigurationSave('review');
});
minLengthSlider.addEventListener('input', () => {
  state.minLength = Number(minLengthSlider.value);
  refreshDisplay();
  scheduleConfigurationSave('review');
});
document.getElementById('windowStart').addEventListener('input', () => {
  scheduleConfigurationSave('review');
});
document.getElementById('windowEnd').addEventListener('input', () => {
  scheduleConfigurationSave('review');
});

let analysisDebounce = null;
function scheduleAnalysisAfterSettingChange() {
  if (!state.station?.video_path) return;
  window.clearTimeout(analysisDebounce);
  analysisDebounce = window.setTimeout(
    state.motionSamples.length ? resegmentPhases : startAnalysis,
    450,
  );
}

thresholdSlider.addEventListener('change', scheduleAnalysisAfterSettingChange);
minLengthSlider.addEventListener('change', scheduleAnalysisAfterSettingChange);

playToggle.addEventListener('click', () => {
  if (!video.src) return;
  if (video.paused) {
    const selected = state.phases.find((phase) => phase.id === state.selectedPhaseId);
    if (selected) {
      if (video.currentTime < Number(selected.debut_s) || video.currentTime >= Number(selected.fin_s)) {
        video.currentTime = Number(selected.debut_s);
      }
      state.playbackEnd = Number(selected.fin_s);
    }
    video.play().catch((error) => showAnalysisStatus(`Lecture impossible : ${error.message}`, true));
  } else {
    video.pause();
  }
});

playFullVideoButton.addEventListener('click', () => {
  state.selectedPhaseId = null;
  state.playbackEnd = null;
  selectedInterval.textContent = 'Lecture complète de la vidéo.';
  renderTimeline();
  renderMotionChart();
  video.currentTime = 0;
  video.play().catch((error) => showAnalysisStatus(`Lecture impossible : ${error.message}`, true));
});

analyzeButton.addEventListener('click', startAnalysis);

document.getElementById('splitPhase').addEventListener('click', async () => {
  const currentTime = Math.round(Number(video.currentTime) * 10) / 10;
  const phase = state.phases.find((item) => currentTime > Number(item.debut_s) && currentTime < Number(item.fin_s));
  if (!phase) {
    showAnalysisStatus('Place la vidéo à l’intérieur d’une phase avant de la couper.', true);
    return;
  }
  try {
    state.phases = await apiRequest(`/api/stations/${stationId}/phases/${phase.id}/split`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ temps_s: currentTime }),
    });
    refreshDisplay();
    showAnalysisStatus('Phase coupée et enregistrée.');
  } catch (error) {
    showAnalysisStatus(error.message, true);
  }
});

document.getElementById('mergePhases').addEventListener('click', async () => {
  const ids = [...selectedPhases];
  if (ids.length !== 2) {
    showAnalysisStatus('Sélectionne exactement deux phases voisines.', true);
    return;
  }
  try {
    state.phases = await apiRequest(`/api/stations/${stationId}/phases/merge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phase_ids: ids }),
    });
    selectedPhases.clear();
    refreshDisplay();
    showAnalysisStatus('Phases fusionnées et enregistrées.');
  } catch (error) {
    showAnalysisStatus(error.message, true);
  }
});

roiFrame.addEventListener('load', drawRoi);
roiFrame.addEventListener('load', () => {
  loadedFrameTime = Number(new URL(roiFrame.src).searchParams.get('time_s'));
  if (roiDrawingEnabled && loadedFrameTime != null) {
    setRoiStatus(`Image figée à ${formatSeconds(loadedFrameTime)}. Trace le rectangle de la zone.`);
  }
});
roiFrame.addEventListener('error', () => {
  setRoiStatus('Impossible de capturer cette image vidéo pour définir les zones.', true);
});
video.addEventListener('seeked', scheduleFrameLoad);
video.addEventListener('loadedmetadata', scheduleFrameLoad);
video.addEventListener('loadedmetadata', renderVideoAnnotations);

operationForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const name = operationName.value.trim();
  if (!name) {
    showOperationStatus('Saisissez un nom d’opération.', true);
    return;
  }
  const submit = operationForm.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    await apiRequest(`/api/projects/${state.station.project_id}/operations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nom: name }),
    });
    operationName.value = '';
    scheduleConfigurationSave('operations');
    await refreshAnnotationData();
    showOperationStatus('Opération ajoutée au référentiel du projet.');
  } catch (error) {
    showOperationStatus(error.message, true);
  } finally {
    submit.disabled = false;
  }
});

datasetSplit.addEventListener('change', async () => {
  const previousSplit = state.station.dataset_split || 'excluded';
  datasetSplit.disabled = true;
  try {
    const result = await apiRequest(`/api/stations/${stationId}/dataset-split`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ split: datasetSplit.value }),
    });
    state.station.dataset_split = result.split;
    await refreshAnnotationData();
    showOperationStatus('Affectation de la vidéo enregistrée.');
  } catch (error) {
    datasetSplit.value = previousSplit;
    showOperationStatus(error.message, true);
  } finally {
    datasetSplit.disabled = false;
  }
});

for (const [buttonId, input] of [
  ['setAnnotationStart', annotationStart],
  ['setAnnotationEnd', annotationEnd],
]) {
  document.getElementById(buttonId).addEventListener('click', () => {
    input.value = (Number(video.currentTime) || 0).toFixed(1);
    scheduleConfigurationSave('operations');
  });
}

annotationForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const start = Number(annotationStart.value);
  const end = Number(annotationEnd.value);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) {
    showAnnotationStatus('Saisissez un intervalle valide, avec une fin après le début.', true);
    return;
  }
  const body = JSON.stringify({
    operation_id: annotationOperation.value ? Number(annotationOperation.value) : null,
    debut_s: start,
    fin_s: end,
  });
  const editingId = state.annotationEditId;
  saveAnnotation.disabled = true;
  try {
    await apiRequest(
      editingId
        ? `/api/stations/${stationId}/annotations/${editingId}`
        : `/api/stations/${stationId}/annotations`,
      {
        method: editingId ? 'PATCH' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
      },
    );
    resetAnnotationForm();
    await refreshAnnotationData();
    showAnnotationStatus(editingId ? 'Annotation mise à jour.' : 'Annotation enregistrée.');
  } catch (error) {
    showAnnotationStatus(error.message, true);
  } finally {
    saveAnnotation.disabled = false;
  }
});

for (const control of [operationName, annotationOperation, annotationStart, annotationEnd]) {
  control.addEventListener('input', () => scheduleConfigurationSave('operations'));
  control.addEventListener('change', () => scheduleConfigurationSave('operations'));
}

function resetAnnotationForm() {
  state.annotationEditId = null;
  annotationForm.reset();
  saveAnnotation.textContent = 'Ajouter l’annotation';
  cancelAnnotationEdit.hidden = true;
  scheduleConfigurationSave('operations');
}

cancelAnnotationEdit.addEventListener('click', () => {
  resetAnnotationForm();
  showAnnotationStatus('Modification annulée.');
});

downloadAnnotationManifest.addEventListener('click', async () => {
  downloadAnnotationManifest.disabled = true;
  try {
    const manifest = await apiRequest(`/api/projects/${state.station.project_id}/annotation-manifest`);
    const file = new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(file);
    const link = document.createElement('a');
    link.href = url;
    link.download = `kaizen-studio-annotations-projet-${state.station.project_id}.json`;
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    showOperationStatus(`Export du manifeste impossible : ${error.message}`, true);
  } finally {
    downloadAnnotationManifest.disabled = false;
  }
});

trainOperationModelButton.addEventListener('click', async () => {
  trainOperationModelButton.disabled = true;
  suggestOperationsButton.disabled = true;
  state.modelSuggestions = [];
  renderModelSuggestions();
  operationModelStatus.textContent = 'Extraction des images et entraînement local en cours…';
  operationModelStatus.className = 'form-message';
  operationModelResults.replaceChildren();
  try {
    const result = await apiRequest(`/api/projects/${state.station.project_id}/operation-model/train`, {
      method: 'POST',
    });
    showOperationModelStatus(result);
    modelSuggestionStatus.textContent = '';
    await refreshAnnotationData();
    operationModelStatus.textContent = result.message;
    operationModelStatus.className = 'form-message success';
  } catch (error) {
    operationModelStatus.textContent = `Entraînement impossible : ${error.message}`;
    operationModelStatus.className = 'form-message error';
  } finally {
    trainOperationModelButton.disabled = false;
    if (state.operationModel) showOperationModelStatus(state.operationModel);
  }
});

suggestOperationsButton.addEventListener('click', async () => {
  suggestOperationsButton.disabled = true;
  state.modelSuggestions = [];
  renderModelSuggestions();
  modelSuggestionStatus.textContent = 'Analyse locale des phases d’activité…';
  modelSuggestionStatus.className = 'form-message';
  try {
    const result = await apiRequest(`/api/stations/${stationId}/operation-suggestions`, {
      method: 'POST',
    });
    state.modelSuggestions = result.suggestions;
    renderModelSuggestions();
    const message = `${result.suggestions.length} suggestion(s) à vérifier ; ${result.uncertain} phase(s) rejetée(s) car le score était trop faible ; ${result.already_annotated} phase(s) déjà annotée(s). ${result.message}`;
    modelSuggestionStatus.textContent = message;
    modelSuggestionStatus.className = 'form-message';
  } catch (error) {
    modelSuggestionStatus.textContent = `Propositions impossibles : ${error.message}`;
    modelSuggestionStatus.className = 'form-message error';
  } finally {
    suggestOperationsButton.disabled = false;
    if (state.operationModel) showOperationModelStatus(state.operationModel);
  }
});

roiCanvas.addEventListener('pointerdown', (event) => {
  if (!roiDrawingEnabled) return;
  if (!video.paused) {
    setRoiStatus('Mets la vidéo en pause avant de sélectionner une zone.', true);
    return;
  }
  if (loadedFrameTime == null || Math.abs(loadedFrameTime - video.currentTime) > 0.05) {
    setRoiStatus('Capture de l’image en cours ; attends son affichage avant de dessiner.', true);
    scheduleFrameLoad();
    return;
  }
  if (!roiCanvas.width || !roiCanvas.height) return;
  const rect = roiCanvas.getBoundingClientRect();
  roiDragStart = {
    x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
    y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
  };
  roiCanvas.setPointerCapture(event.pointerId);
});
roiCanvas.addEventListener('pointermove', (event) => {
  if (!roiDragStart) return;
  const rect = roiCanvas.getBoundingClientRect();
  const x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
  const y = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
  roiDraft = [
    Math.min(roiDragStart.x, x),
    Math.min(roiDragStart.y, y),
    Math.abs(x - roiDragStart.x),
    Math.abs(y - roiDragStart.y),
  ];
  drawRoi();
});
roiCanvas.addEventListener('pointerup', async () => {
  if (!roiDragStart) return;
  roiDragStart = null;
  const rectangle = roiDraft;
  roiDraft = null;
  if (rectangle && rectangle[2] >= 0.01 && rectangle[3] >= 0.01) {
    state.rois.push(rectangle);
    roiDrawingEnabled = false;
    drawRoi();
    try {
      await saveRoi();
    } catch (error) {
      state.rois.pop();
      drawRoi();
      setRoiStatus(error.message, true);
    }
  } else {
    drawRoi();
    setRoiStatus('La zone sélectionnée est trop petite.', true);
  }
});
addRoiButton.addEventListener('click', () => {
  if (!state.station?.video_path) {
    setRoiStatus('Aucune vidéo n’est disponible pour définir une zone.', true);
    return;
  }
  if (!video.paused) video.pause();
  roiDrawingEnabled = true;
  scheduleFrameLoad();
  drawRoi();
  setRoiStatus('Capture de l’image en pause…');
});
clearRoiButton.addEventListener('click', async () => {
  const previousRois = state.rois;
  state.rois = [];
  roiDraft = null;
  roiDrawingEnabled = false;
  drawRoi();
  try {
    await saveRoi();
  } catch (error) {
    state.rois = previousRois;
    drawRoi();
    setRoiStatus(error.message, true);
  }
});

document.getElementById('setCycleStart').addEventListener('click', () => {
  cycleStartInput.value = (Number(video.currentTime) || 0).toFixed(1);
  scheduleConfigurationSave('cycles');
});
document.getElementById('setCycleEnd').addEventListener('click', () => {
  cycleEndInput.value = (Number(video.currentTime) || 0).toFixed(1);
  scheduleConfigurationSave('cycles');
});
for (const control of [
  cycleStartInput,
  cycleEndInput,
  document.getElementById('minimumStop'),
  document.getElementById('minimumCycle'),
]) {
  control.addEventListener('input', () => scheduleConfigurationSave('cycles'));
  control.addEventListener('change', () => scheduleConfigurationSave('cycles'));
}
document.getElementById('saveCycle').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  const start = Number(cycleStartInput.value);
  const end = Number(cycleEndInput.value);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) {
    showCycleStatus('Saisissez un début et une fin valides, avec une fin après le début.', true);
    return;
  }
  button.disabled = true;
  try {
    await apiRequest(`/api/stations/${stationId}/cycles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ debut_s: start, fin_s: end, source: 'manual' }),
    });
    cycleStartInput.value = '';
    cycleEndInput.value = '';
    await loadCycles();
    scheduleConfigurationSave('cycles');
    showCycleStatus('Cycle ajouté.');
  } catch (error) {
    showCycleStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
});
document.getElementById('suggestCycles').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  cycleCandidates.replaceChildren();
  try {
    const minStop = Number(document.getElementById('minimumStop').value);
    const minCycle = Number(document.getElementById('minimumCycle').value);
    if (!Number.isFinite(minStop) || minStop <= 0 || !Number.isFinite(minCycle) || minCycle <= 0) {
      throw new Error('Les durées minimales doivent être positives.');
    }
    const query = new URLSearchParams({ min_stop_s: String(minStop), min_cycle_s: String(minCycle) });
    const result = await apiRequest(`/api/stations/${stationId}/cycle-candidates?${query}`);
    state.cycleSuggestions = result.candidates;
    renderCycleSuggestions();
    showCycleStatus(result.candidates.length
      ? `${result.warning} Vérifiez les propositions avant de les ajouter.`
      : 'Aucune proposition trouvée. Essayez un seuil différent ou délimitez les cycles manuellement.');
  } catch (error) {
    showCycleStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
});

phaseSearch.addEventListener('input', renderPhaseList);
phaseTypeFilter.addEventListener('change', renderPhaseList);
phaseCategoryFilter.addEventListener('change', renderPhaseList);

function updateVideoTimeReadouts() {
  const time = `Instant vidéo courant : ${formatSeconds(video.currentTime)}`;
  sharedVideoTime.textContent = formatSeconds(video.currentTime);
  annotationVideoTime.textContent = time;
}

const reviewTabButtons = [...document.querySelectorAll('.review-tab-button[data-review-tab]')];
const reviewTabPanels = [...document.querySelectorAll('.review-tab-panel')];
const reviewTabStorageKey = `kaizen-review-tab:${stationId}`;

function activateReviewTab(tabName, focusButton = false) {
  const selectedButton = reviewTabButtons.find((button) => button.dataset.reviewTab === tabName);
  if (!selectedButton) return;
  reviewTabButtons.forEach((button) => {
    const selected = button === selectedButton;
    button.setAttribute('aria-selected', String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  reviewTabPanels.forEach((panel) => {
    panel.hidden = panel.id !== selectedButton.getAttribute('aria-controls');
  });
  try {
    window.localStorage.setItem(reviewTabStorageKey, tabName);
  } catch (error) {
    console.warn('Onglet actif non mémorisé dans le stockage local du navigateur.', error);
  }
  if (focusButton) selectedButton.focus();
  if (tabName === 'review') {
    window.requestAnimationFrame(() => {
      drawPostureOverlay();
      renderMotionChart();
    });
  }
}

let initialReviewTab = 'review';
try {
  const storedTab = window.localStorage.getItem(reviewTabStorageKey);
  if (reviewTabButtons.some((button) => button.dataset.reviewTab === storedTab)) {
    initialReviewTab = storedTab;
  }
} catch (error) {
  console.warn('Onglet actif non lu depuis le stockage local du navigateur.', error);
}

reviewTabButtons.forEach((button, index) => {
  button.addEventListener('click', () => activateReviewTab(button.dataset.reviewTab));
  button.addEventListener('keydown', (event) => {
    let nextIndex = index;
    if (event.key === 'ArrowRight') nextIndex = (index + 1) % reviewTabButtons.length;
    else if (event.key === 'ArrowLeft') nextIndex = (index - 1 + reviewTabButtons.length) % reviewTabButtons.length;
    else if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = reviewTabButtons.length - 1;
    else return;
    event.preventDefault();
    activateReviewTab(reviewTabButtons[nextIndex].dataset.reviewTab, true);
  });
});
activateReviewTab(initialReviewTab);

loadStation();
window.addEventListener('resize', () => {
  renderTimeline();
  renderMotionChart();
});
