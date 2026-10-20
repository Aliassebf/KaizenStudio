const projectId = window.location.pathname.split('/').filter(Boolean)[1];
const colors = {
  VA: '#2e7d32',
  'NVA nécessaire': '#f9a825',
  Gaspillage: '#c62828',
  'Non classé': '#9e9e9e',
};
const categories = Object.keys(colors);
let summaryData = null;

function seconds(value) {
  return value == null ? '—' : `${Number(value).toFixed(1)} s`;
}

function percent(value) {
  return value == null ? '—' : `${Number(value).toFixed(1)} %`;
}

function makeCell(value) {
  const cell = document.createElement('td');
  cell.textContent = value;
  return cell;
}

function renderNextStep(data) {
  const container = document.getElementById('summaryNextStep');
  container.replaceChildren();
  const unanalysed = data.stations.filter((station) => station.temps_cycle <= 0);
  if (!data.stations.length) {
    const heading = document.createElement('h2');
    heading.textContent = 'Aucun poste ajouté à ce projet';
    const explanation = document.createElement('p');
    explanation.textContent = 'Pour obtenir un Yamazumi, ajoutez un poste avec sa vidéo locale, puis lancez l’analyse du mouvement et validez les phases dans l’écran de revue.';
    const link = document.createElement('a');
    link.href = `/#project-${encodeURIComponent(projectId)}`;
    link.className = 'station-review-link';
    link.textContent = 'Ajouter un poste et sa vidéo';
    container.append(heading, explanation, link);
    container.hidden = false;
    return;
  }

  if (unanalysed.length) {
    const heading = document.createElement('h2');
    heading.textContent = 'Analyse à compléter';
    const explanation = document.createElement('p');
    explanation.textContent = 'Ces postes n’ont pas encore de phases enregistrées. Ouvrez leur revue pour analyser la vidéo ; les durées restent des estimations à valider par chronométrage.';
    const links = document.createElement('div');
    for (const station of unanalysed) {
      const link = document.createElement('a');
      link.href = `/review/${station.station_id}?station_id=${station.station_id}`;
      link.className = 'station-review-link';
      link.textContent = `Ouvrir la revue — ${station.station_nom}`;
      links.appendChild(link);
    }
    container.append(heading, explanation, links);
    container.hidden = false;
    return;
  }

  container.hidden = true;
}

function renderMetrics(data) {
  const totalStations = data.stations.length;
  const averageCycle = totalStations
    ? data.stations.reduce((sum, station) => sum + station.temps_cycle, 0) / totalStations
    : 0;
  const averageVA = totalStations
    ? data.stations.reduce((sum, station) => sum + station.pct_va, 0) / totalStations
    : 0;
  const values = [
    ['Postes analysés', String(totalStations)],
    ['Takt projet', seconds(data.project.takt_s)],
    ['Cycle moyen estimé', seconds(averageCycle)],
    ['Part VA moyenne', percent(averageVA)],
    ['Erreur moyenne vs chrono', percent(data.comparaison_chrono.erreur_absolue_moyenne_pct)],
  ];
  const container = document.getElementById('metrics');
  container.replaceChildren();
  for (const [label, value] of values) {
    const card = document.createElement('div');
    card.className = 'metric-card';
    const title = document.createElement('span');
    title.textContent = label;
    const metric = document.createElement('strong');
    metric.textContent = value;
    card.append(title, metric);
    container.appendChild(card);
  }
}

function renderStationTable(stations) {
  const tbody = document.getElementById('stationRows');
  tbody.replaceChildren();
  for (const station of stations) {
    const row = document.createElement('tr');
    row.append(
      makeCell(station.station_nom),
      makeCell(seconds(station.VA)),
      makeCell(seconds(station['NVA nécessaire'])),
      makeCell(seconds(station.Gaspillage)),
      makeCell(seconds(station['Non classé'])),
      makeCell(seconds(station.temps_cycle)),
      makeCell(percent(station.pct_va)),
      makeCell(seconds(station.ecart_takt)),
    );
    const ergonomics = document.createElement('td');
    const scoreList = document.createElement('div');
    scoreList.className = 'summary-score-list';
    for (const [method, score, level] of [
      ['RULA', station.latest_rula_score, station.latest_rula_level],
      ['REBA', station.latest_reba_score, station.latest_reba_level],
    ]) {
      const chip = document.createElement('span');
      chip.className = `summary-score-chip${score == null ? ' missing' : ''}`;
      chip.textContent = score == null ? `${method} · À saisir` : `${method} ${score} · ${level}`;
      scoreList.appendChild(chip);
    }
    ergonomics.appendChild(scoreList);
    row.appendChild(ergonomics);
    const reviewCell = document.createElement('td');
    const reviewLink = document.createElement('a');
    reviewLink.href = `/review/${station.station_id}?station_id=${station.station_id}`;
    reviewLink.className = 'station-review-link';
    reviewLink.textContent = 'Ouvrir';
    reviewLink.setAttribute('aria-label', `Ouvrir la revue du poste ${station.station_nom}`);
    reviewCell.appendChild(reviewLink);
    row.appendChild(reviewCell);
    tbody.appendChild(row);
  }
}

