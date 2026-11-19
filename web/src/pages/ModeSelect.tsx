import { Fragment, useEffect, useRef, useState, type PointerEvent } from "react";
import type { Mode } from "../api/types";
import domainMp4 from "../assets/characters/domain.mp4";
import domainPng from "../assets/characters/domain.png";
import domainWebm from "../assets/characters/domain.webm";
import generalMp4 from "../assets/characters/general.mp4";
import generalPng from "../assets/characters/general.png";
import generalWebm from "../assets/characters/general.webm";
import hrMp4 from "../assets/characters/hr.mp4";
import hrPng from "../assets/characters/hr.png";
import hrWebm from "../assets/characters/hr.webm";
import { ArchDiagram } from "../components/ArchDiagram";
import { useReducedMotion } from "../hooks/useReducedMotion";
import s from "./ModeSelect.module.css";

// 09 1-2. 캐릭터는 평소 정지 이미지, 카드에 마우스를 올리면 영상(10-6). 파일명은 모드 키(general, hr, domain)
// 배경은 투명하다 — 세 이미지·영상의 배경색이 제각각(253~255)이고 비네팅·발밑 그림자가 있어 어떤 --card 값으로도 다 맞출 수 없었다.
//   png: 배경 투명(RGBA). 영상: webm(VP9, 알파) 먼저, 알파를 못 쓰는 브라우저(Safari)는 mp4 — 배경을 --card 색으로 채운 판이다
/** intro: 대사. 줄마다 한 줄 — 줄바꿈 위치를 정해 둔다 */
interface Character { mode: Mode; still: string; webm: string; mp4: string; intro: string[] }

// 순서: 일반, 업무특화, 사내규정 — 업무특화가 이 서비스의 메인이라 가운데에 둔다
const CHARACTERS: Character[] = [
  { mode: "일반", still: generalPng, webm: generalWebm, mp4: generalMp4, intro: ["무엇이든 물어보세요.", "사내서버에서만 처리됩니다."] },
  { mode: "업무특화", still: domainPng, webm: domainWebm, mp4: domainMp4, intro: ["펫보험 약관은 제 전문이에요.", "근거 조항까지 찾아드릴게요."] },
  { mode: "사내규정", still: hrPng, webm: hrWebm, mp4: hrMp4, intro: ["인사, 복무 규정은 제가 알아요."] },
];

