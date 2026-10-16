import { Fragment, useEffect, useRef, useState } from "react";
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

// 09 2-1. 캐릭터는 평소 정지 이미지, 카드에 마우스를 올리면 영상(10-6). 파일명은 모드 키(general, hr, domain)
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

function CharacterCard({ c, onSelect }: { c: Character; onSelect: (m: Mode) => void }) {
  const reduced = useReducedMotion();
  const video = useRef<HTMLVideoElement>(null);
  const hover = useRef(0); // 들어오고 나갈 때마다 오른다 — 늦게 온 재생 알림이 이미 끝난 호버의 것인지 가린다
  const [playing, setPlaying] = useState(false);
  // 한 번에 하나만 보인다(11번 9절). 영상이 투명(webm)이라 겹치면 뒤의 정지 이미지가 비친다 — 숨기는 쪽은 visibility로
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
    v.currentTime = 0; // 다시 호버하면 시작 자세부터(11번 9절)
  };

  return (
    <button className={`raised lift ${s.card}`} onClick={() => onSelect(c.mode)} onMouseEnter={start} onMouseLeave={stop}>
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

/** 모드 소개 글 — 말풍선은 캐릭터 말투, 본문·표는 설명 말투 */
interface Intro { bubble: string; body: string; spec: [string, string][] }
const INTRO: Record<Mode, Intro> = {
  일반: {
    bubble: "외부로는 한 글자도 안 나가요.",
    body: "Tri-7B를 사내 서버에 직접 올려 씁니다. 질문도 답변도 네트워크를 벗어나지 않습니다. 임베딩과 생성 모두 로컬 모델이라 외부 API 호출이 0건입니다.",
    spec: [
      ["모델", "Tri-7B (7.5B, Apache 2.0)"],
      ["양자화", "Q4_K_M — GGUF 변환 후 Ollama 등록"],
      ["임베딩", "KURE-v1 (한국어 특화, MIT)"],
    ],
  },
  업무특화: {
    bubble: "약관은 제가 외우지 않아요. 매번 찾아서 읽어드려요.",
    body: "사실은 모델이 기억하지 않습니다. 검색이 매번 약관에서 찾아 건네고, 모델은 그것을 읽어 상담 말투로 정리합니다. 근거 조항은 코드가 조립합니다 — 모델이 쓰면 없는 조항을 지어낼 수 있기 때문입니다.",
    spec: [
      ["청킹", "항(項) 단위 — 강아지 1,008건 / 고양이 914건"],
      ["검색", "Hybrid(BM25 + Dense) + bge-reranker-v2-m3"],
      ["그래프", "조항 참조 관계 — \"제6항만 참조\" 같은 인용까지 추적"],
      ["필터", "등급·유형을 UI에서 확정해 검색 범위를 고정"],
      ["계산", "지급액은 코드가 — 프롬프트에 넣었더니 오류가 16% → 21%로 올랐습니다"],
    ],
  },
  사내규정: {
    bubble: "연차든 복무든, 규정에 있는 건 제가 알아요.",
    body: "같은 파이프라인에 자료만 바꿔 태웠습니다. 코퍼스가 늘어도 구조는 그대로입니다.",
    spec: [
      ["전처리", "인사규정 원문 → 청크 49개, 참조 그래프 7엣지"],
      ["회귀", "24문항"],
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
  { name: "사내 전용", line: "모델도 임베딩도 서버 안에서. 외부 API 호출 0건",
    detail: "생성은 Ollama 에 올린 Tri-7B 가, 검색은 KURE 임베딩과 bge-reranker 가 맡습니다. 넷 다 서버 안에 있어 질문도 약관도 네트워크를 벗어나지 않습니다. 학습 데이터를 만들 때도 외부 API 를 쓰지 않았습니다." },
  { name: "외부 접속", line: "포트를 열지 않고 도메인으로. 로그인은 앱 앞에서",
    detail: "서버는 사설망 안에 있습니다. Cloudflare Tunnel 이 바깥으로 연결을 걸어 나가는 방식이라 공유기에 포트를 뚫을 일이 없습니다. 도메인 앞에는 Access 가 서서, 로그인하지 않은 요청은 앱에 닿기도 전에 돌려보냅니다." },
  { name: "동시 접속", line: "여럿이 동시에 물어도 수신이 막히지 않습니다",
    detail: "FastAPI 가 요청을 비동기로 받고, GPU 추론은 Ollama 큐가 순서대로 처리합니다. 수신과 처리를 분리했기에 앞 사람의 답변이 길어도 뒤 사람의 질문이 막히지 않습니다. 답변은 WebSocket 으로 흘러나가 첫 글자가 바로 보입니다." },
  { name: "세션 격리", line: "남의 상담은 있는지조차 알 수 없습니다",
    detail: "Access 가 통과시킨 이메일이 그 세션의 주인입니다. 다른 상담원의 대화에 접근하면 \"권한 없음\"이 아니라 \"없는 세션\"으로 답합니다 — 존재 여부조차 새지 않게 하려는 것입니다. 세션은 DB 에 있어 서버를 재시작해도 대화가 이어집니다." },
  { name: "기록의 재현", line: "반년 뒤에도 그때 조건으로 보입니다",
    detail: "로그에 고객 ID 만 남기면, 나중에 등급이 바뀌었을 때 과거 상담이 지금 등급으로 보입니다. 그래서 그 순간의 등급·자기부담금·부담보를 턴마다 박아둡니다. 검색된 조문도 본문까지 저장해, 약관을 다시 색인해도 \"그때 무엇을 보고 답했는지\"가 남습니다." },
  { name: "무중단 배포", line: "push 한 번으로 배포까지. 기준은 Git입니다",
    detail: "push 한 번에 Jenkins 가 빌드해 Harbor 에 올리고, ArgoCD 가 클러스터에 반영합니다. 클러스터 상태의 기준은 Git 이라 손으로 kubectl 을 쓰면 되돌려 놓습니다. 앱은 두 벌이 서로 다른 노드에서 돌아 한 대씩 교체되고, 그동안 요청은 끊기지 않습니다." },
  { name: "GPU 예산", line: "16GB 한 장에 모델 넷을 올립니다",
    detail: "임베딩과 리랭커는 상주하고, 생성 모델은 모드마다 갈아 끼웁니다. 쿠버네티스에 GPU 를 맡기면 장치를 통째로 한 Pod 가 가져가므로, GPU 를 쓰는 것은 호스트에 두고 Pod 가 네트워크로 부르는 구조를 택했습니다." },
  { name: "직접 세운 클러스터", line: "노드 넷, 진입점부터 인증서까지",
    detail: "Vagrant 로 VM 을 띄우고 kubeadm 으로 구성했습니다. 사설망에는 LoadBalancer 가 없어 MetalLB 로 진입점을 만들고, 인증서는 cert-manager 가 DNS 인증으로 받아옵니다. 약관 데이터는 이미지에 담지 않고 NFS 로 읽기 전용 마운트합니다." },
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

export function ModeSelect({ onSelect }: { onSelect: (m: Mode) => void }) {
  return (
    <main className={s.page}>
      <section className={s.hero}>
        <h1 className={s.title}>누구와 이야기할까요?</h1>
        <div className={s.grid}>
          {CHARACTERS.map((c) => <CharacterCard key={c.mode} c={c} onSelect={onSelect} />)}
        </div>
      </section>
      {/* 프로젝트 소개 — 스크롤하면 나온다. 모드마다 글·영상을 좌우 번갈아(지그재그), 끝에 기술 구성 */}
      <div className={s.about} aria-label="프로젝트 소개" role="region">
        {CHARACTERS.map((c, i) => <ModeIntro key={c.mode} c={c} reverse={i % 2 === 1} />)}
        <TechStack />
      </div>
    </main>
  );
}
