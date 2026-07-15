# Shorts Studio

Mini application web complète, en **FastAPI + FFmpeg + Whisper**, pour transformer **vos propres vidéos** en format vertical 9:16 avec sous-titres automatiques.

> Important : ce projet reproduit des **fonctionnalités générales** de génération de shorts, mais **ne copie pas** Cortia ni son code. Utilisez uniquement du contenu dont vous possédez les droits.

## Fonctionnalités

- Upload vidéo depuis le navigateur
- Transcription automatique avec Whisper
- Génération de sous-titres `.srt`
- Conversion verticale 1080x1920 via FFmpeg
- Incrustation de sous-titres dans la vidéo finale
- Découpe automatique du “meilleur moment” selon la densité de parole
- Téléchargement de la vidéo exportée et du fichier SRT
- Narration optionnelle avec Piper TTS si configuré
- Suivi d'avancement en temps réel côté frontend

## Structure

```bash
.
├── app/
│   └── main.py
├── static/
│   ├── app.js
│   └── styles.css
├── templates/
│   └── index.html
├── requirements.txt
└── .gitignore
```

## Prérequis

### 1) Outils système

Installez FFmpeg et Python 3.

```bash
sudo apt update
sudo apt install -y ffmpeg python3 python3-pip python3-venv
```

### 2) Dépendances Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3) Whisper

Whisper est utilisé pour la transcription. Il est déjà listé dans `requirements.txt`.

### 4) Piper TTS (optionnel)

Si vous voulez utiliser le champ “Texte de narration”, installez Piper et définissez un modèle :

```bash
export PIPER_MODEL=/chemin/vers/fr_FR-upmc-medium.onnx
```

Sans cette variable, l'application fonctionne quand même, mais **sans narration IA**.

## Lancement

Depuis la racine du projet :

```bash
uvicorn app.main:app --reload
```

Puis ouvrez :

```bash
http://127.0.0.1:8000
```

## API rapide

### Vérifier l'état du serveur

```bash
GET /health
```

### Vérifier les outils disponibles

```bash
GET /api/tools
```

### Lancer un traitement

```bash
POST /api/process
```

Form-data attendu :

- `video` : fichier vidéo
- `language` : `fr`, `en`, `es`, `pt`, `de`
- `whisper_model` : `tiny`, `base`, `small`, `medium`
- `subtitle_style` : `classic`, `yellow`, `bold`
- `narration_text` : optionnel
- `auto_highlight` : `true/false`, optionnel
- `highlight_duration` : durée cible de l'extrait en secondes, entre `10` et `90`

### Consulter un job

```bash
GET /api/jobs/{job_id}
```

### Télécharger la vidéo finale

```bash
GET /api/jobs/{job_id}/download
```

### Télécharger les sous-titres

```bash
GET /api/jobs/{job_id}/subtitle
```

## Notes importantes

- Le stockage des jobs est **en mémoire** : si le serveur redémarre, l'état des jobs disparaît.
- La découpe automatique du “meilleur moment” repose sur une heuristique simple basée sur les sous-titres générés ; ce n'est pas encore un modèle de scoring viral avancé.
- Le traitement vidéo peut prendre du temps selon la taille du fichier et le modèle Whisper choisi.
- Pour une vraie production, ajoutez ensuite :
  - une base de données
  - une file de jobs (Celery, RQ, Dramatiq)
  - un stockage cloud
  - l'authentification utilisateur
  - des templates de sous-titres plus avancés
  - la découpe automatique des meilleurs passages

## Commandes utiles

### Démarrer le backend

```bash
uvicorn app.main:app --reload
```

### Tester la syntaxe Python

```bash
python3 -m py_compile app/main.py
```

## Idées d'amélioration

- ajouter MoviePy pour des animations de texte
- permettre plusieurs formats d'export
- ajouter une bibliothèque de hooks / intros
- intégrer un planificateur de publication
- proposer plusieurs formats de branding
