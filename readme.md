# Packaged build

LUT cache (`.oklab_lut_cache.gz`) is generated after the first color-picker use when running from source. Bundle it so the EXE does not rebuild ~30s of OKLab tables on first launch.

**Faster window startup (recommended — onedir):**

```bat
pyinstaller --onedir --windowed --icon=ico/RH_logo.ico --name "RH1_03" --add-data ".oklab_lut_cache.gz;." main.py
```

**Single-file EXE (slower to open — extracts to a temp dir every launch):**

```bat
pyinstaller --onefile --windowed --icon=ico/RH_logo.ico --name "RH1_03" --add-data ".oklab_lut_cache.gz;." main.py
```

If the cache file is missing, run `python main.py` once (open an OKLab/OKLCH picker), then rebuild.