/** 좁은 화면(1023px 이하)인가 — 모드 카드를 세로로 쌓지 않고 한 장씩 넘긴다(CardSlider, 2026-11-12 사용자) */
const NARROW = "(max-width: 1023px)";
function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => window.matchMedia(NARROW).matches);
  useEffect(() => {
    const m = window.matchMedia(NARROW);
    const on = () => setNarrow(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return narrow;
}

/** copy: 지금 보이지 않는 카드(탭 순서 · 화면 읽기에서 뺀다). clickable: 끌기 끝의 클릭이 아닌가(CardSlider) */
function CharacterCard({ c, onSelect, copy = false, clickable }: {
  c: Character; onSelect: (m: Mode) => void; copy?: boolean; clickable?: () => boolean;
}) {
  const reduced = useReducedMotion();
  const video = useRef<HTMLVideoElement>(null);
  const hover = useRef(0); // 들어오고 나갈 때마다 오른다 — 늦게 온 재생 알림이 이미 끝난 호버의 것인지 가린다
  const [playing, setPlaying] = useState(false);
  // 한 번에 하나만 보인다(11번 1-9절). 영상이 투명(webm)이라 겹치면 뒤의 정지 이미지가 비친다 — 숨기는 쪽은 visibility로
  // 렌더에서 뺀다. 둘 다 .frame 안에 같은 크기·위치로 겹쳐 있어 하나를 빼도 자리가 움직이지 않는다
  const showVideo = playing && !reduced;

  const start = () => {
    const token = ++hover.current;
    const v = video.current;
    if (!v) return; // 움직임 줄이기 — 영상 요소가 없다
    v.muted = true;
    v.currentTime = 0;
    v.play().catch(() => {}); // 재생 전에 마우스를 떼면 pause()가 play를 끊는다 — 정상
    // 정지 이미지는 영상의 첫 프레임이 실제로 화면에 그려진 뒤에 치운다. 로드가 늦으면 그동안 정지 이미지가 그대로 남는다
    const reveal = () => { if (hover.current === token) setPlaying(true); };
    v.addEventListener("playing", () => {
      if (hover.current !== token) return;
      if ("requestVideoFrameCallback" in v) v.requestVideoFrameCallback(reveal);
      else reveal();
    }, { once: true });
  };
  const stop = () => {
    hover.current++;
    setPlaying(false);
    const v = video.current;
    if (!v) return;
    v.pause();
    v.currentTime = 0; // 다시 호버하면 시작 자세부터(11번 1-9절)
  };

  return (
    <button className={`raised lift ${s.card}`} onClick={() => (clickable?.() ?? true) && onSelect(c.mode)}
            onMouseEnter={start} onMouseLeave={stop} tabIndex={copy ? -1 : undefined} aria-hidden={copy || undefined}>
      <span className={s.media} aria-hidden>
        <span className={s.frame}>
          <img className={`${s.still} ${showVideo ? s.hidden : ""}`} src={c.still} alt="" draggable={false} />
          {!reduced && (
            <video ref={video} className={`${s.video} ${showVideo ? "" : s.hidden}`}
                   muted playsInline loop preload="auto" disablePictureInPicture>
              <source src={c.webm} type="video/webm" />
              <source src={c.mp4} type="video/mp4" />
            </video>
          )}
        </span>
      </span>
      <span className={s.name}>{c.mode}</span>
      <span className={s.intro}>{c.intro.map((line, i) => <Fragment key={i}>{i > 0 && <br />}{line}</Fragment>)}</span>
    </button>
  );
}

/** 소개 섹션의 캐릭터 — 호버가 아니라 늘 재생(음소거·반복). 움직임 줄이기에서는 정지 이미지.
 *  화면 밖에서는 멈춰 둔다 — 세 영상이 스크롤 아래에서 계속 디코딩하지 않게 */
function LoopVideo({ c }: { c: Character }) {
  const reduced = useReducedMotion();
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const v = video.current;
    if (!v) return;
    v.muted = true; // React는 muted 속성을 DOM에 확실히 적지 않는다 — 자동 재생 허용 조건이라 직접 켠다
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) v.play().catch(() => {});
      else v.pause();
    });
    io.observe(v);
    return () => io.disconnect();
  }, [reduced]);

  return (
    <span className={`raised ${s.introFrame}`} aria-hidden>
      {reduced ? (
        <img className={s.introMedia} src={c.still} alt="" draggable={false} />
      ) : (
        <video ref={video} className={s.introMedia} muted playsInline loop preload="metadata" poster={c.still} disablePictureInPicture>
          <source src={c.webm} type="video/webm" />
          <source src={c.mp4} type="video/mp4" />
        </video>
      )}
    </span>
  );
}

// 소개 글(2026-11-19 새로 씀). docs가 아니라 운영 코드와 운영 설정(ronanlab-infra apps/petmint/app/configmap.yaml)을 보고 썼다.
// 공개 화면이라 서버 주소, 포트, 실제 사람 이름을 넣지 않고, 하지 않는 것을 하는 것처럼 쓰지 않는다.
// 화면 글과 주석 모두 줄표와 가운뎃점을 쓰지 않는다(원고와 같은 기준, 2026-11-19 사용자).

/** 맨 위 한 단락: 무엇을 하는 서비스인가 */
const LEAD = {
  title: "반려동물 보험 상담원 곁에서 약관을 찾아 읽어 주는 챗봇입니다",
  body: [
    "메리츠화재 펫보험 '펫퍼민트'의 강아지, 고양이 약관과 가상 회사의 인사규정을 읽고 답합니다. 상담원이 고객을 고르면 그 고객이 가입한 특약 안에서만 조항을 찾고, 답에 쓴 근거 조항을 옆에 함께 보여 줍니다.",
    "언어 모델과 검색 모델, 약관 데이터는 모두 사내 서버에 있고 바깥 AI 서비스를 부르지 않습니다. 고객과 직원은 시연을 위해 만든 가상 자료입니다.",
  ],
};

