
import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "ivan-hk-brief-9821")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
BUS_STOP_ID = os.environ.get("BUS_STOP_ID", "003301")  # e.g. Muk Chui Street, Kai Tak[cite: 1]


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("utf-8", errors="replace")


def gather_hk_data() -> str:
    parts = []

    # 1. HKO regional weather & active warnings[cite: 1]
    try:
        w = fetch_json("https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=rhrread&lang=tc")
        temps = w.get("temperature", {}).get("data", [])
        kc = next(
            (t for t in temps if any(k in t.get("place", "") for k in ["九龍城", "黃大仙", "觀塘"])),
            temps[0] if temps else {},
        )
        humidity = w.get("humidity", {}).get("data", [{}])[0].get("value", "--")
        warnings = w.get("warningMessage") or ["無特別天氣警告"]
        parts.append(f"天氣: {kc.get('place', '香港')} {kc.get('value', '--')}°C，濕度 {humidity}%；警告: {' / '.join(warnings)}")
    except Exception as e:
        parts.append(f"天氣讀取失敗: {e}")

    # 2. Citybus Route 608 ETA[cite: 1]
    try:
        eta_json = fetch_json(f"https://rt.data.gov.hk/v1/transport/citybus-nwfb/eta/CTB/{BUS_STOP_ID}/608")
        etas = [x.get("eta", "")[11:16] for x in eta_json.get("data", []) if x.get("eta")][:3]
        parts.append(f"城巴608 (站 {BUS_STOP_ID}) 未來班次: {', '.join(etas) if etas else '暫無班次'}")
    except Exception as e:
        parts.append(f"城巴608讀取失敗: {e}")

    # 3. Transport Dept special traffic news XML[cite: 2]
    try:
        xml_raw = fetch_text("https://resource.data.one.gov.hk/td/en/specialtrafficnews.xml")
        root = ET.fromstring(xml_raw)
        msgs = []
        for m in root.findall(".//message")[:12]:
            txt = (m.findtext("ChinText") or m.findtext("EngText") or "").strip()
            if txt:
                msgs.append(txt.split("。")[0])
        parts.append("特別交通消息:\n- " + "\n- ".join(msgs[:6]) if msgs else "特別交通消息: 暫無")
    except Exception as e:
        parts.append(f"交通消息讀取失敗: {e}")

    return "\n".join(parts)


def summarize_with_gemini(raw_text: str) -> str:
    prompt = (
        "你是香港通勤簡報助手。請根據以下實時資料，用繁體中文寫出極簡短匯報（最多 5 點，每點一句，總字數 180 字內）："
        "重點列出天氣警告、停課/交通異常或重要班次；若無異常就簡潔寫出。\n\n"
        + raw_text
    )

    if not GEMINI_API_KEY:
        return raw_text[:500]

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={urllib.parse.quote(GEMINI_API_KEY)}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        candidates = res.get("candidates", [])
        text = candidates[0]["content"]["parts"][0]["text"].strip() if candidates else ""
        return text or raw_text[:500]


def send_ntfy(message: str) -> None:
    url = f"https://ntfy.sh/{urllib.parse.quote(NTFY_TOPIC)}"
    req = urllib.request.Request(
        url,
        data=message.encode("utf-8"),
        headers={
            "Title": "HK Commute & Weather Brief",
            "Tags": "partly_sunny,bus",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


if __name__ == "__main__":
    summary = summarize_with_gemini(gather_hk_data())
    send_ntfy(summary)
    print("Sent:\n", summary)
