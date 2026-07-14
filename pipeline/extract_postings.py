#!/usr/bin/env python3
"""가지(GAJI) 공고 PDF → 구조화 추출·자동 분류 파이프라인.

사용법:
    export ANTHROPIC_API_KEY=...
    python extract_postings.py 공고문.pdf > postings.json

하나의 PDF에 여러 분야 공고가 섞여 있어도(예: 대학 전임교원 일괄 초빙)
모집단위별로 쪼개서 공고 배열로 반환한다. 분야 분류는 사이트의 트리
택소노미(enum)로 강제되므로 후처리 매핑이 필요 없다.

대량 처리(야간 수집분 일괄 등)는 Batches API로 돌리면 비용이 50% 절감된다 —
아래 extract() 요청 본문을 그대로 requests[].params 로 옮기면 된다.
"""

import base64
import json
import sys
from typing import List, Literal, Optional

import anthropic
from pydantic import BaseModel, Field

# 사이트 트리와 1:1로 일치하는 분야 경로 — 여기 값이 곧 트리 노드다.
FieldPath = Literal[
    "공학/컴퓨터·AI", "공학/전기·전자", "공학/기계·항공", "공학/화학공학·재료", "공학/토목·건축·도시",
    "자연과학/수학·통계", "자연과학/물리학", "자연과학/화학", "자연과학/생명과학", "자연과학/농림·원예",
    "의·약학/의학", "의·약학/약학", "의·약학/간호·보건",
    "사회과학/경영·경제", "사회과학/심리학", "사회과학/사회·행정",
    "인문학/어문학", "인문학/역사·철학",
    "예·체능/디자인", "예·체능/체육",
    "융합·학제간/AI·데이터 융합", "융합·학제간/환경·지속가능", "융합·학제간/바이오헬스 융합",
]

Rank = Literal["교수", "부교수", "조교수", "연구교수", "박사후연구원", "연구원", "강의·겸임", "초빙·객원"]

# 기존 스킬 사전 — 표기 통일을 위해 프롬프트에 제공한다.
# 실서비스에서는 DB의 canonical skill 테이블에서 로드.
CANONICAL_SKILLS = [
    "Python", "R", "Stata", "SPSS", "MATLAB", "SQL", "LaTeX",
    "Deep Learning", "Machine Learning", "NLP", "Computer Vision", "PyTorch",
    "통계이론", "계량경제", "실험설계", "역학", "의학통계", "임상시험",
    "유기합성", "NMR", "세포배양", "CRISPR", "유세포분석",
    "회로설계", "Verilog", "반도체공정", "CAD", "유한요소해석", "CFD", "유체역학",
    "재료합성", "XRD", "전자현미경", "양자컴퓨팅",
    "UX디자인", "Figma", "GIS", "정책분석", "영어강의", "강의경력",
]


class Posting(BaseModel):
    title: str = Field(description="공고 제목. 모집단위·전공을 포함해 한 줄로. 예: '통계학과 조교수 초빙 (베이지안 통계)'")
    org: str = Field(description="채용 기관명 (대학·병원·연구소)")
    field_path: FieldPath = Field(description="분야 분류. 반드시 목록 중 가장 가까운 하나를 고른다.")
    rank: Rank = Field(description="직급. 초빙교수·객원교수는 '초빙·객원', 겸임·시간강사는 '강의·겸임'으로.")
    region: str = Field(description="근무지 시·군 단위. 예: '서울', '수원'")
    deadline: Optional[str] = Field(description="지원 마감일 YYYY-MM-DD. 공고문에 없으면 null. 상대 표현('접수일로부터 2주')은 계산하지 말고 null.")
    pay: Optional[str] = Field(description="보수·대우. 명시가 없으면 null. 예: '본교 내규', '연 5,500만원'")
    required_skills: List[str] = Field(description="필수 지원자격에서 뽑은 스킬·역량 태그. 2~5자 내외 명사구. 기존 스킬 사전의 표기가 있으면 반드시 그 표기를 재사용.")
    preferred_skills: List[str] = Field(description="우대사항에서 뽑은 스킬 태그. 동일한 표기 규칙.")
    confidence: Literal["high", "medium", "low"] = Field(description="분야 분류와 필드 추출 전반의 확신도. 분야가 애매하거나(융합 전공 등) 원문이 불명확하면 medium 이하로.")
    evidence: str = Field(description="분야 분류의 근거가 된 원문 구절을 30자 이내로 인용.")


class Extraction(BaseModel):
    source_title: str = Field(description="PDF 공고문 자체의 제목")
    postings: List[Posting] = Field(description="모집단위(학과×직급)별로 쪼갠 개별 공고 목록")


PROMPT = f"""이 PDF는 대학·연구기관의 채용 공고문입니다. 채용정보 사이트에 등록하기 위해 구조화해 주세요.

규칙:
- 여러 학과·분야를 한꺼번에 모집하는 공고라면 **모집단위별로 하나씩** 쪼개어 postings 배열에 담습니다. 같은 학과에서 직급이 다르면 그것도 별도 항목입니다.
- 스킬 태그는 아래 기존 사전에 있는 표기를 우선 재사용하세요 (표기 통일 목적). 사전에 없는 역량은 새 태그로 만들되 간결한 명사구로:
{", ".join(CANONICAL_SKILLS)}
- 공고문에 명시되지 않은 값은 지어내지 말고 null로 두세요.
- 채용과 무관한 내용(제출서류 안내, 유의사항 등)은 무시합니다."""


def extract(pdf_path: str) -> Extraction:
    with open(pdf_path, "rb") as f:
        pdf_b64 = base64.standard_b64encode(f.read()).decode("utf-8")

    client = anthropic.Anthropic()
    response = client.messages.parse(
        model="claude-opus-4-8",
        max_tokens=16000,
        thinking={"type": "adaptive"},
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_b64,
                    },
                },
                {"type": "text", "text": PROMPT},
            ],
        }],
        output_format=Extraction,
    )
    return response.parsed_output


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("사용법: python extract_postings.py <공고문.pdf>")

    result = extract(sys.argv[1])

    # 검수 큐 분류: high는 자동 게시, 그 외는 관리자 검수로.
    auto = [p for p in result.postings if p.confidence == "high"]
    review = [p for p in result.postings if p.confidence != "high"]
    print(f"[{result.source_title}] 추출 {len(result.postings)}건 "
          f"(자동 게시 {len(auto)} / 검수 대기 {len(review)})", file=sys.stderr)

    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
