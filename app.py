import os
import io
import json
import base64
from flask import Flask, request
import requests
import logging
import google.generativeai as genai # NEU für Gemini

# Konfiguration des Loggings
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Anwendung initialisieren
app = Flask(__name__, static_folder='.', static_url_path='')

# Umgebungsvariable GOOGLE_API_KEY laden (von Render)
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY', 'API_KEY_NOT_SET')
GOOGLE_STT_ENDPOINT = f"https://speech.googleapis.com/v1/speech:recognize?key={GOOGLE_API_KEY}"

# --- NEU: Gemini Konfiguration ---
if GOOGLE_API_KEY != 'API_KEY_NOT_SET':
    genai.configure(api_key=GOOGLE_API_KEY)
    # Wir nutzen das schnelle Flash-Modell für OCR
    vision_model = genai.GenerativeModel('gemini-1.5-flash')
# ---------------------------------

# Prüfen, ob der API-Schlüssel gesetzt ist
API_KEY_VALID = GOOGLE_API_KEY != 'API_KEY_NOT_SET'

# --- FRONTEND (index.html) aus Datei laden ---
@app.route('/')
def index():
    """Lädt und liefert die HTML-Hauptdatei."""
    try:
        # Flask sucht index.html automatisch im `templates`-Ordner, aber für die Einfachheit laden wir sie direkt
        with open('index.html', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return "Fehler: Die Datei index.html wurde nicht gefunden. Bitte stellen Sie sicher, dass sie im Verzeichnis liegt.", 500

@app.route('/health', methods=['GET'])
def health():
    return {"status": "awake"}, 200

# --- BACKEND (Transkription) ---
@app.route('/transcribe', methods=['POST'])
def transcribe_audio():
    """Empfängt Base64-Audio und sendet es an Google Speech-to-Text."""
    if not API_KEY_VALID:
        return {"error": "API-Schlüssel ist nicht gesetzt oder ungültig. Bitte GOOGLE_API_KEY in Render-Umgebungsvariablen setzen."}, 500

    try:
        data = request.get_json()
        audio_base64 = data.get('audio_base64')
        mime_type = data.get('mime_type', 'audio/webm') # Standard auf webm setzen, falls nicht gesendet
        
        if not audio_base64:
            return {"error": "Keine Audiodaten gefunden."}, 400

        # --- DYNAMISCHE ENCODING-KONFIGURATION ---
        
        # Bestimmt das Encoding basierend auf dem vom Browser gemeldeten MimeType
        encoding = "LINEAR16" # Standardwert, wenn nicht spezifiziert
        
        # Wenn der Browser MP4 liefert (häufig bei iOS/Safari), müssen wir MP3 (AAC) explizit setzen,
        # um den "bad encoding" Fehler zu beheben.
        if 'audio/mp4' in mime_type:
            # MP3 ist die beste Annäherung, die Google für das in MP4 enthaltene AAC akzeptiert.
            encoding = "MP3" 
            sample_rate = 44100 # Standard-Sample-Rate für iOS/WebRTC-Aufnahmen
            logger.info(f"Dynamisches Encoding: {mime_type} -> {encoding} mit Rate {sample_rate} Hz.")
        elif 'audio/webm' in mime_type:
            # WebM (Opus) wird von Google besser erkannt, oft ist LINEAR16 oder ENCODING_UNSPECIFIED
            # ausreichend, aber wir verwenden hier die sicherste Methode.
            encoding = "ENCODING_UNSPECIFIED"
            sample_rate = 48000 # Häufigste Sample-Rate für WebM/Opus

        # Konfiguration für Google STT
        config = {
            "encoding": encoding,
            "sampleRateHertz": sample_rate,
            "languageCode": "de-DE", # Wichtig: Deutsche Sprache setzen
            "enableAutomaticPunctuation": True
        }
        
        api_payload = {
            "config": config,
            "audio": {
                "content": audio_base64
            }
        }

        # Sende Anfrage an Google STT
        response = requests.post(
            GOOGLE_STT_ENDPOINT,
            headers={'Content-Type': 'application/json'},
            data=json.dumps(api_payload)
        )
        
        # --- FEHLERBEHANDLUNG ---
        if response.status_code == 200:
            result = response.json()
            # Ergebnis extrahieren
            if result.get('results'):
                transcript = result['results'][0]['alternatives'][0]['transcript']
                return {"transcript": transcript}
            else:
                return {"transcript": "Keine Sprache erkannt oder Transkription nicht möglich."}, 200
        else:
            # Detaillierte Fehlerbehandlung für API-Probleme
            error_details = response.text
            logger.error(f"HTTP-Statusfehler: {error_details}")

            # Versucht, eine menschenlesbare Fehlermeldung aus der Google API zu extrahieren
            try:
                error_json = response.json()
                # Versucht, die spezifische Fehlermeldung von Google zu finden
                google_message = error_json.get('error', {}).get('message', 'Unbekannter API-Fehler.')
            except json.JSONDecodeError:
                google_message = f"Rohfehler ({response.status_code}): {response.text[:100]}..."

            return {"error": f"Google API-Fehler: {google_message}"}, 500

    except Exception as e:
        logger.exception("Unerwarteter Fehler während der Transkription.")
        return {"error": f"Unerwarteter Fehler während der Transkription: {str(e)}"}, 500

# --- NEU: BACKEND (Handschrift-Erkennung / OCR) ---
@app.route('/scan-handwriting', methods=['POST'])
def scan_handwriting():
    """Empfängt eine Bild-URL und extrahiert Text via Gemini AI."""
    if not API_KEY_VALID:
        return {"error": "API-Schlüssel nicht gesetzt."}, 500

    try:
        data = request.get_json()
        image_url = data.get('image_url')
        
        if not image_url:
            return {"error": "Keine Bild-URL gefunden."}, 400

        logger.info(f"Starte Scan für Bild: {image_url}")

        # 1. Bild von Supabase/URL herunterladen
        img_response = requests.get(image_url)
        if img_response.status_code != 200:
            return {"error": "Bild konnte nicht von der URL geladen werden."}, 400

        # 2. Prompt für die KI definieren
        prompt = (
            "Analysiere dieses Bild. Es handelt sich um eine handgeschriebene oder gedruckte Notiz. "
            "Extrahiere den Text und formatiere ihn als kurze, klare To-Do Liste. "
            "Antworte NUR mit dem erkannten Text, keine Einleitung, keine Kommentare."
        )

        # 3. Gemini Vision aufrufen
        # Wir senden das Bild als Byte-Daten an die KI
        response = vision_model.generate_content([
            prompt,
            {"mime_type": "image/jpeg", "data": img_response.content}
        ])

        extracted_text = response.text.strip()
        logger.info("KI-Scan erfolgreich abgeschlossen.")

        return {"text": extracted_text}

    except Exception as e:
        logger.exception("Fehler beim KI-Scan.")
        return {"error": f"KI-Fehler: {str(e)}"}, 500

if __name__ == '__main__':
    # Nur für die lokale Entwicklung, Render verwendet Gunicorn
    app.run(debug=True)