function cycleStatistics(cycles, suppliedStatistics) {
  if (suppliedStatistics && Number.isFinite(Number(suppliedStatistics.nombre))) {
    return suppliedStatistics;
  }
  const durations = cycles
    .map((cycle) => Number(cycle.duree_s ?? (Number(cycle.fin_s) - Number(cycle.debut_s))))
    .filter((duration) => Number.isFinite(duration) && duration > 0)
    .sort((left, right) => left - right);
  if (!durations.length) {
    return {
      nombre: 0,
      moyenne_s: null,
      mediane_s: null,
      minimum_s: null,
      maximum_s: null,
      ecart_type_s: null,
      coefficient_variation_pct: null,
    };
  }
  const average = durations.reduce((sum, duration) => sum + duration, 0) / durations.length;
  const middle = Math.floor(durations.length / 2);
  const median = durations.length % 2
    ? durations[middle]
    : (durations[middle - 1] + durations[middle]) / 2;
  const deviation = durations.length > 1
    ? Math.sqrt(durations.reduce((sum, duration) => sum + (duration - average) ** 2, 0) / durations.length)
    : null;
  return {
    nombre: durations.length,
    moyenne_s: average,
    mediane_s: median,
    minimum_s: durations[0],
    maximum_s: durations[durations.length - 1],
    ecart_type_s: deviation,
    coefficient_variation_pct: deviation == null ? null : (average ? deviation / average * 100 : 0),
  };
}

function renderCycleTable(stations) {
  const tbody = document.getElementById('cycleRows');
  tbody.replaceChildren();
  for (const station of stations) {
    const cycles = Array.isArray(station.cycles) ? station.cycles : [];
    const stats = cycleStatistics(cycles, station.statistiques_cycles);
    const durations = cycles.length
      ? cycles.map((cycle, index) => {
        const duration = Number(cycle.duree_s ?? (Number(cycle.fin_s) - Number(cycle.debut_s)));
        return `C${index + 1} : ${Number.isFinite(duration) ? duration.toFixed(1) : '—'}`;
      }).join(' · ')
      : 'Aucun cycle enregistré';
    const row = document.createElement('tr');
    row.append(
      makeCell(station.station_nom),
      makeCell(durations),
      makeCell(String(stats.nombre)),
      makeCell(seconds(stats.moyenne_s)),
      makeCell(seconds(stats.mediane_s)),
      makeCell(stats.minimum_s == null ? '—' : `${Number(stats.minimum_s).toFixed(1)}–${Number(stats.maximum_s).toFixed(1)}`),
      makeCell(seconds(stats.ecart_type_s)),
      makeCell(percent(stats.coefficient_variation_pct)),
    );
    const action = document.createElement('td');
    const reviewLink = document.createElement('a');
    reviewLink.href = `/review/${station.station_id}?station_id=${station.station_id}`;
    reviewLink.className = 'station-review-link';
    reviewLink.textContent = 'Délimiter';
    reviewLink.setAttribute('aria-label', `Délimiter les cycles du poste ${station.station_nom}`);
    action.appendChild(reviewLink);
    row.appendChild(action);
    tbody.appendChild(row);
  }
  if (!stations.length) {
    const row = document.createElement('tr');
    row.appendChild(makeCell('Aucun poste ajouté à ce projet.'));
    tbody.appendChild(row);
  }
}

