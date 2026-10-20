from __future__ import annotations

def test_dashboard_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200, response.text
    assert "Kaizen Studio" in response.text
    assert "Démarrer une étude" in response.text
    assert "Créer le projet" in response.text
    assert "project-layout-1" in response.text
    assert 'id="videoMaxMb"' in response.text
    assert "streamed-video-upload-1" in response.text
    dashboard_script = client.get("/static/dashboard.js")
    assert "stations/import" in dashboard_script.text
    assert "import-stream" in dashboard_script.text
    assert "request.upload" in dashboard_script.text
    assert "Supprimer le projet" in dashboard_script.text
    assert "pour lancer l’import local" in dashboard_script.text
    assert "RULA" in dashboard_script.text
    assert "REBA" in dashboard_script.text
    assert "/api/dashboard" in dashboard_script.text
    assert "project-progress-track" in dashboard_script.text
    assert "station-add" in dashboard_script.text
    assert "Ajouter un poste et sa vidéo" in dashboard_script.text
    assert "projectSearch" in response.text


def test_review_page_is_served_for_station(client):
    project = client.post("/api/projects", json={"nom": "Projet UI", "takt_s": 45})
    assert project.status_code == 201, project.text
    station = client.post(
        f"/api/projects/{project.json()['id']}/stations",
        json={"nom": "Poste UI", "video_path": ""},
    )
    assert station.status_code == 201, station.text

    response = client.get(f"/review/{station.json()['id']}")
    assert response.status_code == 200, response.text
    assert "Kaizen Studio" in response.text
    assert "Analyser le mouvement" in response.text
    assert "Couper au temps vidéo" in response.text
    assert 'id="playFullVideo"' in response.text
    assert 'id="selectedInterval"' in response.text
    assert 'id="timeline" class="timeline"' in response.text
    assert 'id="phaseSearch" type="search"' in response.text
    assert 'id="phaseTypeFilter"' in response.text
    assert 'id="phaseCategoryFilter"' in response.text
    assert 'id="phaseFilterCount"' in response.text
    assert 'class="review-back-link" href="/"' in response.text
    assert 'name="viewport" content="width=device-width, initial-scale=1.0, minimum-scale=0.5, maximum-scale=5.0, user-scalable=yes"' in response.text
    assert 'class="topbar review-topbar"' in response.text
    assert 'class="review-heading"' in response.text
    assert "Retour aux projets" in response.text
    assert 'role="tablist"' in response.text
    assert 'id="reviewTabButton-review"' in response.text
    assert 'id="reviewTabButton-operations"' in response.text
    assert 'id="reviewTabButton-cycles"' in response.text
    assert 'id="reviewTabButton-ergonomics"' in response.text
    assert 'id="reviewTabPanel-review"' in response.text
    assert 'id="reviewTabPanel-operations"' in response.text
    assert 'id="reviewTabPanel-cycles"' in response.text
    assert 'id="reviewTabPanel-ergonomics"' in response.text
    assert 'id="configurationSaveStatus"' in response.text
    assert 'class="review-sidebar shared-video-tools"' in response.text
    assert 'id="sharedVideoTime"' in response.text
    assert 'id="videoPlayer"' in response.text
    assert 'id="roiCanvas"' in response.text
    assert 'id="addRoi"' in response.text
    assert 'id="roiList"' in response.text
    assert 'id="roiStatus"' in response.text
    assert "Mets la vidéo en pause sur une image nette" in response.text
    assert 'id="analyzeButton"' in response.text
    assert response.text.count('id="videoPlayer"') == 1
    assert response.text.count('id="roiCanvas"') == 1
    assert response.text.index('class="review-sidebar shared-video-tools"') < response.text.index('role="tablist"')
    assert 'id="videoPlayer"' not in response.text[response.text.index('id="reviewTabPanel-review"'):]
    assert 'id="roiCanvas"' not in response.text[response.text.index('id="reviewTabPanel-review"'):]
    assert "Comparer plusieurs cycles" in response.text
    assert "Proposer depuis les arrêts détectés" in response.text
    assert response.text.index('id="reviewTabPanel-review"') < response.text.index('id="reviewTabPanel-operations"')
    assert response.text.index('id="reviewTabPanel-operations"') < response.text.index('id="reviewTabPanel-cycles"')
    assert response.text.index('id="reviewTabPanel-cycles"') < response.text.index('id="reviewTabPanel-ergonomics"')
    assert 'id="cycleStart"' in response.text
    assert 'id="cycleEnd"' in response.text
    assert 'class="review-sidebar shared-video-tools"' in response.text
    assert 'class="review-workspace"' in response.text
    assert "Préparer les opérations à reconnaître" in response.text
    assert "operationSuggestions" in response.text
    assert 'id="annotationTimeline"' in response.text
    assert 'id="operationForm"' in response.text
    assert 'id="datasetSplit"' in response.text
    assert 'id="annotationForm"' in response.text
    assert "Autre / incertain" in response.text
    assert "Exporter les annotations du projet (JSON)" in response.text
    assert "classifieur local" in response.text
    assert 'id="trainOperationModel"' in response.text
    assert 'id="suggestOperations"' in response.text
    assert 'id="modelSuggestions"' in response.text
    assert "review-steps-scroll-1" in response.text
    assert "Suivi de posture local" in response.text
    assert "Pré-cotation à valider par l’évaluateur" in response.text
    assert 'id="cameraView"' in response.text
    assert 'id="prefillAssessment"' in response.text
    assert 'id="scoringResult"' in response.text
    assert 'id="postureCandidateList"' in response.text
    assert 'id="postureCandidateSummary"' in response.text
    assert 'name="charge_kg"' in response.text
    assert 'name="torsion_tronc"' in response.text
    assert 'name="frequence_geste_par_min"' in response.text
    assert 'name="posture_statique_sup_1min"' in response.text
    assert "J’ai vérifié la posture et validé ou corrigé cette pré-cotation" in response.text
    assert "Enregistrer la cotation" in response.text
    assert "Utiliser l’instant vidéo courant" in response.text
    assert "Les images partielles restent sélectionnables" in response.text
    review_script = client.get("/static/app.js")
    assert "/api/stations/${stationId}/analysis" in review_script.text
    assert "/api/projects/${state.station.project_id}/operations" in review_script.text
    assert "/api/stations/${stationId}/annotations" in review_script.text
    assert "/api/stations/${stationId}/dataset-split" in review_script.text
    assert "/api/stations/${stationId}/analysis-configuration" in review_script.text
    assert "/api/projects/${state.station.project_id}/annotation-manifest" in review_script.text
    assert "/api/projects/${state.station.project_id}/operation-model/train" in review_script.text
    assert "/api/stations/${stationId}/operation-suggestions" in review_script.text
    assert "function renderVideoAnnotations()" in review_script.text
    assert "function showDatasetSummary(dataset)" in review_script.text
    assert "function activateReviewTab(tabName, focusButton = false)" in review_script.text
    assert "function applyAnalysisConfiguration(payload)" in review_script.text
    assert "scheduleConfigurationSave('cycles')" in review_script.text
    assert "scheduleConfigurationSave('ergonomics')" in review_script.text
    assert "event.key === 'ArrowRight'" in review_script.text
    assert "event.key === 'ArrowLeft'" in review_script.text
    assert "kaizen-review-tab:${stationId}" in review_script.text
    assert "function updateVideoTimeReadouts()" in review_script.text
    assert "function parseRois(value)" in review_script.text
    assert "roiFrame.addEventListener('load'" in review_script.text
    assert "video.addEventListener('pause'" in review_script.text
    assert "roi: roiPayload()" in review_script.text
    assert "Opération observée" in review_script.text
    assert "Opération partagée" in review_script.text
    assert "window.location.pathname.match(/^\\/review\\/(\\d+)\\/?$/)" in review_script.text
    assert "/api/stations/${stationId}/posture-analysis" in review_script.text
    assert "/api/stations/${stationId}/ergonomic-assessments" in review_script.text
    assert "/api/ergonomics/score" in review_script.text
    assert "async function prefillErgonomicAssessment()" in review_script.text
    assert "function renderPostureCandidates()" in review_script.text
    assert "function selectPostureCandidate(sample)" in review_script.text
    assert "Choisissez une image de posture dans la liste" in review_script.text
    assert "Aucun angle exploitable sur cette image." in review_script.text
    assert "Questions à confirmer avec l’évaluateur" in review_script.text
    assert "official_method_confirmed.checked = false" in review_script.text
    assert "drawPostureOverlay" in review_script.text
    assert "phaseDisplayLabel(phase)" in review_script.text
    assert "formatSeconds(end - start)" in review_script.text
    assert "keepTimelineSegmentVisible(segment)" in review_script.text
    assert "timeline.scrollBy" in review_script.text
    assert "updateSelectedPhaseCard(phase.id)" in review_script.text
    assert "updateSelectedTimelineSegment(phase.id)" in review_script.text
    assert "function updateSelectedTimelineSegment(phaseId)" in review_script.text
    assert "aria-current" in review_script.text
    assert "segment.setAttribute('aria-pressed', String(selected))" in review_script.text
    assert "scrollIntoView" not in review_script.text
    assert "state.playbackEnd = end" in review_script.text
    assert "video.currentTime >= state.playbackEnd" in review_script.text
    assert "renderMotionChart();" in review_script.text
    assert "formatSeconds(time)" in review_script.text
    assert "motionChart.clientWidth" in review_script.text
    assert "Type de phase" in review_script.text
    assert "updatePhase(phase.id, { type_auto: value })" in review_script.text
    assert 'item.dataset.phaseId = phase.id' in review_script.text
    assert "phaseList.querySelectorAll('.phase-item[data-phase-id]')" in review_script.text
    assert "selected-phase" in review_script.text
    assert "function normalizePhaseSearch(value)" in review_script.text
    assert "normalizePhaseSearch(phaseSearch.value.trim())" in review_script.text
    assert "const phaseNumberQuery = query.match(" in review_script.text
    assert "Number(phase.ordre) === requestedNumber" in review_script.text
    assert "phaseList.scrollTop = previousScrollTop" in review_script.text
    assert "await loadCycles();" in review_script.text
    assert "Redémarrez Kaizen Studio pour activer cette fonction." in review_script.text
    assert "function constrainAnalysisWindowToVideo()" in review_script.text
    assert "Math.floor(duration * 10 + 1e-8) / 10" in review_script.text
    styles = client.get("/static/styles.css")
    normalized_styles = styles.text.replace("\r\n", "\n")
    assert ".review-topbar {" in styles.text
    assert '"heading back"' in styles.text
    assert ".review-topbar > .review-back-link { grid-area: back;" in styles.text
    assert ".annotation-timeline {" in styles.text
    assert ".video-annotation-row {" in styles.text
    assert '"heading"' in styles.text
    assert ".review-tabs {" in styles.text
    assert "position: sticky;" in styles.text
    assert ".review-tab-button[aria-selected=\"true\"]" in styles.text
    assert ".review-tab-panel[hidden] { display: none; }" in styles.text
    assert ".review-layout {" in styles.text
    assert "grid-template-columns: minmax(300px, .8fr) minmax(0, 1.5fr)" in styles.text
    assert "min-height: calc(100vh - 150px);" not in styles.text
    assert ".review-workspace > .steps-panel .phase-list" in styles.text
    assert "max-height: max(15rem, min(72vh, calc(100vh - 8rem)));" in styles.text
    assert "overflow-y: auto;" in styles.text
    assert "overscroll-behavior: contain;" in styles.text
    assert ".cycle-tab-panel, .ergonomics-tab-panel" in styles.text
    assert "min-height: 0;" in styles.text
    assert "max-height: none;" in styles.text
    assert "@media (max-width: 1200px)" in styles.text
    assert ".shared-video-tools {" in styles.text
    assert "position: sticky;" in styles.text
    assert ".review-layout { grid-template-columns: minmax(0, 1fr); }" in styles.text
    assert "grid-template-columns: minmax(0, 1fr)" in styles.text
    assert "min-width: 0;" in styles.text


