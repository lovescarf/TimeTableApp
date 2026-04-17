# Kartik's Dashboard

Night-glass, single-page Flask dashboard with:
- Login/registration + streak tracking
- SQLite “memory” (tasks + alarms)
- Auto-alarms generated from timetable tasks
- Google Calendar month widget (with dots on event days)
- Gemini chat (via `google-genai`, model `gemini-2.5-flash`)

## Setup

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Set your Gemini API key (recommended):

```bash
setx GEMINI_API_KEY "YOUR_KEY_HERE"
```

Run the app:

```bash
python app.py
```

Open:
- `http://127.0.0.1:5000/`

## Google Calendar

Put your OAuth client in `credentials.json` (already present in this workspace), then click **Connect Google** in the Calendar card.  
If the token expires, the dashboard will prompt you to reconnect.

