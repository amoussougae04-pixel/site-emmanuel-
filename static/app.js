const form = document.getElementById('process-form');
const submitBtn = document.getElementById('submit-btn');
const toolsList = document.getElementById('tools-list');
const statusCard = document.getElementById('status-card');
const statusStep = document.getElementById('status-step');
const statusError = document.getElementById('status-error');
const progressBarFill = document.getElementById('progress-bar-fill');
const resultActions = document.getElementById('result-actions');
const downloadVideo = document.getElementById('download-video');
const downloadSubtitle = document.getElementById('download-subtitle');
const highlightInfo = document.getElementById('highlight-info');
const autoHighlight = document.getElementById('auto_highlight');
const highlightDuration = document.getElementById('highlight_duration');

let pollTimer = null;

async function loadTools() {
  try {
    const response = await fetch('/api/tools');
    const data = await response.json();
    const labels = {
      ffmpeg: 'FFmpeg',
      ffprobe: 'ffprobe',
      whisper: 'Whisper',
      piper: 'Piper TTS (optionnel)',
    };

    toolsList.innerHTML = Object.entries(labels)
      .map(([key, label]) => {
        const ok = Boolean(data[key]);
        return `
          <li>
            <span>${label}</span>
            <span class="tag ${ok ? 'ok' : 'off'}">${ok ? 'OK' : 'Manquant'}</span>
          </li>
        `;
      })
      .join('');
  } catch (error) {
    toolsList.innerHTML = '<li>Impossible de vérifier les dépendances.</li>';
  }
}

function setStatus({ label, step, progress = 0, error = '', state = 'waiting' }) {
  statusCard.className = `status ${state}`;
  statusCard.querySelector('.status-label').textContent = label;
  statusStep.textContent = step;
  progressBarFill.style.width = `${progress}%`;

  if (error) {
    statusError.textContent = error;
    statusError.classList.remove('hidden');
  } else {
    statusError.textContent = '';
    statusError.classList.add('hidden');
  }
}

async function pollJob(jobId) {
  clearTimeout(pollTimer);
  try {
    const response = await fetch(`/api/jobs/${jobId}`);
    const job = await response.json();

    setStatus({
      label: translateStatus(job.status),
      step: job.step || 'Traitement en cours…',
      progress: job.progress || 0,
      error: job.error || '',
      state: job.status,
    });

    if (job.status === 'completed') {
      resultActions.classList.remove('hidden');
      downloadVideo.href = job.output_url;
      downloadSubtitle.href = job.subtitle_url;

      if (job.highlight && job.highlight.enabled) {
        highlightInfo.textContent = `Extrait détecté : ${job.highlight.start}s → ${job.highlight.end}s (durée ${job.highlight.duration}s).`;
        highlightInfo.classList.remove('hidden');
      } else {
        highlightInfo.textContent = '';
        highlightInfo.classList.add('hidden');
      }

      submitBtn.disabled = false;
      submitBtn.textContent = 'Générer une autre vidéo';
      return;
    }

    if (job.status === 'failed') {
      resultActions.classList.add('hidden');
      highlightInfo.textContent = '';
      highlightInfo.classList.add('hidden');
      submitBtn.disabled = false;
      submitBtn.textContent = 'Réessayer';
      return;
    }

    pollTimer = setTimeout(() => pollJob(jobId), 2500);
  } catch (error) {
    setStatus({
      label: 'Erreur',
      step: "Impossible de récupérer l'état du traitement.",
      error: error.message,
      progress: 100,
      state: 'failed',
    });
    submitBtn.disabled = false;
    submitBtn.textContent = 'Réessayer';
  }
}

function translateStatus(status) {
  switch (status) {
    case 'queued':
      return 'Job en file d’attente';
    case 'processing':
      return 'Traitement en cours';
    case 'completed':
      return 'Traitement terminé';
    case 'failed':
      return 'Échec du traitement';
    default:
      return 'En attente';
  }
}

function syncHighlightInputs() {
  highlightDuration.disabled = !autoHighlight.checked;
}

autoHighlight.addEventListener('change', syncHighlightInputs);
syncHighlightInputs();

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  submitBtn.disabled = true;
  submitBtn.textContent = 'Envoi…';
  resultActions.classList.add('hidden');
  highlightInfo.textContent = '';
  highlightInfo.classList.add('hidden');
  setStatus({
    label: 'Envoi du fichier',
    step: 'La vidéo est en cours de transfert vers le serveur…',
    progress: 10,
    state: 'processing',
  });

  const formData = new FormData(form);

  try {
    const response = await fetch('/api/process', {
      method: 'POST',
      body: formData,
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || 'Impossible de lancer le traitement.');
    }

    submitBtn.textContent = 'Traitement…';
    pollJob(data.job_id);
  } catch (error) {
    setStatus({
      label: 'Erreur',
      step: 'Le traitement n’a pas démarré.',
      error: error.message,
      progress: 100,
      state: 'failed',
    });
    submitBtn.disabled = false;
    submitBtn.textContent = 'Réessayer';
  }
});

loadTools();