def test_summary_page_is_served_and_linked_from_dashboard(client):
    project = client.post("/api/projects", json={"nom": "Synthèse UI", "takt_s": 48})
    project_id = project.json()["id"]

    response = client.get(f"/projects/{project_id}/summary")
    assert response.status_code == 200, response.text
    assert "Yamazumi multi-postes" in response.text
    assert "Comparaison des cycles" in response.text
    assert 'id="cycleRows"' in response.text
    assert 'id="comparisonSearch" type="search"' in response.text
    assert 'id="comparisonCount"' in response.text
    assert "comparison-table-wrap" in response.text
    assert "summary-comparison-colors-3" in response.text
    assert ".summary-grid { display: grid;" in response.text
    assert ".takt-section { display: grid;" in response.text
    assert "#taktStatus:empty { display: none; }" in response.text
    assert "tbody tr:not(.comparison-note-row):hover" in response.text
    assert "@media (max-width: 700px)" in response.text
    assert "Vert pâle : activité sans chrono" in response.text
    assert "Vert soutenu : écart ≤ 10 %" in response.text
    assert "Orange : écart &gt; 10 % et ≤ 25 %" in response.text
    assert "Rouge : écart &gt; 25 %" in response.text
    assert "Scores ergonomiques" in response.text
    assert 'class="topbar summary-topbar"' in response.text
    assert 'class="back-link" href="/" aria-label="Retour au tableau de bord des projets"' in response.text
    script = client.get("/static/summary.js")
    assert "Erreur moyenne vs chrono" in script.text
    assert "function filterComparisonTable()" in script.text
    assert "row.dataset.phaseNumber = String(phase.ordre)" in script.text
    assert "row.classList.add('comparison-error-low')" in script.text
    assert "row.classList.add('comparison-error-medium')" in script.text
    assert "row.classList.add('comparison-error-high')" in script.text
    assert "phase.type_auto === 'stop' ? 'comparison-stop' : 'comparison-activity'" in script.text
    assert "comparisonSearch').addEventListener('input', filterComparisonTable)" in script.text
    assert "renderCycleTable(summaryData.stations)" in script.text
    assert "summary.latest_rula_score" in script.text or "station.latest_rula_score" in script.text
    assert "summary-score-chip" in script.text
    assert "function cycleStatistics(cycles, suppliedStatistics)" in script.text
    assert "Array.isArray(station.cycles) ? station.cycles : []" in script.text
    assert "Aucun poste ajouté à ce projet" in script.text
    assert "Ajouter un poste et sa vidéo" in script.text
    assert 'id="taktForm"' in response.text
    assert 'id="taktInput"' in response.text
    assert "method: 'PATCH'" in script.text
    assert "Les indicateurs et le Yamazumi ont été actualisés." in script.text

    dashboard_script = client.get("/static/dashboard.js")
    assert "Synthèse Yamazumi" in dashboard_script.text
    assert "article.id = `project-${project.id}`" in dashboard_script.text


def test_video_route_returns_404_when_missing(client):
    project = client.post("/api/projects", json={"nom": "Projet video", "takt_s": 50})
    station = client.post(
        f"/api/projects/{project.json()['id']}/stations",
        json={"nom": "Poste manquant", "video_path": "C:/absent/video.mp4"},
    )
    response = client.get(f"/api/stations/{station.json()['id']}/video")
    assert response.status_code == 404, response.text
