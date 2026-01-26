"""
Module for handling metadata scraping from various APIs.
"""
from snapshot_utils import SnapshotUtils
from PyQt6.QtCore import QThread, pyqtSignal
import time
import re
import os
import xml.etree.ElementTree as ET
from xml.dom import minidom
from difflib import SequenceMatcher
import unicodedata
import requests
import logging
from config_manager import ConfigManager
from utils import get_kodi_filename, fetch_image_data

logger = logging.getLogger(__name__)


try:
    from pymediainfo import MediaInfo
    MEDIAINFO_AVAILABLE = True
except ImportError:
    MEDIAINFO_AVAILABLE = False

try:
    import wikipediaapi
    WIKIPEDIA_AVAILABLE = True
except ImportError:
    WIKIPEDIA_AVAILABLE = False


class ScrapingWorker(QThread):
    """
    Worker for handling metadata scraping and image downloading in a background thread.
    """
    # Signals
    progress_log = pyqtSignal(str)  # Log messages
    progress_value = pyqtSignal(int)  # Progress bar value
    item_finished = pyqtSignal(int, dict)  # Row index, Metadata
    finished = pyqtSignal()  # Thread finished

    API_IMG_BASE = "https://image.tmdb.org/t/p/original"

    def __init__(self, items):
        """
        Initialize the worker.
        :param items: List of dictionaries/tuples: [{'path': str, 'artist': str, 'title': str, 'row': int}, ...]
        """
        super().__init__()
        self.items = items
        self.tmdb_key = ""
        self.fanart_api_key = ""
        self.discogs_key = ""
        self.discogs_secret = ""
        self.setlistfm_key = ""
        self.tadb_key = ""

    def run(self):
        """Execute the scraping process."""
        # Load keys freshly
        self.tmdb_key = ConfigManager.get("tmdb_key")
        self.fanart_api_key = ConfigManager.get("fanart_key")
        self.discogs_key = ConfigManager.get("discogs_key")
        self.discogs_secret = ConfigManager.get("discogs_secret")
        self.setlistfm_key = ConfigManager.get("setlist_key")
        self.tadb_key = ConfigManager.get("tadb_key", "2")

        count = 0
        for item in self.items:
            path = item['path']
            artist = item['artist']
            title = item['title']
            row = item['row']

            logger.info(f"Processing: {artist} - {title}")
            self.progress_log.emit(f"Processing: {artist} - {title}")

            # Rate limiting
            time.sleep(2.1)

            # Scrape
            metadata = self.scrape_metadata(artist, title, None)

            if metadata:
                # Save NFO
                self.save_nfo(path, metadata)
                # Download Images
                self.download_images(path, metadata)

                # Emit success for this item
                self.item_finished.emit(row, metadata)

            count += 1
            self.progress_value.emit(count)

        self.finished.emit()

    def save_nfo(self, path, metadata):
        """Save the metadata to musicvideo.nfo or [CleanName].nfo."""
        is_folder = os.path.isdir(path)

        # 1. IDENTIFICAZIONE STRUTTURA DISCO
        is_disc = False
        if is_folder:
            for sub in ["VIDEO_TS", "BDMV", "video_ts", "bdmv"]:
                if os.path.exists(os.path.join(path, sub)):
                    is_disc = True
                    break

        # Determine where to save
        if is_disc:
            # CASO A: Struttura Disco -> movie.nfo nella root
            base_path = path
            nfo_name = "movie.nfo"
        else:
            # CASO B: File Singolo o Cartella Generica
            if is_folder:
                base_path = path
                clean_name = os.path.basename(path)
                nfo_name = f"{clean_name}.nfo"
            else:
                base_path = os.path.dirname(path)
                clean_name = get_kodi_filename(os.path.basename(path))
                nfo_name = f"{clean_name}.nfo"

        nfo_path = os.path.join(base_path, nfo_name)

        # Create XML
        root_tag = "movie" if metadata.get("is_concert") else "musicvideo"
        root = ET.Element(root_tag)

        ET.SubElement(root, "title").text = metadata["title"]
        ET.SubElement(root, "artist").text = metadata["artist"]
        ET.SubElement(root, "album").text = metadata["album"]
        ET.SubElement(root, "plot").text = metadata["plot"]
        ET.SubElement(root, "year").text = str(metadata["year"])
        ET.SubElement(root, "director").text = metadata["director"]
        ET.SubElement(root, "genre").text = metadata["genre"]

        # --- VIDEO DETAILS ---
        if not os.path.isdir(path):
            details = self.get_video_details(path)
            if details.get("width", 0) > 0:
                fileinfo = ET.SubElement(root, "fileinfo")
                streamdetails = ET.SubElement(fileinfo, "streamdetails")

                # Video Track
                video = ET.SubElement(streamdetails, "video")
                ET.SubElement(video, "codec").text = str(
                    details.get("video_codec", ""))
                ET.SubElement(video, "width").text = str(
                    details.get("width", 0))
                ET.SubElement(video, "height").text = str(
                    details.get("height", 0))
                ET.SubElement(video, "durationinseconds").text = str(
                    details.get("duration", 0))
                if details.get("hdr"):
                    ET.SubElement(video, "hdr").text = "True"

                # Audio Track
                audio = ET.SubElement(streamdetails, "audio")
                ET.SubElement(audio, "codec").text = str(
                    details.get("audio_codec", ""))
                ET.SubElement(audio, "channels").text = str(
                    details.get("audio_channels", 0))

        # Pretty print
        xml_str = minidom.parseString(
            ET.tostring(root, encoding='utf-8')).toprettyxml(indent="    ")

        try:
            with open(nfo_path, "w", encoding="utf-8") as f:
                f.write(xml_str)
            logger.info(f"Saved NFO to: {nfo_path}")
            self.progress_log.emit(f"Saved NFO to: {nfo_path}")
        except IOError as e:
            logger.error(f"Error saving NFO {nfo_path}: {e}", exc_info=True)
            self.progress_log.emit(f"Error saving NFO {nfo_path}: {e}")

    def download_images(self, path, metadata):
        """Download poster and fanart images."""
        is_folder = os.path.isdir(path)

        # 1. IDENTIFICAZIONE STRUTTURA DISCO
        is_disc = False
        if is_folder:
            for sub in ["VIDEO_TS", "BDMV", "video_ts", "bdmv"]:
                if os.path.exists(os.path.join(path, sub)):
                    is_disc = True
                    break

        if is_disc:
            base_folder = path
            poster_name = "poster.jpg"
            fanart_name = "fanart.jpg"
        else:
            if is_folder:
                base_folder = path
                clean_name = os.path.basename(path)
            else:
                base_folder = os.path.dirname(path)
                clean_name = get_kodi_filename(os.path.basename(path))

            poster_name = f"{clean_name}-poster.jpg"
            fanart_name = f"{clean_name}-fanart.jpg"

        def download(url, filename):
            if not url:
                return
            filepath = os.path.join(base_folder, filename)

            try:
                data = fetch_image_data(url)
                if data:
                    with open(filepath, 'wb') as f:
                        f.write(data)
                    logger.info(f"Saved image: {filepath}")
                    self.progress_log.emit(f"Saved image: {filepath}")
                else:
                    logger.warning(f"Failed to download image: {url}")
                    self.progress_log.emit(f"Failed to download image: {url}")
            except Exception as e:
                logger.error(f"Download error: {e}", exc_info=True)
                self.progress_log.emit(f"Download error: {e}")

        download(metadata["poster_url"], poster_name)

        if metadata["fanart_url"]:
            download(metadata["fanart_url"], fanart_name)
        elif not is_folder:
            fanart_path = os.path.join(base_folder, fanart_name)
            if not os.path.exists(fanart_path):
                SnapshotUtils.extract_frame(path, fanart_path)

    @staticmethod
    def get_video_details(file_path):
        """Extract video and audio details using PyMediaInfo."""
        details = {
            "width": 0, "height": 0, "duration": 0, "video_codec": "", "hdr": False,
            "audio_codec": "", "audio_channels": 0
        }
        if not MEDIAINFO_AVAILABLE:
            return details

        try:
            # SANITIZZAZIONE PERCORSO PER WINDOWS UNC
            parse_path = file_path
            if os.name == 'nt':
                # Se è un percorso di rete (inizia con \\) ma non è già esteso (\\?\)
                if parse_path.startswith(r"\\") and not parse_path.startswith("\\\\?\\"):
                    # Converti \\Server\Share in \\?\UNC\Server\Share
                    parse_path = r"\\?\UNC" + parse_path[1:]

            media_info = MediaInfo.parse(parse_path)
            for track in media_info.tracks:
                if track.track_type == "Video":
                    details["width"] = track.width
                    details["height"] = track.height
                    if track.duration:
                        try:
                            details["duration"] = int(
                                float(track.duration) / 1000)
                        except (ValueError, TypeError):
                            details["duration"] = 0
                    details["video_codec"] = track.format

                    if getattr(track, 'hdr_format', None):
                        details["hdr"] = True
                    elif getattr(track, 'transfer_characteristics', None) and \
                            ("PQ" in track.transfer_characteristics or "HLG" in track.transfer_characteristics):
                        details["hdr"] = True

                elif track.track_type == "Audio" and not details["audio_codec"]:
                    details["audio_codec"] = track.format
                    details["audio_channels"] = track.channel_s

            return details
        except Exception as e:
            import traceback
            logger.critical(
                f"CRITICAL MEDIAINFO ERROR per: {file_path}", exc_info=True)
            return details

    def check_similarity(self, query, result, artist=None):
        """Calculate similarity ratio."""
        if not query or not result:
            return 0.0

        clean_query = re.sub(r'\s*\(.*?\)', '', query).lower().strip()
        clean_result = result.lower().strip()

        if artist:
            artist_lower = artist.lower().strip()
            clean_result = clean_result.replace(artist_lower, "").strip()
            clean_result = re.sub(r'^[\s\-]+', '', clean_result)
            clean_query = clean_query.replace(artist_lower, "").strip()
            clean_query = re.sub(r'^[\s\-]+', '', clean_query)

        if clean_query and clean_result and (clean_query in clean_result or clean_result in clean_query):
            return 1.0

        return SequenceMatcher(None, clean_query, clean_result).ratio()

    def scrape_metadata(self, artist, title, date=None):
        """Orchestrate scraping with Supreme Waterfall strategy."""

        logger.info(f"--- START SCRAPING: '{artist} - {title}' ---")
        self.progress_log.emit(f"Scraping '{title}'...")

        # --- PASSO 1: TMDB SEARCH ---
        logger.info("[STEP 1] Searching on TMDB...")
        if self.tmdb_key:
            tmdb_data = self.fetch_tmdb_data(artist, title)
            if tmdb_data:
                logger.info("✅ SUCCESS TMDB: Found!")
                self.progress_log.emit("Found on TMDB!")

                # Arricchimento Setlist
                setlist_text = None
                if date and re.match(r"\d{4}-\d{2}-\d{2}", date):
                    setlist_text = self.fetch_setlistfm_by_date(artist, date)

                if not setlist_text:
                    clean_title = tmdb_data["title"]
                    for bw in ["Live", "The Movie", "Concert", "Film", "Tour"]:
                        clean_title = clean_title.replace(bw, "").strip()

                    if clean_title:
                        setlist_text = self.fetch_setlistfm_by_tour(
                            artist, clean_title, tmdb_data.get("year"))

                if setlist_text:
                    tmdb_data["plot"] += f"\n\n[SETLIST]\n{setlist_text}"

                logger.info("✅ SCRAPING COMPLETED (TMDB)")
                return tmdb_data
            else:
                logger.info("❌ FAIL TMDB: No result or mismatch.")
        else:
            logger.info("⚠️ SKIP TMDB: Missing API Key.")

        # --- PASSO 2: MUSIC VIDEO FALLBACK ---
        found_metadata = False
        nfo_data = {"is_concert": False, "is_musicvideo": True}
        poster_url = None
        fanart_url = None
        mbid = None
        discogs_data = None

        # 2.1 TADB
        logger.info("[STEP 2] Searching on TheAudioDB...")
        tadb_data = self.fetch_theaudiodb_data(artist, title)
        if tadb_data:
            logger.info("✅ SUCCESS TheAudioDB: Found!")
            self.progress_log.emit("Found on TheAudioDB")
            found_metadata = True
            nfo_data.update(tadb_data)
            poster_url = tadb_data.get("poster_url")
            fanart_url = tadb_data.get("fanart_url")
            mbid = tadb_data.get("mbid")
        else:
            logger.info("❌ FAIL TheAudioDB: No result.")

        # 2.2 Discogs
        if not found_metadata:
            logger.info("[STEP 3] Searching on Discogs...")
            if self.discogs_key and self.discogs_secret:
                discogs_data = self.fetch_discogs_data(artist, title)
                if discogs_data:
                    logger.info("✅ SUCCESS Discogs: Found!")
                    self.progress_log.emit("Found on Discogs")
                    found_metadata = True
                    nfo_data.update(discogs_data)
                    poster_url = discogs_data.get("poster_url")
                else:
                    logger.info("❌ FAIL Discogs: No result.")
            else:
                logger.info("⚠️ SKIP Discogs: Missing API Key.")
        else:
            logger.info("⚠️ SKIP Discogs: Metadata already found on TADB.")

        # 2.3 Fanart.tv
        logger.info("[STEP 4] Enriching from Fanart.tv...")
        if found_metadata and (not poster_url or not fanart_url):
            if mbid and self.fanart_api_key:
                fanart_data = self.fetch_fanart_data(mbid)
                if fanart_data:
                    if not poster_url:
                        poster_url = fanart_data.get("poster_url")
                    if not fanart_url:
                        fanart_url = fanart_data.get("fanart_url")
                    logger.info("✅ Fanart.tv: Images added.")
                else:
                    logger.info("❌ Fanart.tv: No images found.")
            else:
                logger.info("⚠️ SKIP Fanart.tv: Missing MBID or API Key.")
        else:
            logger.info(
                "⚠️ SKIP Fanart.tv: Images already present or missing metadata.")

        # 2.4 Discogs Image Recovery
        logger.info("[STEP 5] Recovering Discogs Images...")
        if found_metadata and not poster_url:
            if not discogs_data and self.discogs_key:
                discogs_data = self.fetch_discogs_data(artist, title)

            if discogs_data and discogs_data.get("poster_url"):
                poster_url = discogs_data.get("poster_url")
                logger.info("✅ Discogs Images: Poster recovered.")
            else:
                logger.info("❌ Discogs Images: No poster found.")
        else:
            logger.info(
                "⚠️ SKIP Discogs Images: Poster already present or missing metadata.")

        if found_metadata:
            nfo_data["poster_url"] = poster_url
            nfo_data["fanart_url"] = fanart_url
            logger.info("✅ SCRAPING COMPLETED (Fallback)")
            return nfo_data
        else:
            self.progress_log.emit(f"No data found for {artist} - {title}")
            logger.warning(
                "⛔ SCRAPING FAILED: No data found in any source.")
            return None

    def _clean_discogs_title(self, title, artist):
        """
        Rimuove il prefisso 'Artist - ' dal titolo se presente, usando normalizzazione e fuzzy matching.
        Gestisce casi come 'Bjork' vs 'Björk'.
        """
        if not title or not artist:
            return title

        # 1. Split by " - "
        parts = title.split(" - ", 1)
        if len(parts) < 2:
            return title

        potential_artist = parts[0].strip()
        real_title = parts[1].strip()

        # 2. Normalize strings (remove accents, lowercase)
        def normalize(s):
            return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn').lower()

        norm_potential = normalize(potential_artist)
        norm_artist = normalize(artist)

        # 3. Check equality or fuzzy match on normalized strings
        if norm_potential == norm_artist:
            return real_title

        ratio = SequenceMatcher(None, norm_potential, norm_artist).ratio()

        # Se la similarità è alta (> 0.75), assumiamo sia l'artista e lo rimuoviamo
        if ratio > 0.75:
            return real_title

        return title

    def fetch_discogs_data(self, artist, title):
        time.sleep(1.1)
        url = "https://api.discogs.com/database/search"
        headers = {
            "User-Agent": "ConcertManagerApp/1.0",
            "Authorization": f"Discogs key={self.discogs_key}, secret={self.discogs_secret}"
        }
        query = f"{artist} {title}"
        params = {"q": query, "type": "release", "per_page": 1}

        try:
            response = requests.get(
                url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data and data.get("results"):
                result = data["results"][0]
                raw_title = result.get("title", title)
                discogs_title = self._clean_discogs_title(raw_title, artist)

                sim_score = self.check_similarity(title, discogs_title, artist)
                if sim_score < 0.7:
                    return None

                year = result.get("year", "")
                genre = result.get("genre", ["Music"])[
                    0] if result.get("genre") else "Music"
                cover_image = result.get(
                    "cover_image", "") or result.get("thumb", "")

                return {
                    "title": discogs_title,
                    "artist": artist,
                    "album": "",
                    "plot": f"Release from Discogs: {discogs_title}",
                    "year": year,
                    "director": "",
                    "genre": genre,
                    "poster_url": cover_image,
                    "fanart_url": "",
                    "mbid": None
                }
        except Exception as e:
            self.progress_log.emit(f"Discogs error: {e}")
        return None

    def fetch_theaudiodb_data(self, artist, title):
        api_key = self.tadb_key
        url = f"https://www.theaudiodb.com/api/v1/json/{api_key}/searchtrack.php"
        params = {"s": artist, "t": title}

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data and data.get("track"):
                track = data["track"][0]
                found_title = track.get("strTrack", "")

                sim_score = self.check_similarity(title, found_title, artist)
                if sim_score < 0.7:
                    return None

                return {
                    "title": found_title,
                    "artist": track.get("strArtist", artist),
                    "album": track.get("strAlbum", ""),
                    "plot": track.get("strDescriptionEN", ""),
                    "year": track.get("intYear") or "",
                    "director": track.get("strMusicVidDirector") or "",
                    "genre": track.get("strGenre", ""),
                    "poster_url": track.get("strAlbumThumb") or "",
                    "fanart_url": track.get("strTrackThumb") or "",
                    "mbid": track.get("strMusicBrainzArtistID")
                }
        except Exception as e:
            self.progress_log.emit(f"TADB error: {e}")
        return None

    def fetch_tmdb_data(self, artist, title):
        query = f"{artist} {title}"
        url = "https://api.themoviedb.org/3/search/movie"
        params = {"api_key": self.tmdb_key,
                  "query": query, "language": "it-IT"}

        try:
            res = requests.get(url, params=params, timeout=10)
            res.raise_for_status()
            data = res.json()

            if data.get("results"):
                movie = data["results"][0]
                found_title = movie.get("title", "")

                sim_score = self.check_similarity(title, found_title, artist)
                if sim_score < 0.7:
                    return None

                poster_path = movie.get("poster_path")
                backdrop_path = movie.get("backdrop_path")
                poster_url = f"{self.API_IMG_BASE}{poster_path}" if poster_path else ""
                fanart_url = f"{self.API_IMG_BASE}{backdrop_path}" if backdrop_path else ""

                return {
                    "is_concert": True,
                    "title": found_title,
                    "artist": artist,
                    "album": "",
                    "plot": movie.get("overview", ""),
                    "year": movie.get("release_date", "").split("-")[0],
                    "director": "",
                    "genre": "Concert",
                    "poster_url": poster_url,
                    "fanart_url": fanart_url,
                    "mbid": None
                }
        except Exception as e:
            self.progress_log.emit(f"TMDB error: {e}")
        return None

    def fetch_setlistfm_by_date(self, artist, date_str):
        if not self.setlistfm_key:
            return None
        try:
            parts = date_str.split("-")
            formatted_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
        except:
            return None

        url = "https://api.setlist.fm/rest/1.0/search/setlists"
        headers = {"x-api-key": self.setlistfm_key,
                   "Accept": "application/json"}
        params = {"artistName": artist, "date": formatted_date}
        return self._execute_setlist_request(url, headers, params)

    def fetch_setlistfm_by_tour(self, artist, tour_name, year=None):
        if not self.setlistfm_key:
            return None
        url = "https://api.setlist.fm/rest/1.0/search/setlists"
        headers = {"x-api-key": self.setlistfm_key,
                   "Accept": "application/json"}
        params = {"artistName": artist, "tourName": tour_name, "p": 1}
        if year:
            params["year"] = year
        return self._execute_setlist_request(url, headers, params)

    def fetch_fanart_data(self, mbid):
        """
        Fetch images from Fanart.tv using MBID.
        Returns a dict with 'poster_url' and 'fanart_url' keys.
        """
        if not self.fanart_api_key:
            return None

        url = f"https://webservice.fanart.tv/v3/music/{mbid}"
        headers = {"api-key": self.fanart_api_key}

        max_retries = 3
        for attempt in range(max_retries):
            try:
                res = requests.get(url, headers=headers, timeout=10)

                if res.status_code == 200:
                    data = res.json()
                    poster_url = ""
                    fanart_url = ""

                    if "musicbanner" in data and data["musicbanner"]:
                        poster_url = data["musicbanner"][0]["url"]
                    elif "artistthumb" in data and data["artistthumb"]:
                        poster_url = data["artistthumb"][0]["url"]

                    if "artistbackground" in data and data["artistbackground"]:
                        fanart_url = data["artistbackground"][0]["url"]

                    return {"poster_url": poster_url, "fanart_url": fanart_url}

                elif res.status_code in [500, 502, 503, 504]:
                    logger.warning(
                        f"Fanart.tv server error {res.status_code}. Retry {attempt + 1}/{max_retries}...")
                    time.sleep(2)
                    continue
                else:
                    res.raise_for_status()

            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(
                        f"Fanart.tv error after {max_retries} attempts: {e}")
                else:
                    logger.warning(
                        f"Fanart.tv connection error: {e}. Retrying...")
                    time.sleep(2)

        return None

    def deep_enrich_data(self, seed_data):
        """
        Arricchisce i dati di base con dettagli da Wikipedia, Setlist.fm e Fanart.tv.
        Input: seed_data (dict)
        Output: enriched_data (dict)
        """
        enriched = seed_data.copy()
        artist = enriched.get("artist", "")
        title = enriched.get("title", "")
        year = enriched.get("year", "")

        if not artist or not title:
            return enriched

        logger.info(f"--- START DEEP ENRICHMENT for: {artist} - {title} ---")

        # 1. DISCOGS ENRICHMENT (Fallback per Anno/Album/Poster)
        if not enriched.get("year") or not enriched.get("album") or not enriched.get("poster_url"):
            logger.info(
                "Incomplete data (Year/Album/Poster), querying Discogs...")
            if self.discogs_key and self.discogs_secret:
                discogs_data = self.fetch_discogs_data(artist, title)
                if discogs_data:
                    if not enriched.get("year") and discogs_data.get("year"):
                        enriched["year"] = discogs_data["year"]
                        logger.info(
                            f"Year recovered from Discogs: {enriched['year']}")

                    if not enriched.get("album") and discogs_data.get("title"):
                        # Usa il titolo della release come album
                        enriched["album"] = discogs_data["title"]
                        logger.info(
                            f"Album recovered from Discogs: {enriched['album']}")

                    if not enriched.get("poster_url") and discogs_data.get("poster_url"):
                        enriched["poster_url"] = discogs_data["poster_url"]
                        logger.info("Poster recovered from Discogs.")
                else:
                    logger.info("Discogs: No data found.")
            else:
                logger.info("⚠️ SKIP Discogs: Missing API Key.")
        else:
            logger.debug("Technical data complete, skipping Discogs.")

        # 2. WIKIPEDIA (Se plot vuoto o corto)
        if WIKIPEDIA_AVAILABLE and (not enriched.get("plot") or len(enriched.get("plot", "")) < 50):
            logger.info("Plot missing or short, querying Wikipedia...")
            try:
                wiki = wikipediaapi.Wikipedia(
                    language='it',
                    user_agent='MusicVideoManager/1.0 (contact: user@example.com)'
                )
                # Tentativi di ricerca
                queries = [
                    f"{artist} {title} (song)",
                    f"{title} (song)",
                    f"{title}"
                ]

                found_plot = False
                for q in queries:
                    logger.debug(
                        f"🔍 WIKI TEST: Searching exact page with title: '{q}'")
                    page = wiki.page(q)
                    if page.exists():
                        logger.info(
                            f"✅ WIKI FOUND: Page '{page.title}' exists (ID: {page.pageid}).")
                        preview = page.summary[:100].replace('\n', ' ')
                        logger.debug(f"📄 WIKI PREVIEW: {preview}...")

                        # Check Disambiguation
                        if "may refer to" in page.summary.lower() or "può riferirsi a" in page.summary.lower():
                            logger.warning(
                                f"⚠️ WIKI DISAMBIGUATION: '{q}' is a disambiguation page. Skipping.")
                            continue

                        summary = page.summary
                        # Controllo base se è musicale (opzionale, ma utile)
                        keywords = ["album", "song", "concerto", "band", "canzone",
                                    "brano", "singolo", "gruppo", "musica", "rock", "pop", "metal", "jazz", "disco", "tour"]
                        if any(k in summary.lower() for k in keywords):
                            enriched["plot"] = summary
                            logger.info(f"Wikipedia plot found for: {q}")
                            self.progress_log.emit(
                                f"Wikipedia plot found for: {q}")
                            found_plot = True
                            break
                        else:
                            logger.warning(
                                f"⚠️ WIKI CONTENT VALIDATION FAILED: Missing keywords in summary for '{q}'.")
                    else:
                        logger.debug(
                            f"❌ WIKI FAIL: Page '{q}' does not exist.")
                if not found_plot:
                    logger.info("Wikipedia: No plot found.")

            except Exception as e:
                self.progress_log.emit(f"Wikipedia error: {e}")
                logger.error(f"Wikipedia error: {e}")
        else:
            logger.debug("Plot already present, skipping Wikipedia.")

        # 3. SETLIST.FM (Se manca scaletta e siamo in contesto concerto)
        is_concert = enriched.get("is_concert", True)
        current_plot = enriched.get("plot", "")

        if is_concert and "[SETLIST]" not in current_plot and "[SCALETTA" not in current_plot:
            setlist_data = None
            # 1. Cerca per data se esiste (es. YYYY-MM-DD)
            full_date = enriched.get("date") or enriched.get("release_date")

            if full_date and re.match(r"\d{4}-\d{2}-\d{2}", str(full_date)):
                setlist_data = self.fetch_setlistfm_by_date(artist, full_date)

            # 2. Fallback su Tour search
            if not setlist_data:
                setlist_data = self.fetch_setlistfm_by_tour(
                    artist, title, year)

            if setlist_data:
                songs = []
                if "sets" in setlist_data and "set" in setlist_data["sets"]:
                    count = 1
                    for s in setlist_data["sets"]["set"]:
                        for song in s["song"]:
                            if song.get("name"):
                                songs.append(f"{count}. {song['name']}")
                                count += 1

                if songs:
                    header = f"\n\n[SCALETTA SETLIST.FM]\n"
                    enriched["plot"] = (enriched.get(
                        "plot") or "") + header + "\n".join(songs)
                    logger.info("Setlist.fm data added.")
                    self.progress_log.emit("Setlist.fm data added.")

        # 4. FANART.TV (Se mancano immagini)
        logger.info("Checking images on Fanart.tv...")
        if not enriched.get("poster_url") or not enriched.get("fanart_url"):
            mbid = enriched.get("mbid")
            if mbid:
                fanart_data = self.fetch_fanart_data(mbid)
                if fanart_data:
                    if not enriched.get("poster_url"):
                        enriched["poster_url"] = fanart_data.get("poster_url")
                    if not enriched.get("fanart_url"):
                        enriched["fanart_url"] = fanart_data.get("fanart_url")
                    logger.info("Fanart.tv images added.")
                    self.progress_log.emit("Fanart.tv images added.")
            else:
                logger.info("Missing MBID, skipping Fanart.tv.")

        logger.info("--- DEEP ENRICHMENT COMPLETED ---")
        return enriched

    def _execute_setlist_request(self, url, headers, params):
        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            if res.status_code == 404:
                return None
            res.raise_for_status()
            data = res.json()
            if data.get("setlist"):
                setlist = data["setlist"][0]
                tour = f"Tour: {setlist['tour']['name']}\n" if "tour" in setlist else ""
                songs = ""
                if "sets" in setlist and "set" in setlist["sets"]:
                    count = 1
                    for s in setlist["sets"]["set"]:
                        for song in s["song"]:
                            songs += f"{count}. {song['name']}\n"
                            count += 1
                return f"{tour}{songs}" if songs else None
        except:
            pass
        return None

    def search_global(self, artist, title):
        """
        Perform a global search across all configured sources.
        Returns a list of candidate dictionaries.
        """
        # 1. Carica chiavi fresche
        self.tmdb_key = ConfigManager.get("tmdb_key")
        self.tadb_key = ConfigManager.get("tadb_key", "2")
        self.discogs_key = ConfigManager.get("discogs_key")
        self.discogs_secret = ConfigManager.get("discogs_secret")

        candidates = []

        # --- 2. TMDB SEARCH ---
        if self.tmdb_key:
            logger.info(
                f"Manual Search: Searching TMDB for '{artist} {title}'...")
            try:
                url = "https://api.themoviedb.org/3/search/movie"
                query = f"{artist} {title}"
                params = {"api_key": self.tmdb_key,
                          "query": query, "language": "it-IT"}

                res = requests.get(url, params=params, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    for item in data.get("results", [])[:5]:
                        poster_path = item.get("poster_path")
                        poster_url = f"{self.API_IMG_BASE}{poster_path}" if poster_path else ""

                        candidates.append({
                            "source": "TMDB",
                            "type": "Concert/Movie",
                            "title": item.get("title"),
                            "year": item.get("release_date", "").split("-")[0],
                            "poster": poster_url,
                            "raw_data": item
                        })
                    logger.info(
                        f"Manual Search: TMDB found {len(data.get('results', [])[:5])} results.")
            except Exception as e:
                logger.error(f"Error searching TMDB: {e}", exc_info=True)

        # --- 3. THEAUDIODB SEARCH ---
        # TADB usa artist e title separati
        if self.tadb_key:
            logger.info(
                f"Manual Search: Searching TheAudioDB for '{artist}' - '{title}'...")
            try:
                url = f"https://www.theaudiodb.com/api/v1/json/{self.tadb_key}/searchtrack.php"
                params = {"s": artist, "t": title}

                res = requests.get(url, params=params, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    if data and data.get("track"):
                        for track in data["track"][:5]:
                            candidates.append({
                                "source": "TADB",
                                "type": "Music Video",
                                "artist": track.get("strArtist"),
                                "title": track.get("strTrack"),
                                "year": track.get("intYear") or "",
                                "poster": track.get("strTrackThumb") or track.get("strAlbumThumb") or "",
                                "raw_data": track
                            })
            except Exception as e:
                logger.error(f"Error searching TADB: {e}", exc_info=True)

        # --- 4. DISCOGS SEARCH ---
        if self.discogs_key and self.discogs_secret:
            logger.info(
                f"Manual Search: Searching Discogs for '{artist} {title}'...")
            try:
                url = "https://api.discogs.com/database/search"
                headers = {
                    "User-Agent": "ConcertManagerApp/1.0",
                    "Authorization": f"Discogs key={self.discogs_key}, secret={self.discogs_secret}"
                }
                query = f"{artist} {title}"
                params = {"q": query, "type": "release", "per_page": 5}

                res = requests.get(url, headers=headers,
                                   params=params, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    for result in data.get("results", []):
                        raw_title = result.get("title")
                        clean_title = self._clean_discogs_title(
                            raw_title, artist)

                        candidates.append({
                            "source": "Discogs",
                            "type": "Release",
                            "title": clean_title,
                            "year": result.get("year", ""),
                            "poster": result.get("cover_image", "") or result.get("thumb", ""),
                            "raw_data": result
                        })
                    logger.info(
                        f"Manual Search: Discogs found {len(data.get('results', []))} results.")
            except Exception as e:
                logger.error(f"Error searching Discogs: {e}", exc_info=True)

        return candidates
