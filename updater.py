"""
updater.py
----------
FRED Official API'si ile 4 seriyi çekerek data/ klasöründeki CSV'leri günceller.
GitHub Actions tarafından her gece çalıştırılır.
Yerel olarak da çalıştırılabilir: FRED_API_KEY=xxx python updater.py
"""

import json
import pandas as pd
import os
from datetime import datetime, timedelta

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

SERIES = {
    "Brent.csv":    "DCOILBRENTEU",
    "JetFuel.csv":  "DJFUELUSGULF",
    "Diesel.csv":   "DDFUELUSGULF",
    "Gasoline.csv": "DGASUSGULF",
}

# FRED Resmi API — hızlı, güvenilir, IP kısıtlaması yok
FRED_API_URL = (
    "https://api.stlouisfed.org/fred/series/observations"
    "?series_id={series_id}"
    "&observation_start={start_date}"
    "&api_key={api_key}"
    "&file_type=json"
)


def get_api_key() -> str:
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "FRED_API_KEY bulunamadı! "
            "GitHub Secrets'a ekleyin veya lokalde export FRED_API_KEY=xxx yapın."
        )
    return key


def fetch_recent(series_id: str, api_key: str) -> pd.DataFrame:
    """FRED API'si ile son 2 haftanın verisini çeker — çok hızlı."""
    import requests
    start_date = (datetime.utcnow() - timedelta(days=14)).strftime("%Y-%m-%d")
    url = FRED_API_URL.format(
        series_id=series_id,
        start_date=start_date,
        api_key=api_key,
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    rows = [
        {"DATE": obs["date"], series_id: obs["value"]}
        for obs in data.get("observations", [])
        if obs["value"] != "."
    ]
    if not rows:
        raise RuntimeError(f"{series_id} için veri gelmedi.")

    df = pd.DataFrame(rows)
    df["DATE"] = pd.to_datetime(df["DATE"])
    df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
    df = df.dropna().sort_values("DATE").reset_index(drop=True)
    return df


def update_csv(filename: str, series_id: str, api_key: str):
    path = os.path.join(DATA_DIR, filename)
    print(f"[{series_id}] FRED API'sinden son 2 hafta çekiliyor...")

    fresh = fetch_recent(series_id, api_key)
    print(f"  {len(fresh)} satır alındı. Son tarih: {fresh['DATE'].iloc[-1].date()}")

    if not os.path.exists(path):
        fresh["DATE"] = fresh["DATE"].dt.strftime("%Y-%m-%d")
        fresh.to_csv(path, index=False)
        print(f"  Yeni dosya oluşturuldu.")
        return

    existing = pd.read_csv(path)
    existing["DATE"] = pd.to_datetime(existing["DATE"], errors="coerce")
    last_date = existing["DATE"].max()

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
    print("=== FRED Veri Güncelleyici (API) ===\n")
    api_key = get_api_key()
    for filename, series_id in SERIES.items():
        try:
            update_csv(filename, series_id, api_key)
        except Exception as e:
            print(f"  [HATA] {series_id}: {e}")
    write_last_updated()
    print("\nTamamlandı!")
