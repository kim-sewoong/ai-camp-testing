#!/usr/bin/env python3
"""점심메뉴 리서치 — 로컬 실시간 조회 서버 (표준 라이브러리만 사용).

- 후보 식당: 카카오 로컬 API(카테고리 FD6) — k-skill-proxy 경유, 키 불필요
- 리뷰 신호(선택): 네이버 검색 오픈API 블로그 검색 결과 수
  환경변수 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 가 있으면 사용

실행:  python3 server.py   →  http://localhost:8765
"""
import json
import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8765"))
PROXY = os.environ.get("KSKILL_PROXY_BASE_URL", "https://k-skill-proxy.nomadamas.org")
NAVER_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

# 서울 중구 퇴계로 24 SK남산빌딩
ORIGIN = {"name": "SK남산빌딩", "address": "서울 중구 퇴계로 24", "x": 126.975962, "y": 37.556619}
ROOT = os.path.dirname(os.path.abspath(__file__))


def get_json(url, headers=None, timeout=10):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "lunch-research/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


CUISINES = ["한식", "일식", "중식", "양식", "분식", "국밥", "냉면", "돈까스", "쌀국수", "샐러드"]


def _query(path, params, pages=3):
    docs = []
    for page in range(1, pages + 1):
        q = urllib.parse.urlencode({**params, "page": page, "size": 15})
        try:
            data = get_json(f"{PROXY}/v1/kakao-map/search/{path}?{q}")
        except Exception:
            break
        docs += data.get("documents", [])
        if data.get("meta", {}).get("is_end"):
            break
    return docs


def kakao_restaurants(radius):
    """카카오 API는 쿼리당 최대 45곳 → 카테고리 + 메뉴별 키워드 검색을 합쳐 후보를 넓힌다."""
    base = {"category_group_code": "FD6", "x": ORIGIN["x"], "y": ORIGIN["y"], "radius": radius}
    jobs = [("category", {**base, "sort": "distance"})]
    jobs += [("keyword", {**base, "q": kw, "sort": "accuracy"}) for kw in CUISINES]
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(lambda j: _query(*j), jobs))
    if not results[0] and not any(results):
        raise RuntimeError("카카오맵 조회 실패")
    out, seen = [], set()
    for docs in results:
        for d in docs:
            if d["id"] in seen or d.get("category_group_code") != "FD6":
                continue
            seen.add(d["id"])
            out.append(d)
    out.sort(key=lambda d: int(d.get("distance") or 0))
    return out


def naver_blog_count(name):
    q = urllib.parse.urlencode({"query": f"{name} 회현 맛집", "display": 1})
    try:
        data = get_json(
            f"https://openapi.naver.com/v1/search/blog.json?{q}",
            headers={"X-Naver-Client-Id": NAVER_ID, "X-Naver-Client-Secret": NAVER_SECRET},
            timeout=6,
        )
        return int(data.get("total", 0))
    except Exception:
        return None


def build(radius):
    places = kakao_restaurants(radius)
    naver_on = bool(NAVER_ID and NAVER_SECRET)
    counts = {}
    if naver_on:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for p, c in zip(places, ex.map(lambda p: naver_blog_count(p["place_name"]), places)):
                counts[p["id"]] = c

    items = []
    for p in places:
        cats = [c.strip() for c in p.get("category_name", "").split(">")]
        sub = cats[1] if len(cats) > 1 else "기타"
        detail = cats[-1] if len(cats) > 2 else sub
        name = p["place_name"]
        items.append({
            "id": p["id"],
            "name": name,
            "category": sub,
            "detail": detail,
            "distance": int(p.get("distance") or 0),
            "address": p.get("road_address_name") or p.get("address_name"),
            "phone": p.get("phone", ""),
            "x": p["x"], "y": p["y"],
            "blogCount": counts.get(p["id"]),
            "links": {
                "kakaoReview": f"https://place.map.kakao.com/{p['id']}#review",
                "kakaoPlace": f"https://place.map.kakao.com/{p['id']}",
                "naverMap": "https://map.naver.com/p/search/" + urllib.parse.quote(f"{name} 서울 중구"),
                "naverBlog": "https://search.naver.com/search.naver?where=blog&query="
                             + urllib.parse.quote(f"{name} 후기"),
            },
        })
    return {
        "origin": ORIGIN, "radius": radius, "naverEnabled": naver_on,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": items,
    }


MAX_RADIUS = 1000  # 한 번에 1km까지 조회하고, 반경 필터는 페이지에서 처리


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/data.json":  # 로컬 실행 시: 요청할 때마다 실시간 조회
            try:
                body, code = json.dumps(build(MAX_RADIUS), ensure_ascii=False).encode(), 200
            except Exception as e:  # upstream failure
                body, code = json.dumps({"error": str(e)}, ensure_ascii=False).encode(), 502
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if u.path in ("/", ""):
            self.path = "/index.html"
        return super().do_GET()


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--out":  # GitHub Actions: data.json 생성
        data = build(MAX_RADIUS)
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        print(f"{len(data['items'])}곳 저장 → {sys.argv[2]} (네이버 리뷰 신호: {data['naverEnabled']})")
        sys.exit(0 if data["items"] else 1)
    print(f"점심 리서치 서버: http://localhost:{PORT}  (네이버 리뷰 신호: {'ON' if NAVER_ID else 'OFF'})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
