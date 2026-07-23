"""
updater.py
----------
FRED'den 4 seriyi çekerek data/ klasöründeki CSV'leri günceller.
Sadece son 2 haftanın verisi çekilip mevcut CSV'ye eklenir (hızlı).
GitHub Actions tarafından her gece çalıştırılır.
"""

import subprocess
import json
import pandas as pd
import os
from datetime import datetime, timedelta
from io import StringIO

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

SERIES = {
    "Brent.csv":    "DCOILBRENTEU",
    "JetFuel.csv":  "DJFUELUSGULF",
    "Diesel.csv":   "DDFUELUSGULF",
    "Gasoline.csv": "DGASUSGULF",
}

# Sadece son 2 haftanın verisi çekilir — küçük, hızlı
FRED_URL = (
    "https://fred.stlouisfed.org/graph/fredgraph.csv"
    "?id={series_id}&cosd={start_date}&coed={end_date}"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def fetch_recent(series_id: str) -> pd.DataFrame:
    """FRED'den son 2 haftanın verisini çeker (çok hızlı, küçük dosya)."""
    end_date   = datetime.utcnow().strftime("%Y-%m-%d")
    start_date = (datetime.utcnow() - timedelta(days=14)).strftime("%Y-%m-%d")
    url = FRED_URL.format(series_id=series_id, start_date=start_date, end_date=end_date)
    text = None

    # Yöntem 1: requests
    try:
        import requests
        resp = requests.get(url, headers=HEADERS)
        resp.raise_for_status()
        text = resp.text
    except Exception as e:
        print(f"    requests hatası: {e} — curl deneniyor...")

    # Yöntem 2: curl fallback
    if text is None:
        result = subprocess.run(
            ["curl", "-s", "-A", HEADERS["User-Agent"], "-L", url],
            capture_output=True, text=True
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(f"curl hatası: {result.stderr}")
        text = result.stdout

    lines = [l for l in text.strip().split("\n") if "," in l]
    if not lines:
        raise RuntimeError("Boş yanıt alındı")

    df = pd.read_csv(StringIO("\n".join(lines)))
    df.columns = ["DATE", series_id]
    df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
    df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
    df = df.dropna().sort_values("DATE").reset_index(drop=True)
    return df


def update_csv(filename: str, series_id: str):
    path = os.path.join(DATA_DIR, filename)
    print(f"[{series_id}] Son 2 hafta çekiliyor...")

    fresh = fetch_recent(series_id)
    print(f"  FRED'den {len(fresh)} satır alındı. Son tarih: {fresh['DATE'].iloc[-1].date()}")

    if not os.path.exists(path):
        # İlk kurulum: tüm veri yoksa son 2 haftayı yaz
        fresh["DATE"] = fresh["DATE"].dt.strftime("%Y-%m-%d")
        fresh.to_csv(path, index=False)
        print(f"  Yeni dosya oluşturuldu.")
        return

    # Mevcut CSV'yi oku
    existing = pd.read_csv(path)
    existing["DATE"] = pd.to_datetime(existing["DATE"], errors="coerce")
    last_date = existing["DATE"].max()

    # Sadece yeni satırları ekle
    new_rows = fresh[fresh["DATE"] > last_date].copy()
    if new_rows.empty:
        print(f"  Zaten güncel. Son tarih: {last_date.date()}")
        return

    new_rows["DATE"] = new_rows["DATE"].dt.strftime("%Y-%m-%d")
    existing["DATE"] = existing["DATE"].dt.strftime("%Y-%m-%d")
    updated = pd.concat([existing, new_rows], ignore_index=True)
    updated.to_csv(path, index=False)
    print(f"  {len(new_rows)} yeni satır eklendi. Son tarih: {new_rows['DATE'].iloc[-1]}")


def write_last_updated():
    meta_path = os.path.join(DATA_DIR, "meta.json")
    meta = {"last_updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}
    with open(meta_path, "w") as f:
        json.dump(meta, f)
    print(f"\nSon güncelleme damgası yazıldı: {meta['last_updated']}")


if __name__ == "__main__":
    print("=== FRED Veri Güncelleyici ===\n")
    for filename, series_id in SERIES.items():
        try:
            update_csv(filename, series_id)
        except Exception as e:
            print(f"  [HATA] {series_id}: {e}")
    write_last_updated()
    print("\nTamamlandı!")
