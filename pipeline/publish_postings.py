#!/usr/bin/env python3
"""추출 결과(JSON)를 검수 후 사이트 데이터(data/postings.js)에 추가한다.

사용법:
    python extract_postings.py inbox/공고.pdf > out.json   # 1) 추출
    python publish_postings.py out.json                    # 2) 미리보기
    python publish_postings.py out.json --write            # 3) 실제 추가
    (이후)  git add -A && git commit -m "공고 추가" && git push

- confidence가 high가 아닌 항목은 ⚠️ 표시 — 분야를 눈으로 확인할 것.
- id는 기존 최대값+1부터 자동 부여, isNew:true로 게시된다.
"""

import json
import re
import sys
from pathlib import Path

DATA = Path(__file__).parent.parent / "data" / "postings.js"

RANK_MAP = {}  # 추출 rank 그대로 사용 (extract_postings.py enum과 사이트가 동기화되어 있음)


def js_str(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def to_entry(p, next_id):
    f_major, f_sub = p["field_path"].split("/", 1)
    parts = [
        f"id:{next_id}",
        f"t:{js_str(p['title'])}",
        f"org:{js_str(p['org'])}",
        f'f:[{js_str(f_major)},{js_str(f_sub)}]',
        f"rank:{js_str(p['rank'])}",
        f"region:{js_str(p.get('region') or '미정')}",
        f"dl:{js_str(p.get('deadline') or '9999-12-31')}",
        f"pay:{js_str(p.get('pay') or '기관 내규')}",
        "sk:[" + ",".join(js_str(s) for s in p.get("required_skills", [])) + "]",
        "pf:[" + ",".join(js_str(s) for s in p.get("preferred_skills", [])) + "]",
    ]
    if p.get("url"):
        parts.append(f"url:{js_str(p['url'])}")
    parts.append("isNew:true")
    return " {" + ", ".join(parts) + "},"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    result = json.loads(Path(sys.argv[1]).read_text())
    postings = result.get("postings", result if isinstance(result, list) else [])

    src = DATA.read_text()
    max_id = max(int(m) for m in re.findall(r"\bid:(\d+)", src))

    lines = []
    for i, p in enumerate(postings):
        flag = "" if p.get("confidence") == "high" else "  ⚠️ 검수 필요(" + p.get("confidence", "?") + ")"
        entry = to_entry(p, max_id + 1 + i)
        print(f"[{p.get('confidence','?'):6}] {p['title']}{flag}")
        print("   " + entry)
        lines.append(entry)

    if "--write" not in sys.argv:
        print(f"\n(미리보기 — 실제 추가하려면 --write)")
        return

    marker = "];"
    idx = src.rindex(marker)
    block = f" /* ↓ 파이프라인 추가 ({result.get('source_title','수동')}) */\n" + "\n".join(lines) + "\n"
    DATA.write_text(src[:idx] + block + src[idx:])
    print(f"\n✅ {len(lines)}건을 data/postings.js에 추가했습니다. git commit & push로 배포하세요.")


if __name__ == "__main__":
    main()
