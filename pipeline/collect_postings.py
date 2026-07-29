#!/usr/bin/env python3
"""Treenure 공고 수집기 — 대학 채용 게시판에서 새 공고 링크·PDF를 수집한다.

사용법:
    python collect_postings.py            # 새 링크 탐지 + PDF 다운로드 → inbox/
    python collect_postings.py --list     # 수집 대상 소스 목록 확인

동작:
  1. SOURCES의 각 게시판 페이지를 가져와 채용 관련 링크(채용·초빙·모집 키워드)를 찾는다.
  2. seen_links.json과 비교해 '새로 나타난' 링크만 보고한다.
  3. 링크가 PDF면 inbox/ 폴더에 내려받는다 (HTML 공고는 URL만 보고).
  4. 이후 단계:  python extract_postings.py inbox/파일.pdf > 결과.json
                python publish_postings.py 결과.json   (검수 후 사이트 데이터에 추가)

주의: 수집 대상은 각 기관이 공개한 공고 페이지이며, robots.txt와 요청 간격(2초)을 지킨다.
      게시판 URL·HTML 구조는 기관마다 다르므로 SOURCES를 직접 보강·수정할 것.
"""

import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

BASE = Path(__file__).parent
INBOX = BASE / "inbox"
SEEN = BASE / "seen_links.json"
UA = {"User-Agent": "Mozilla/5.0 (Treenure collector; +https://ckim-test.github.io/treenure/)"}

# 수집 소스 — 각 대학 교원 채용 게시판. ⚠️ URL은 예시이므로 실제 게시판 주소로 확인·교체할 것.
SOURCES = [
    {"org": "KAIST 바이오및뇌공학과", "url": "https://bioeng.kaist.ac.kr/community/notice"},
    {"org": "서울시립대학교",        "url": "https://www.uos.ac.kr/korNotice/list.do?list_id=FA1"},
    {"org": "성균관대학교",          "url": "https://www.skku.edu/skku/about/jobs/faculty.do"},
    {"org": "서울대학교",            "url": "https://www.snu.ac.kr/snunow/notice/faculty"},
    {"org": "연세대학교",            "url": "https://www.yonsei.ac.kr/sc/support/notice.jsp"},
    {"org": "고려대학교",            "url": "https://www.korea.ac.kr/user/boardList.do?boardId=525"},
]

KEYWORDS = re.compile(r"채용|초빙|임용|모집|공채|faculty|recruit", re.I)
LINK_RE = re.compile(r'href=["\']([^"\']+)["\'][^>]*>([^<]{4,120})<', re.I)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")


def collect() -> None:
    INBOX.mkdir(exist_ok=True)
    seen = set(json.loads(SEEN.read_text())) if SEEN.exists() else set()
    found_new = []

    for s in SOURCES:
        try:
            html = fetch(s["url"])
        except Exception as e:
            print(f"[실패] {s['org']}: {e}  ← URL을 실제 게시판 주소로 교체하세요", file=sys.stderr)
            continue
        for href, text in LINK_RE.findall(html):
            if not KEYWORDS.search(text):
                continue
            link = urljoin(s["url"], href)
            if link in seen:
                continue
            seen.add(link)
            found_new.append({"org": s["org"], "title": text.strip(), "url": link})
            if link.lower().endswith(".pdf"):
                try:
                    name = re.sub(r"[^\w가-힣.-]", "_", link.rsplit("/", 1)[-1])[:80]
                    (INBOX / name).write_bytes(
                        urllib.request.urlopen(urllib.request.Request(link, headers=UA), timeout=30).read())
                    found_new[-1]["pdf"] = str(INBOX / name)
                except Exception as e:
                    print(f"  [PDF 다운로드 실패] {link}: {e}", file=sys.stderr)
        time.sleep(2)  # 요청 간격 예의

    SEEN.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=1))
    print(f"\n새 공고 후보 {len(found_new)}건:")
    for f in found_new:
        mark = "📄" if "pdf" in f else "🔗"
        print(f"  {mark} [{f['org']}] {f['title']}\n     {f.get('pdf', f['url'])}")
    if not found_new:
        print("  (없음 — 다음 실행 때 새로 올라온 공고만 표시됩니다)")


if __name__ == "__main__":
    if "--list" in sys.argv:
        for s in SOURCES:
            print(f"  {s['org']}: {s['url']}")
    else:
        collect()
