"""
updater.py
----------
FRED'den 4 seriyi çekerek data/ klasöründeki CSV'leri günceller.
GitHub Actions tarafından her gece çalıştırılır.
Yerel olarak da çalıştırılabilir: python updater.py
"""

import subprocess
import json
import pandas as pd
import os
from datetime import datetime
from io import StringIO

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

SERIES = {
    "Brent.csv":    "DCOILBRENTEU",
    "JetFuel.csv":  "DJFUELUSGULF",
    "Diesel.csv":   "DDFUELUSGULF",
    "Gasoline.csv": "DGASUSGULF",
}

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
HEADERS  = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def fetch_fred(series_id: str) -> pd.DataFrame:
    """FRED'den gunluk seriyi ceker. Once requests, olmazsa curl dener."""
    url = FRED_URL.format(series_id=series_id)
    text = None

    # Yontem 1: requests (cross-platform, hizli)
    try:
        import requests
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        text = resp.text
    except Exception as e:
        print(f"    requests hatasi: {e} — curl deneniyor...")

    # Yontem 2: curl fallback (cache buster ile)
    if text is None:
        result = subprocess.run(
            ["curl", "-s", "-H", "Cache-Control: no-cache", "-A", HEADERS["User-Agent"], "-L", "--max-time", "60", url],
            capture_output=True, text=True, timeout=90
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(f"curl hatasi: {result.stderr}")
        text = result.stdout

    lines = [l for l in text.strip().split("\n") if "," in l]
    df = pd.read_csv(StringIO("\n".join(lines)))
    df.columns = ["DATE", series_id]
    df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
    df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
    df = df.dropna().sort_values("DATE").reset_index(drop=True)
    df = df[df["DATE"] >= "2021-01-01"].reset_index(drop=True)
    return df


def update_csv(filename: str, series_id: str):
    path = os.path.join(DATA_DIR, filename)
    print(f"[{series_id}] FRED'den veri cekiliyor...")
    fresh = fetch_fred(series_id)

    if fresh.empty:
        print(f"  [UYARI] {series_id} verisi bos geldi!")
        return

    fresh_export = fresh.copy()
    fresh_export["DATE"] = fresh_export["DATE"].dt.strftime("%Y-%m-%d")
    fresh_export.to_csv(path, index=False)
    print(f"  Guncellendi. Toplam {len(fresh)} satir. Son tarih: {fresh['DATE'].iloc[-1].date()}")


def write_last_updated():
    meta_path = os.path.join(DATA_DIR, "meta.json")
    meta = {"last_updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}
    with open(meta_path, "w") as f:
        json.dump(meta, f)
    print(f"\nSon guncelleme damgasi yazildi: {meta['last_updated']}")


if __name__ == "__main__":
    print("=== FRED Veri Guncelleyici ===\n")
    for filename, series_id in SERIES.items():
        try:
            update_csv(filename, series_id)
        except Exception as e:
            print(f"  [HATA] {series_id}: {e}")
    write_last_updated()
    print("\nTamamlandi!")
