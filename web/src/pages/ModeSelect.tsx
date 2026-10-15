import { Fragment, useRef, useState } from "react";
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

export function ModeSelect({ onSelect }: { onSelect: (m: Mode) => void }) {
  return (
    <main className={s.page}>
      <section className={s.hero}>
        <h1 className={s.title}>누구와 이야기할까요?</h1>
        <div className={s.grid}>
          {CHARACTERS.map((c) => <CharacterCard key={c.mode} c={c} onSelect={onSelect} />)}
        </div>
      </section>
      {/* 프로젝트 소개 — 스크롤하면 나온다. 내용은 나중에 채운다(자리만) */}
      <section className={s.about} aria-label="프로젝트 소개" />
    </main>
  );
}
