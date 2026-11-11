# 🍱 오늘 점심 뭐 먹지? — SK남산빌딩 점심 리서치

서울 중구 퇴계로 24 SK남산빌딩 기준 반경 1km 식당을 카카오맵에서 조회해, 오늘의 추천 2곳과 전체 목록을 보여줍니다.
각 식당마다 **카카오맵 리뷰 · 네이버지도 리뷰 · 블로그 후기** 링크가 붙어 있습니다.

## 데이터 흐름

- **후보 식당**: 카카오 로컬 API(음식점 카테고리 + 메뉴별 키워드 검색), [k-skill-proxy](https://github.com/NomaDamas/k-skill) 경유
- **리뷰 신호(선택)**: 네이버 검색 오픈API 블로그 검색 결과 수
- **추천 점수**: 리뷰 수 55% + 거리 30% + 오늘의 랜덤 15% (네이버 키가 없으면 거리 40% + 랜덤 60%)
- 카카오·네이버 별점은 공식 API로 제공되지 않아 직접 수집하지 않습니다. 리뷰 링크에서 확인하세요.

## 공개 페이지 (GitHub Pages)

GitHub Actions가 **평일 10:30 · 11:30 · 12:30 (KST)**에 데이터를 새로 조회해 배포합니다.
Actions 탭 → "점심 데이터 갱신 & 배포" → **Run workflow**로 즉시 갱신할 수도 있습니다.

네이버 리뷰 신호를 켜려면 저장소 **Settings → Secrets and variables → Actions**에
`NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`을 추가하세요 ([네이버 개발자센터](https://developers.naver.com/apps)에서 "검색" API 발급).

## 로컬 실행 (요청할 때마다 실시간 조회)

```bash
python3 server.py            # http://localhost:8765
NAVER_CLIENT_ID=… NAVER_CLIENT_SECRET=… python3 server.py   # 네이버 리뷰 신호 포함
```

Python 3 표준 라이브러리만 사용합니다.