/** 모드 소개 글. 말풍선은 캐릭터 말투, 본문과 표는 설명 말투 */
interface Intro { stack: string[]; bubble: string; body: string; spec: [string, string][] }
const INTRO: Record<Mode, Intro> = {
  일반: {
    stack: ["Tri-7B 원본"],
    bubble: "무엇이든 물어보세요. 사내 서버 안에서 답해요.",
    body: "약관을 찾지 않고 원본 언어 모델과 바로 이야기합니다. 최근 3턴의 대화를 함께 넘겨 이어지는 질문도 받습니다.",
    spec: [
      ["모델", "Tri-7B 원본, Q4_K_M 양자화"],
      ["실행", "사내 서버의 Ollama"],
      ["검색", "하지 않음"],
    ],
  },
  업무특화: {
    stack: ["Tri-7B", "LoRA", "검색"],
    bubble: "약관은 외우지 않아요. 매번 찾아서 읽어 드려요.",
    body: "고른 고객과 반려동물의 가입 정보로 검색 범위를 먼저 정하고, 가입한 특약의 조항만 찾습니다. 약관 질문으로 따로 학습한 모델이 그 발췌를 읽고 답합니다. 보험금 계산, 부담보, 가입 나이처럼 틀리면 안 되는 답은 모델이 아니라 코드가 약관 기준으로 냅니다.",
    spec: [
      ["모델", "Tri-7B + LoRA(약관 질문과 답으로 학습)"],
      ["검색", "벡터(KURE-v1)와 키워드(BM25)로 찾고 bge-reranker-v2-m3로 다시 줄 세움"],
      ["약관", "강아지 1,065조각, 고양이 976조각"],
      ["참조", "조문이 부르는 다른 조문을 그래프로 따라가 함께 건넴"],
      ["코드 답", "보험금 계산, 부담보, 가입 나이, 면책 단서, 병명 되묻기"],
    ],
  },
  사내규정: {
    stack: ["Tri-7B 원본", "검색"],
    bubble: "연차든 복무든, 규정에 있는 건 찾아 드려요.",
    body: "업무특화와 같은 검색 길에 가상 회사의 인사규정을 넣었습니다. 앞 질문에 이어진 질문은 모델이 혼자 읽히는 질문으로 다시 쓴 뒤 찾습니다. 로그인한 직원 본인의 남은 연차나 퇴직금은 인사 원장으로 코드가 계산합니다.",
    spec: [
      ["모델", "Tri-7B 원본"],
      ["자료", "인사규정 49조각(가상 회사)"],
      ["본인 질문", "연차 잔여, 퇴직금, 자격수당, 승진 시점"],
    ],
  },
};

/** 모드 소개 한 줄 — 넓은 화면에서는 글·영상 좌우(reverse면 영상·글), 좁은 화면에서는 글 위·영상 아래.
 *  DOM 순서는 늘 글 → 영상이다(읽는 순서 = 쌓이는 순서). 좌우 바꿈은 CSS order로만 한다.
 *  섹션 제목은 캐릭터가 하는 말 — 말풍선 꼬리가 영상(캐릭터) 쪽을 가리킨다 */
