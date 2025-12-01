==================================================
MUSIC VIDEO MANAGER v1.0
Software di catalogazione ibrida per Video Musicali e Concerti
==================================================

COME FUNZIONA LO SCRAPING:

1. MODALITÀ IBRIDA (TMDB First)
   Il software cerca prima su TheMovieDB (TMDB).
   - Se trova un Film/Concerto: Scarica Locandina e Fanart ufficiali.
   - Arricchimento Dati:
     a) Cerca la data esatta nel nome file.
     b) Cerca il nome del Tour su Setlist.fm.
     c) Scarica la scaletta e la aggiunge alla Trama.

2. MODALITÀ VIDEOCLIP (Waterfall Fallback)
   Se TMDB non trova nulla, il software assume sia un Video Musicale.
   Strategia a cascata per i dati:
   - Step 1: TheAudioDB (TADB) -> Metadati e Immagini.
   - Step 2: Discogs -> Metadati e Cover Album se TADB fallisce.
   - Step 3: Fanart.tv -> Immagini HD se mancano.
   - Step 4: Snapshot Locale -> Se non esiste nessuna immagine, estrae un frame dal video.

FUNZIONI EXTRA:
- Editor Manuale: Doppio click sulla riga per modificare dati, cercare setlist a mano o cambiare fanart.
- Dati Tecnici: Analisi automatica risoluzione, codec e audio (MediaInfo).
- Diagnostica: Spunte verdi/rosse per vedere cosa manca.

REQUISITI:
- I file devono essere nominati "Artista - Titolo".
- Per i concerti, includere l'anno o la data aiuta la precisione.
