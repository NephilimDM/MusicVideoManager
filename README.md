# MUSIC VIDEO MANAGER v1.0
Hybrid Cataloging Software for Music Videos and Concerts

## HOW SCRAPING WORKS

### 1. HYBRID MODE (TMDB First)
The software first searches on TheMovieDB (TMDB).
- **If a Movie/Concert is found**: Downloads official Poster and Fanart.
- **Data Enrichment**:
    a) Searches for the exact date in the filename.
    b) Searches for the Tour name on Setlist.fm.
    c) Downloads the setlist and adds it to the Plot.

### 2. MUSIC VIDEO MODE (Waterfall Fallback)
If TMDB finds nothing, the software assumes it is a Music Video.
Waterfall strategy for data:
- **Step 1**: TheAudioDB (TADB) -> Metadata and Images.
- **Step 2**: Discogs -> Metadata and Album Cover if TADB fails.
- **Step 3**: Fanart.tv -> HD Images if missing.
- **Step 4**: Local Snapshot -> If no image exists, extracts a frame from the video.

## EXTRA FEATURES
- **Manual Editor**: Double-click on a row to edit data, manually search for setlists, or change fanart.
- **Technical Data**: Automatic analysis of resolution, codec, and audio (MediaInfo).
- **Diagnostics**: Green/Red ticks to see what is missing.
- **Multi-language**: Support for English and Italian (configurable in Settings).

## CONFIGURATION
To use the scraping features, you need to configure your API keys.
1. Open the application.
2. Click on the **Settings** button (gear icon).
3. Enter your API keys for:
    - **TMDB** (The Movie Database)
    - **Fanart.tv**
    - **Discogs** (Key + Secret)
    - **TheAudioDB** (Optional, default is "2")
    - **Setlist.fm**
4. Select your preferred **Language** (English or Italian).
5. Click **Save**.

*Note: The configuration is stored locally in `config.json`.*

## REQUIREMENTS & INSTALLATION
- **Files Naming**: Files must be named "Artist - Title". For concerts, including the year or date helps accuracy.

### Running from Source
1. Install Python 3.10+.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the application:
   ```bash
   python main.py
   ```

### Building the Executable
To build a standalone single-file executable:
```bash
python -m PyInstaller build.spec --clean --noconfirm
```
The executable will be created in `dist/MusicVideoManager.exe`.
