"""오늘 뭐 입지? — 날씨·미세먼지 실시간 조회 (Vercel Python 서버리스 함수).

GET /api/weather?lat=..&lon=..  (생략 시 SK남산빌딩)
- 기상청 초단기실황 + 단기예보, 에어코리아 미세먼지 — k-skill-proxy 경유(키 불필요)
표준 라이브러리만 사용.
"""
import json
import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler

PROXY = os.environ.get("KSKILL_PROXY_BASE_URL", "https://k-skill-proxy.nomadamas.org")
KST = timezone(timedelta(hours=9))
DEFAULT = {"name": "SK남산빌딩", "region": "서울 중구", "lat": 37.556619, "lon": 126.975962}
FIELDS = ("TMP", "SKY", "PTY", "POP", "PCP", "SNO", "REH", "WSD")


def _get(path, params, timeout=8):
    url = f"{PROXY}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "weather-outfit/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _items(data):
    return (((data or {}).get("response") or {}).get("body") or {}).get("items", {}).get("item", []) or []


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return v  # "강수없음", "1mm 미만" 등은 문자열 그대로


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def _find_number(obj, keys):
    """응답 구조가 문서화돼 있지 않아, 키 이름으로 숫자 값을 재귀 탐색한다."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower().replace("_", "") in keys:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        for v in obj.values():
            r = _find_number(v, keys)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_number(v, keys)
            if r is not None:
                return r
    return None


def _find_str(obj, keys):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower().replace("_", "") in keys and isinstance(v, str) and v:
                return v
        for v in obj.values():
            r = _find_str(v, keys)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_str(v, keys)
            if r:
                return r
    return None


def region_of(lat, lon):
    data = _get("/v1/kakao-map/coord2region", {"x": lon, "y": lat})
    for d in data.get("documents", []):
        if d.get("region_type") == "B":
            return f"{d.get('region_1depth_name', '')} {d.get('region_2depth_name', '')}".strip()
    return None


def dust(region):
    data = _get("/v1/fine-dust/report", {"regionHint": region})
    if data.get("error") or data.get("ambiguous_location"):
        return None
    pm10 = _find_number(data, {"pm10value", "pm10"})
    pm25 = _find_number(data, {"pm25value", "pm25", "pm2.5"})
    if pm10 is None and pm25 is None:
        return None
    return {
        "pm10": pm10, "pm25": pm25,
        "station": _find_str(data, {"stationname", "station"}),
        "time": _find_str(data, {"datatime", "measuredat", "time"}),
    }


def build(lat, lon, name=None):
    now = datetime.now(KST)
    # 오늘 전체(03시~)와 최저/최고를 담은 02시 발표본 — 02:15 이전이면 전날 23시 발표본
    if now.hour < 2 or (now.hour == 2 and now.minute < 15):
        base_d, base_t = (now - timedelta(days=1)).strftime("%Y%m%d"), "2300"
    else:
        base_d, base_t = now.strftime("%Y%m%d"), "0200"
    loc = {"lat": lat, "lon": lon}

    with ThreadPoolExecutor(max_workers=5) as ex:
        f_now = ex.submit(_safe, lambda: _get("/v1/korea-weather/now", loc))
        f_day = ex.submit(_safe, lambda: _get("/v1/korea-weather/forecast", {**loc, "baseDate": base_d, "baseTime": base_t}))
        f_new = ex.submit(_safe, lambda: _get("/v1/korea-weather/forecast", loc))
        is_default = abs(lat - DEFAULT["lat"]) < 1e-4 and abs(lon - DEFAULT["lon"]) < 1e-4
        region = DEFAULT["region"] if is_default else _safe(lambda: region_of(lat, lon))
        f_dust = ex.submit(_safe, lambda: dust(region)) if region else None

    # 시간별 예보 병합: 02시 발표본 위에 최신 발표본을 덮어쓴다
    days = {}
    for src in (f_day.result(), f_new.result()):
        for it in _items(src):
            d, t, c, v = it["fcstDate"], it["fcstTime"], it["category"], it["fcstValue"]
            day = days.setdefault(d, {"date": d, "tmn": None, "tmx": None, "hours": {}})
            if c == "TMN":
                day["tmn"] = _num(v)
            elif c == "TMX":
                day["tmx"] = _num(v)
            elif c in FIELDS:
                day["hours"].setdefault(t, {"time": t})[c.lower()] = _num(v)

    today = now.strftime("%Y%m%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y%m%d")
    out_days = []
    for d in (today, tomorrow):
        if d not in days:
            continue
        day = days[d]
        hours = [day["hours"][k] for k in sorted(day["hours"])]
        temps = [h["tmp"] for h in hours if isinstance(h.get("tmp"), float)]
        out_days.append({
            "date": d,
            "tmn": day["tmn"] if day["tmn"] is not None else (min(temps) if temps else None),
            "tmx": day["tmx"] if day["tmx"] is not None else (max(temps) if temps else None),
            "hours": hours,
        })

    cur = {i["category"]: _num(i["obsrValue"]) for i in _items(f_now.result())}
    return {
        "location": {"name": name or (DEFAULT["name"] if is_default else region or "내 위치"),
                     "region": region, "lat": lat, "lon": lon},
        "fetchedAt": now.isoformat(timespec="seconds"),
        "now": {"temp": cur.get("T1H"), "reh": cur.get("REH"), "wsd": cur.get("WSD"),
                "pty": cur.get("PTY"), "rn1": cur.get("RN1")} if cur else None,
        "days": out_days,
        "dust": f_dust.result() if f_dust else None,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        try:
            lat = float(qs.get("lat", [DEFAULT["lat"]])[0])
            lon = float(qs.get("lon", [DEFAULT["lon"]])[0])
            if not (33 <= lat <= 39 and 124 <= lon <= 132):
                raise ValueError("대한민국 범위 밖의 좌표입니다")
            data = build(round(lat, 4) if "lat" in qs else lat, round(lon, 4) if "lon" in qs else lon)
            if not data["days"] and not data["now"]:
                raise RuntimeError("기상청 데이터를 가져오지 못했어요")
            body, code = json.dumps(data, ensure_ascii=False).encode(), 200
        except Exception as e:
            body, code = json.dumps({"error": str(e)}, ensure_ascii=False).encode(), 502
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "public, s-maxage=600, stale-while-revalidate=300" if code == 200 else "no-store")
        self.end_headers()
        self.wfile.write(body)
