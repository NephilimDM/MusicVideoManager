import os
import re


def get_kodi_filename(original_filename):
    """
    Calcola il nome file 'pulito' per Kodi.
    Rimuove l'estensione e i suffissi di stacking (.cd1, .part1) alla fine.
    """
    name_no_ext = os.path.splitext(original_filename)[0]
    # Rimuove cd1/part1 solo se sono alla fine della stringa
    clean_name = re.sub(
        r'(?i)[ ._-]+(cd|dvd|part|disc|pt)[0-9]+$', '', name_no_ext)
    return clean_name.strip()


def fetch_image_data(url):
    """
    Scarica i dati di un'immagine da URL con logica robusta.
    Gestisce User-Agent e retry con Referer per Discogs (403).
    Restituisce i bytes dell'immagine o None se fallisce.
    """
    import requests  # Import locale per evitare dipendenze circolari se necessario

    try:
        # 1. Base Headers
        headers = {"User-Agent": "ConcertManagerApp/1.0"}

        # 2. Primo Tentativo
        response = requests.get(url, headers=headers, timeout=10)

        # 3. Gestione 403 (Discogs)
        if response.status_code == 403:
            print(f"⚠️ 403 Forbidden per {url}, riprovo con Referer...")
            headers["Referer"] = "https://www.discogs.com/"
            response = requests.get(url, headers=headers, timeout=10)

        # 4. Restituisci dati se successo
        if response.status_code == 200:
            return response.content
        else:
            print(f"❌ Errore download {url}: Status {response.status_code}")
            return None

    except Exception as e:
        print(f"❌ Eccezione download {url}: {e}")
        return None


def extract_mediainfo(file_path):
    """
    Estrae i dettagli tecnici (Video/Audio) usando pymediainfo.
    Restituisce un dizionario con i dati o None se fallisce.
    """
    try:
        from pymediainfo import MediaInfo
    except ImportError:
        print("❌ pymediainfo non installato.")
        return None

    if not os.path.exists(file_path):
        return None

    try:
        media_info = MediaInfo.parse(file_path)
        data = {
            "video": {},
            "audio": {}
        }

        for track in media_info.tracks:
            if track.track_type == "Video":
                data["video"] = {
                    "width": track.width,
                    "height": track.height,
                    "aspect": track.display_aspect_ratio,
                    "codec": track.codec_id or track.format,
                    "duration": track.duration  # ms
                }
            elif track.track_type == "Audio" and not data["audio"]:
                # Prendi solo la prima traccia audio
                data["audio"] = {
                    "codec": track.codec_id or track.format,
                    "channels": track.channel_s
                }

        return data
    except Exception as e:
        print(f"❌ Errore MediaInfo per {file_path}: {e}")
        return None
