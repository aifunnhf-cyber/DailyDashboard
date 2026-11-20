
import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "ivan-hk-brief-9821")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
BUS_STOP_ID = os.environ.get("BUS_STOP_ID", "003706")  # e.g. Tak Long Estate, Muk Hung Street[cite: 1]


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
        eta_json = fetch_json(f"https://rt.data.gov.hk/v2/transport/citybus/eta/CTB/{BUS_STOP_ID}/608")
        etas = [x.get("eta", "")[11:16] for x in eta_json.get("data", []) if x.get("eta")][:3]
        parts.append(f"城巴608 (站 {BUS_STOP_ID}) 未來班次: {', '.join(etas) if etas else '暫無班次'}")
    except Exception as e:
        parts.append(f"城巴608讀取失敗: {e}")

    # 3. Transport Dept special traffic news XML (Scan ALL & prioritize North Point / water main burst)
    try:
        xml_raw = fetch_text("https://resource.data.one.gov.hk/td/en/specialtrafficnews.xml")
        root = ET.fromstring(xml_raw)
        target_keywords = ["電照街", "港運", "丹拿道", "英皇道", "北角", "渣華道", "七姊妹道", "爆水管", "水管爆裂", "水管緊急維修"]
        priority_msgs = []
        general_msgs = []

        for m in root.findall(".//message"):
            txt = (m.findtext("ChinText") or m.findtext("EngText") or "").strip()
            if not txt:
                continue
            short_txt = txt.split("。")[0]
            if any(k in txt for k in target_keywords):
                priority_msgs.append(f"【重點關注】{short_txt}")
            elif len(general_msgs) < 6:
                general_msgs.append(short_txt)

        combined_msgs = priority_msgs + general_msgs
        parts.append(
            "特別交通消息:\n- " + "\n- ".join(combined_msgs)
            if combined_msgs
            else "特別交通消息: 暫無"
        )
    except Exception as e:
        parts.append(f"交通消息讀取失敗: {e}")

    return "\n".join(parts)


def summarize_with_gemini(raw_text: str) -> str:
    prompt = (
        "你是香港通勤簡報助手。請根據以下實時資料，用繁體中文寫出極簡短匯報（最多 5 點，每點一句，總字數 200 字內）："
        "1. 必須最優先列出任何涉及【電照街、港運城、北角、英皇道】的爆水管、水管維修或封路消息；"
        "2. 其次列出天氣警告、停課或城巴608班次異常；若上述地區及交通均無異常，請簡潔寫出即可。\n\n"
        + raw_text
    )

    if not GEMINI_API_KEY:
        return raw_text[:500]

    for model in ["gemini-3.5-flash-lite", "gemini-3.8-flash"]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={urllib.parse.quote(GEMINI_API_KEY)}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                candidates = res.get("candidates", [])
                text = candidates[0]["content"]["parts"][0]["text"].strip() if candidates else ""
                if text:
                    return text
        except Exception as e:
            print(f"Gemini ({model}) fallback triggered: {e}")

    return raw_text[:500]


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