function renderComparisonTable(stations) {
  const names = new Map(stations.map((station) => [station.station_id, station.station_nom]));
  const tbody = document.getElementById('comparisonRows');
  tbody.replaceChildren();
  const comparisons = stations.flatMap((station) => station.comparaison_chrono.map((phase) => ({
    ...phase,
    station_nom: names.get(station.station_id),
  })));
  const measured = comparisons.filter((phase) => phase.chrono_reel_s != null);
  const rows = measured.length ? measured : comparisons;
  for (const phase of rows) {
    const row = document.createElement('tr');
    row.className = 'comparison-data-row';
    const error = Number(phase.erreur_absolue_pct);
    if (phase.chrono_reel_s == null || !Number.isFinite(error)) {
      row.classList.add(phase.type_auto === 'stop' ? 'comparison-stop' : 'comparison-activity');
    } else if (error <= 10) {
      row.classList.add('comparison-error-low');
    } else if (error <= 25) {
      row.classList.add('comparison-error-medium');
    } else {
      row.classList.add('comparison-error-high');
    }
    row.dataset.phaseNumber = String(phase.ordre);
    row.dataset.searchText = normalizeSearchText([
      phase.station_nom,
      phase.ordre,
      phase.description,
    ].join(' '));
    row.append(
      makeCell(phase.station_nom),
      makeCell(String(phase.ordre)),
      makeCell(phase.description),
      makeCell(seconds(phase.duree_estimee_s)),
      makeCell(seconds(phase.chrono_reel_s)),
      makeCell(seconds(phase.ecart_absolu_s)),
      makeCell(percent(phase.erreur_absolue_pct)),
    );
    tbody.appendChild(row);
  }
  if (!rows.length) {
    const row = document.createElement('tr');
    row.appendChild(makeCell('Aucune phase enregistrée pour ce projet.'));
    tbody.appendChild(row);
  } else if (!measured.length) {
    const row = document.createElement('tr');
    row.className = 'comparison-note-row';
    row.appendChild(makeCell('Aucun chrono réel positif saisi ; renseignez les chronos dans l’écran de revue.'));
    tbody.insertBefore(row, tbody.firstChild);
  }
  filterComparisonTable();
}

function normalizeSearchText(value) {
  return String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('fr');
}

function filterComparisonTable() {
  const query = normalizeSearchText(document.getElementById('comparisonSearch').value.trim());
  const numberQuery = query.match(/^#?(\d+)$/);
  const rows = [...document.querySelectorAll('#comparisonRows tr.comparison-data-row')];
  document.querySelector('#comparisonRows tr.comparison-empty-row')?.remove();
  let visibleCount = 0;
  for (const row of rows) {
    const matches = !query
      || (numberQuery && row.dataset.phaseNumber === numberQuery[1])
      || (!numberQuery && row.dataset.searchText.includes(query));
    row.hidden = !matches;
    if (matches) visibleCount += 1;
  }
  if (rows.length && !visibleCount) {
    const emptyRow = document.createElement('tr');
    emptyRow.className = 'comparison-empty-row';
    const emptyCell = makeCell('Aucun résultat pour cette recherche.');
    emptyCell.colSpan = 7;
    emptyRow.appendChild(emptyCell);
    document.getElementById('comparisonRows').appendChild(emptyRow);
  }
  const count = document.getElementById('comparisonCount');
  count.textContent = query
    ? `${visibleCount} / ${rows.length} phase${rows.length === 1 ? '' : 's'}`
    : `${rows.length} phase${rows.length === 1 ? '' : 's'}`;
}

function drawYamazumi(data) {
  const canvas = document.getElementById('yamazumi');
  const stations = data.stations;
  const dpr = window.devicePixelRatio || 1;
  const displayWidth = Math.max(canvas.parentElement.clientWidth, 640);
  const height = 360;
  canvas.style.width = `${displayWidth}px`;
  canvas.style.height = `${height}px`;
  canvas.width = displayWidth * dpr;
  canvas.height = height * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, displayWidth, height);

  if (!stations.length) {
    ctx.fillStyle = '#5d6470';
    ctx.font = '16px Segoe UI, Arial';
    ctx.fillText('Aucun poste à représenter.', 24, 42);
    return;
  }

  const margin = { left: 58, right: 28, top: 30, bottom: 78 };
  const chartWidth = displayWidth - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;
  const maximum = Math.max(
    Number(data.project.takt_s),
    ...stations.map((station) => station.temps_cycle),
    1,
  ) * 1.12;
  const y = (value) => margin.top + chartHeight - (value / maximum) * chartHeight;
  const tickCount = 5;

  ctx.font = '12px Segoe UI, Arial';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  ctx.strokeStyle = '#e3e9f1';
  ctx.fillStyle = '#5d6470';
  for (let index = 0; index <= tickCount; index += 1) {
    const value = (maximum / tickCount) * index;
    const yPosition = y(value);
    ctx.beginPath();
    ctx.moveTo(margin.left, yPosition);
    ctx.lineTo(displayWidth - margin.right, yPosition);
    ctx.stroke();
    ctx.fillText(value.toFixed(0), margin.left - 10, yPosition);
  }

  const slotWidth = chartWidth / stations.length;
  const barWidth = Math.min(72, slotWidth * 0.58);
  stations.forEach((station, index) => {
    const x = margin.left + slotWidth * index + (slotWidth - barWidth) / 2;
    let bottom = margin.top + chartHeight;
    for (const category of categories) {
      const value = Number(station[category] || 0);
      const segmentHeight = (value / maximum) * chartHeight;
      if (segmentHeight > 0) {
        ctx.fillStyle = colors[category];
        ctx.fillRect(x, bottom - segmentHeight, barWidth, segmentHeight);
        bottom -= segmentHeight;
      }
    }
    ctx.fillStyle = '#202630';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(station.station_nom.slice(0, 16), x + barWidth / 2, margin.top + chartHeight + 10);
    ctx.fillStyle = '#5d6470';
    ctx.fillText(`${station.temps_cycle.toFixed(1)} s`, x + barWidth / 2, margin.top + chartHeight + 28);
  });

  const taktY = y(Number(data.project.takt_s));
  ctx.beginPath();
  ctx.setLineDash([7, 5]);
  ctx.strokeStyle = '#202630';
  ctx.lineWidth = 2;
  ctx.moveTo(margin.left, taktY);
  ctx.lineTo(displayWidth - margin.right, taktY);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.textAlign = 'left';
  ctx.textBaseline = 'bottom';
  ctx.fillStyle = '#202630';
  ctx.fillText(`Takt ${Number(data.project.takt_s).toFixed(1)} s`, margin.left + 5, taktY - 4);

  let legendX = margin.left;
  const legendY = height - 16;
  ctx.font = '11px Segoe UI, Arial';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  for (const category of categories) {
    ctx.fillStyle = colors[category];
    ctx.fillRect(legendX, legendY - 5, 10, 10);
    ctx.fillStyle = '#404752';
    ctx.fillText(category, legendX + 15, legendY);
    legendX += ctx.measureText(category).width + 34;
  }
}

