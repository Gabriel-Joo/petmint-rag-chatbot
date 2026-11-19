<!--
다루는 곳: notebooks/03-2_참조관계_그래프.ipynb, data/rag_context.py, data/hr_preprocess.py
읽은 커밋: 6710b83
-->
> 상태(2026-11-19 코드와 맞춰 봄): ✓ 참조 그래프는 2026-10-13까지 구현, 강아지 446노드와 745엣지, 고양이 408과 686, 인사규정 6과 7(data/graph/*_graph.json. 서빙 그래프 data/graph/v3는 강아지 447과 747, 고양이 409와 688). ✗ 2~3단계 다단계 탐색은 하지 않는다(1단계 조회만). [code:notebooks/03-2_참조관계_그래프.ipynb:168-169] [code:notebooks/03-2_참조관계_그래프.ipynb:177-184] [code:data/hr_preprocess.py:21] [code:data/chunks_v2.py:15-16] [c:12a4e2b] [c:dcdecd9] <!-- 요약: data/review/chunks_graph_summary.md 5절 참조 그래프(기본, v3) -->

### 0. 한 줄 요약

03-1이 해석한 citation을 "어느 청크가 어느 청크를 참조하는가" 그래프로 만든다. 04번이 검색된 청크의 참조 조문을 즉시 가져올 수 있게 하기 위해서다. [code:notebooks/03-2_참조관계_그래프.ipynb:79] [code:data/rag_context.py:61-66]

---

### 1. 최종 설계

#### 1-1. 노드 키

이게 이 문서의 핵심 설계 결정이다.

**3차(최종), 조각 단위**: `section|section_name|article|coverage|paragraph|chunk_index` [code:notebooks/03-2_참조관계_그래프.ipynb:84-85] [code:data/rag_context.py:65-66]

검증 결과 05번 단위 698개와 04번 청크 1,778개 모두 차이 0건. 노드는 149→446개로 늘었지만 정확성이 우선이다. [code:notebooks/03-2_참조관계_그래프.ipynb:62] (2026-10-12 기준) [code:KNOWN_ISSUES.md:103-105] (149는 조 단위 키 때 값, 446은 쪽번호 제거까지 마친 2026-10-12 노트북 출력 값이다. 키를 바꾼 직후 기록은 449다) [code:KNOWN_ISSUES.md:162-168] (지금 레코드를 세면 1,778(928 + 850), 기록(KNOWN_ISSUES.md:105)은 1,779, 왜 다른지 모름) [code:KNOWN_ISSUES.md:105] <!-- 확인 못 함: 검증 원자료는 그때 남지 않음 -->

#### 1-2. 엣지가 담는 정보

```
[ref_num, ref_title, ref_section, ref_section_name, ref_paragraph, ref_sub_ho]
```

`ref_section`이 들어간 이유는 04번에서 발견한 때문이다. 기존 엣지에는 참조 대상의 section이 없어서, 04번이 **검색된 청크의 section을 그대로 써서** 조회했다. 다른 섹션을 참조하는 경우(`cross_section`) 엉뚱한 섹션에서 찾고 있었다. [code:notebooks/03-2_참조관계_그래프.ipynb:71] [code:notebooks/03-2_참조관계_그래프.ipynb:93-99]

`ref_sub_ho`는 03-1의 호/항 구분(4절)을 04번까지 전달하기 위한 필드다. 조회는 항 단위로 하되, 근거 표기에는 "제13조 제1항 제2호"처럼 호까지 쓴다. [code:notebooks/03-2_참조관계_그래프.ipynb:71-72] [code:notebooks/03-2_참조관계_그래프.ipynb:89-91] [docs:02_pipeline/03a_citation.md]

#### 1-3. 그래프에서 제외하는 것

| scope | 제외 이유 |
| --- | --- |
| `not_found` | 가리키는 대상이 없음 [code:notebooks/03-2_참조관계_그래프.ipynb:74-77] |
| `law_not_in_excerpt` | 약관에 수록되지 않은 외부법 [code:notebooks/03-2_참조관계_그래프.ipynb:74-77] |
| `inline_law_*` | 같은 조 본문의 박스에서 직접 추출하므로 이동 불필요. 다만 04번이 못 찾는 경우가 종별 15건 있다. 박스가 다른 조각에 있는 것 6건, 정규식 차이 3건, `inline_law_nearby`(이웃 조의 박스라 04번이 찾지 않는다) 6건 [code:notebooks/03-2_참조관계_그래프.ipynb:74-77] [code:data/rag_context.py:228-232] [code:data/rag_context.py:468-470] <!-- 잰 날짜 모름 --> <!-- 확인 못 함: 15건과 그 갈래 수는 그때 원자료가 남지 않음 --> |
| `self_item` | 같은 항 안의 호, 자기 본문 [code:notebooks/03-2_참조관계_그래프.ipynb:74-77] |
| `self_paragraph_not_found` | 해당 항을 못 찾음, 01번 citation 추출을 고친 뒤 0건 [code:notebooks/03-2_참조관계_그래프.ipynb:74-77] [code:notebooks/03-1_citation_해석.ipynb:266] (2026-10-12 기준) [c:3878691] |
| `excluded_reference` | 준용에서 제외된 조문, 적용되지 않으므로 뺀다 (강아지 17, 고양이 11) [code:notebooks/03-2_참조관계_그래프.ipynb:74-77] [code:notebooks/03-1_citation_해석.ipynb:266] [docs:02_pipeline/03a_citation.md] (2026-10-12 기준) [code:KNOWN_ISSUES.md:170] |

위 scope 외에 **`article_num`이 없는 청크는 출발 노드에서 통째로 빠진다.** 조 번호가 없으면 그래프 키를 만들 수 없기 때문이다. 별표2, 특정질병표, 안내류가 여기 해당한다. [code:notebooks/03-2_참조관계_그래프.ipynb:82-83]

✓ 인사규정도 같은 구조의 그래프를 만든다(`hr_preprocess.py`). 조립 코드는 코퍼스 이름으로만 나뉘고 나머지는 같다. [code:data/hr_preprocess.py:18-21] [code:data/hr_preprocess.py:214] [code:data/rag_context.py:61-66]

---

### 2. 왜 이렇게 했나

#### 2-1. 왜 그래프DB가 아니라 JSON인가

초기에는 Neo4j로 조항 참조 관계를 저장했다. ✓ 이후 JSON 파일로 전환했다. [code:notebooks/03-2_참조관계_그래프.ipynb:175-180]

**전환 이유**:

- 그래프가 작다. 노드 446개, 엣지 745개 수준 [code:notebooks/03-2_참조관계_그래프.ipynb:168] (2026-10-12 기준)
- **조회 패턴이 단순하다**: "이 청크가 참조하는 목록"을 키로 찾는 1단계 조회뿐이다 [code:data/rag_context.py:61-66]
- 컨테이너를 하나 덜 띄워도 되고, 재부팅, 백업 등 운영 부담이 준다

Neo4j가 빛나는 건 "A를 참조하는 B를 참조하는 C"처럼 **다단계 탐색**이 필요할 때인데, 지금 설계는 1단계만 쓴다.

#### 2-2. 노드 단위를 조회하는 쪽에 맞춘 까닭

> 이 과정에서 배운 것: 그래프의 노드 단위는 "데이터의 자연스러운 단위"가 아니라 **"조회하는 쪽의 단위"에 맞춰야 한다**. 04번은 청크 단위로, 05번은 묶음 단위로 조회하는데, 둘 다 조각 단위 키의 합집합으로 표현할 수 있어야 했다. [code:data/rag_context.py:62-64]
> 

---

### 3. 시도했던 것들

#### 3-1. 노드 키 1차, 2차

**1차, 조 단위**: `section|section_name|article|coverage`

문제는 **같은 조의 다른 항이 인용한 조문까지 딸려 왔다**는 것이다. 제1조 4항을 검색했는데 7항이 인용한 제18조가 참조로 붙는 식이다. FAQ 입력 기준으로 보면 참조 본문이 검색 본문의 5.5배(285k자 vs 52k자)까지 부풀었다. [code:notebooks/03-2_참조관계_그래프.ipynb:69-70] (2026-10-12 기준) [code:KNOWN_ISSUES.md:80-82]

**2차, 항 단위**: `... |paragraph_num` 추가

항을 추가했더니 05번(FAQ 생성)에서 단위 22개가 어긋났다. 05번은 여러 레코드를 묶어 하나의 단위로 쓰는데, **한 항이 여러 조각으로 나뉘어 여러 단위에 흩어지면** 각 단위가 다른 단위의 조각이 인용한 조문까지 받았다. [code:data/rag_context.py:62-64] (2026-10-12까지) [code:KNOWN_ISSUES.md:103] <!-- 확인 못 함: 22개는 그때 원자료가 남지 않음 -->

---

### 4. 남은 한계

✗ 참조를 2~3단계까지 따라가는 기능은 넣지 않는다. 필요해지면 그때 재검토한다. 까닭: 조회 패턴이 이 청크가 참조하는 목록을 찾는 1단계 조회뿐이다(2-1절)

---

### 5. 검증 항목

|  | 강아지 | 고양이 | 인사규정 |
| --- | --- | --- | --- |
| 노드 | 446 | 408 | 6 [code:notebooks/03-2_참조관계_그래프.ipynb:168-169] (2026-10-12 기준) [c:dcdecd9] <!-- 요약: data/review/chunks_graph_summary.md 5절 참조 그래프 기본 판 --> |
| 엣지 | 745 | 686 | 7 <!-- 잰 날짜 모름 --> [c:dcdecd9] <!-- 요약: data/review/chunks_graph_summary.md 5절 참조 그래프 기본 판 --> |