function ModeIntro({ c, reverse }: { c: Character; reverse: boolean }) {
  const it = INTRO[c.mode];
  return (
    <section className={`${s.introRow} ${reverse ? s.introReverse : ""}`} aria-labelledby={`intro-${c.mode}`}>
      <div className={s.introText}>
        <p className={s.eyebrow}>{c.mode}</p>
        {/* 모델 구성 — 요소마다 작은 알약 하나, 사이는 + */}
        <ul className={s.stack} aria-label="모델 구성">
          {it.stack.map((x, i) => (
            <Fragment key={x}>
              {i > 0 && <li className={s.stackPlus} aria-hidden>+</li>}
              <li className={s.pill}>{x}</li>
            </Fragment>
          ))}
        </ul>
        <h2 id={`intro-${c.mode}`} className={s.bubble}>{it.bubble}</h2>
        <p className={s.introBody}>{it.body}</p>
        <dl className={s.spec}>
          {it.spec.map(([k, v]) => (
            <div key={k} className={s.specRow}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      </div>
      <div className={s.introVisual}>
        <LoopVideo c={c} />
      </div>
    </section>
  );
}

/** 기술 구성 — 카드에는 제목과 한 줄, 긴 설명은 아래 아코디언에. 카드와 아코디언은 같은 순서다 */
const TECH: { name: string; line: string; detail: string }[] = [
  { name: "사내 전용", line: "생성도 검색도 서버 안에서. 바깥 AI 서비스 호출 없음",
    detail: "답을 쓰는 Tri-7B 두 판(원본, 약관 학습 판)은 Ollama에, 검색에 쓰는 KURE-v1 임베딩과 bge-reranker-v2-m3는 공용 모델 서버에, 약관 조각은 Milvus에 있습니다. 모두 사내 서버 안이라 질문도 약관도 바깥으로 나가지 않습니다." },
  { name: "터널로 접속", line: "바깥으로 포트를 열지 않습니다",
    detail: "서버는 사설망 안에 있습니다. 클러스터 안에 두 벌로 띄운 Cloudflare 터널이 먼저 바깥으로 연결을 걸어 두고, 요청은 그 연결을 타고 클러스터 입구(ingress)를 거쳐 앱에 닿습니다. 그래서 공유기에 포트를 열 일이 없습니다." },
  { name: "로그인과 격리", line: "사번으로 들어오고, 남의 상담은 보이지 않습니다",
    detail: "사번과 비밀번호로 로그인하고, 비밀번호는 argon2id로 바꿔 저장합니다. 5번 틀리면 15분 잠깁니다. 사번이 없는 방문자는 체험 카드를 눌러 가상 직원으로 들어옵니다. 다른 사람의 상담에 들어가려 하면 권한 없음이 아니라 없는 상담으로 답해, 있는지조차 알 수 없게 했습니다." },
  { name: "기록의 재현", line: "지난 상담은 그때 조건 그대로 보입니다",
    detail: "고객 번호만 남기면 나중에 가입 내용이 바뀌었을 때 지난 상담이 지금 기준으로 보입니다. 그래서 턴마다 그 순간의 반려동물과 가입 내용을 함께 남기고, 근거 패널에 보낸 조항도 그대로 남깁니다." },
  { name: "답 스트리밍", line: "첫 글자부터 바로 보입니다",
    detail: "답은 WebSocket으로 쓰이는 대로 흘러 나옵니다. 답이 길어도 다 쓰일 때까지 기다리지 않고 첫 글자부터 읽기 시작할 수 있습니다." },
  { name: "자동 배포", line: "push 한 번으로 운영까지",
    detail: "push하면 Jenkins가 이미지를 빌드해 Harbor에 올리고, 인프라 저장소의 이미지 태그를 바꿉니다. ArgoCD가 그 저장소를 보고 클러스터에 반영합니다. 앱은 두 벌이 서로 다른 노드에서 돌고, 하나씩 바꿔 끼웁니다." },
  { name: "그래픽카드 한 장", line: "16GB 한 장을 모델들이 나눠 씁니다",
    detail: "클러스터는 가상 머신 위에 있고 그래픽카드를 넘겨주지 않습니다. 그래서 그래픽카드를 쓰는 Ollama와 공용 모델 서버, 검색 서버는 호스트에 두고, 앱이 사설망으로 부릅니다." },
  { name: "직접 세운 클러스터", line: "가상 머신 다섯 대, 입구부터 인증서까지",
    detail: "Vagrant로 가상 머신 다섯 대(제어 하나, 작업 넷)를 띄우고 kubeadm으로 묶었습니다. 사설망에는 로드밸런서가 없어 MetalLB로 입구 주소를 만들고, 인증서는 cert-manager가 받아 옵니다. 약관 조각과 참조 그래프는 이미지에 넣지 않고 NFS로 읽기 전용으로 붙입니다." },
];

/** 쓴 기술, 갈래마다 한 줄 */
const TOOLS: [string, string][] = [
  ["화면", "React, TypeScript, Vite"],
  ["서버", "Python, FastAPI, WebSocket"],
  ["언어 모델", "Tri-7B(원본, LoRA 학습 판), Ollama"],
  ["검색", "Milvus, KURE-v1, BM25, bge-reranker-v2-m3"],
  ["데이터베이스", "MySQL"],
  ["인프라", "Kubernetes(kubeadm), Vagrant, MetalLB, cert-manager, NFS"],
  ["배포", "Jenkins, Harbor, ArgoCD, Cloudflare 터널"],
  ["관측", "Prometheus, Grafana, Loki"],
];

/** 기술 구성 — 카드 8장(넓은 화면 4×2) → 구성도 → 아코디언.
 *  아코디언은 <details> — 기본 접힘, 여러 개를 같이 펼칠 수 있고 키보드·스크린리더 동작이 따라온다 */
function TechStack() {
  return (
    <section className={s.tech} aria-labelledby="tech-heading">
      <h2 id="tech-heading" className={s.techHeading}>기술 구성</h2>
      <ul className={s.techGrid}>
        {TECH.map((t) => (
          <li key={t.name} className={`raised ${s.techCard}`}>
            <span className={s.techName}>{t.name}</span>
            <span className={s.techDesc}>{t.line}</span>
          </li>
        ))}
      </ul>
      <ArchDiagram />
      <dl className={`${s.spec} ${s.tools}`} aria-label="쓴 기술">
        {TOOLS.map(([k, v]) => (
          <div key={k} className={s.specRow}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      <div className={s.accordion}>
        {TECH.map((t) => (
          <details key={t.name} className={s.acc}>
            <summary className={s.accSummary}>{t.name}</summary>
            <p className={s.accBody}>{t.detail}</p>
          </details>
        ))}
      </div>
    </section>
  );
}

/** 좁은 화면(1023px 이하) 모드 카드 — 한 장씩(2026-11-12 사용자). 처음엔 업무특화, 양옆 동그란 화살표로 넘기고 손으로 끌어서도 넘긴다.
 *  폭의 20% 넘게 끌면 넘어가고 아니면 제자리. 5px 넘게 끈 클릭은 모드로 들어가지 않는다. 처음 · 끝에서는 그쪽 화살표를 막는다(순환하지 않는다 — 세 장) */
function CardSlider({ onSelect }: { onSelect: (m: Mode) => void }) {
  const [index, setIndex] = useState(1);
  const [dx, setDx] = useState(0);
  const [dragging, setDragging] = useState(false);
  const drag = useRef({ active: false, x: 0, moved: 0, width: 1 });
  const viewport = useRef<HTMLDivElement>(null);
  const last = CHARACTERS.length - 1;
  const go = (i: number) => setIndex(Math.max(0, Math.min(last, i)));

  const onDown = (e: PointerEvent<HTMLDivElement>) => {
    drag.current = { active: true, x: e.clientX, moved: 0, width: viewport.current?.clientWidth || 1 };
  };
  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d.active) return;
    const m = e.clientX - d.x;
    d.moved = Math.max(d.moved, Math.abs(m));
    if (d.moved > 5) {
      if (!e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.setPointerCapture(e.pointerId);
      setDragging(true);
    }
    const edge = (index === 0 && m > 0) || (index === last && m < 0);   // 끝에서는 바깥쪽으로 덜 끌린다(고무줄)
    setDx(edge ? m / 3 : m);
  };
  const onUp = () => {
    const d = drag.current;
    if (!d.active) return;
    d.active = false;
    setDragging(false);
    if (Math.abs(dx) > d.width * 0.2) go(index + (dx < 0 ? 1 : -1));
    setDx(0);
  };

  return (
    <div className={s.slider} role="region" aria-roledescription="carousel" aria-label="모드">
      <button type="button" className={`${s.arrow} ${s.arrowPrev}`} onClick={() => go(index - 1)} disabled={index === 0}
              aria-label="이전 모드"><Chevron dir="left" /></button>
      <div className={s.sliderViewport} ref={viewport} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp}
           onPointerCancel={onUp} onLostPointerCapture={(e) => e.target === e.currentTarget && onUp()}>
        <div className={`${s.sliderTrack} ${dragging ? s.sliderDragging : ""}`}
             style={{ transform: `translate3d(calc(${-index * 100}% + ${dx}px), 0, 0)` }}>
          {CHARACTERS.map((c, i) => (
            <div key={c.mode} className={s.slide} aria-roledescription="slide" aria-label={`${i + 1} / ${CHARACTERS.length}`}>
              <CharacterCard c={c} onSelect={onSelect} copy={i !== index} clickable={() => drag.current.moved <= 5} />
            </div>
          ))}
        </div>
      </div>
      <button type="button" className={`${s.arrow} ${s.arrowNext}`} onClick={() => go(index + 1)} disabled={index === last}
              aria-label="다음 모드"><Chevron dir="right" /></button>
    </div>
  );
}

function Chevron({ dir }: { dir: "left" | "right" }) {
  return (
    <svg viewBox="0 0 24 24" width="1em" height="1em" aria-hidden focusable="false" fill="none" stroke="currentColor"
         strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d={dir === "left" ? "M15 5l-7 7 7 7" : "M9 5l7 7-7 7"} />
    </svg>
  );
}

export function ModeSelect({ onSelect }: { onSelect: (m: Mode) => void }) {
  const narrow = useNarrow();
  return (
    <main className={s.page}>
      <section className={s.hero}>
        <h1 className={s.title}>누구와 이야기할까요?</h1>
        {narrow ? (
          <CardSlider onSelect={onSelect} />
        ) : (
          <div className={s.grid}>
            {CHARACTERS.map((c) => <CharacterCard key={c.mode} c={c} onSelect={onSelect} />)}
          </div>
        )}
      </section>
      {/* 프로젝트 소개 — 스크롤하면 나온다. 모드마다 글·영상을 좌우 번갈아(지그재그), 끝에 기술 구성 */}
      <div className={s.about} aria-label="프로젝트 소개" role="region">
        <section className={s.lead} aria-labelledby="lead-heading">
          <h2 id="lead-heading" className={s.leadTitle}>{LEAD.title}</h2>
          {LEAD.body.map((p, i) => <p key={i} className={s.introBody}>{p}</p>)}
        </section>
        {CHARACTERS.map((c, i) => <ModeIntro key={c.mode} c={c} reverse={i % 2 === 1} />)}
        <TechStack />
      </div>
    </main>
  );
}