async function loadSummary() {
  const response = await fetch(`/api/projects/${projectId}/summary`);
  if (!response.ok) {
    throw new Error(`Chargement de la synthèse impossible (${response.status}).`);
  }
  summaryData = await response.json();
  document.getElementById('projectTitle').textContent = `Synthèse — ${summaryData.project.nom}`;
  document.getElementById('taktInput').value = Number(summaryData.project.takt_s);
  renderNextStep(summaryData);
  renderMetrics(summaryData);
  renderStationTable(summaryData.stations);
  renderCycleTable(summaryData.stations);
  renderComparisonTable(summaryData.stations);
  drawYamazumi(summaryData);
}

document.getElementById('taktForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const input = document.getElementById('taktInput');
  const button = document.getElementById('saveTakt');
  const status = document.getElementById('taktStatus');
  const takt = Number(input.value);
  if (!Number.isFinite(takt) || takt <= 0) {
    status.textContent = 'Le takt doit être un nombre supérieur à zéro.';
    status.className = 'form-message error';
    return;
  }

  button.disabled = true;
  status.textContent = 'Enregistrement du takt…';
  status.className = 'subtle';
  try {
    const response = await fetch(`/api/projects/${projectId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ takt_s: takt }),
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || `Enregistrement impossible (${response.status}).`);
    }
    await loadSummary();
    status.textContent = 'Takt enregistré. Les indicateurs et le Yamazumi ont été actualisés.';
    status.className = 'form-message';
  } catch (error) {
    console.error(error);
    status.textContent = error.message || 'Erreur lors de l’enregistrement du takt.';
    status.className = 'form-message error';
  } finally {
    button.disabled = false;
  }
});

document.getElementById('exportExcel').addEventListener('click', async () => {
  const button = document.getElementById('exportExcel');
  button.disabled = true;
  try {
    const response = await fetch(`/api/projects/${projectId}/export.xlsx`);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || `Export impossible (${response.status}).`);
    }
    const file = await response.blob();
    const contentDisposition = response.headers.get('content-disposition') || '';
    const encodedFilename = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
    const fallbackFilename = contentDisposition.match(/filename="?([^";]+)"?/i)?.[1];
    const filename = encodedFilename
      ? decodeURIComponent(encodedFilename)
      : fallbackFilename || `kaizen_studio_projet_${projectId}.xlsx`;
    const url = URL.createObjectURL(file);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
    const warning = response.headers.get('x-export-warning');
    if (warning) window.alert(warning);
  } catch (error) {
    console.error(error);
    window.alert(error.message || 'Erreur pendant la création du classeur.');
  } finally {
    button.disabled = false;
  }
});

document.getElementById('comparisonSearch').addEventListener('input', filterComparisonTable);

loadSummary().catch((error) => {
  console.error(error);
  document.getElementById('projectTitle').textContent = 'Erreur de chargement de la synthèse';
});
window.addEventListener('resize', () => {
  if (summaryData) drawYamazumi(summaryData);
});
