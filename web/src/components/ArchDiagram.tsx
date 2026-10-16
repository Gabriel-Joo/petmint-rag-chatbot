import s from "./ArchDiagram.module.css";

// 서비스 구성도 — 라이브러리 없이 인라인 SVG. 색은 전부 CSS 클래스로 토큰(:root)에서 받고, 글자는 <text>라 선택·검색이 된다.
// 넓은 화면은 가로형(세 갈래가 옆으로), 좁은 화면은 세로형(세 갈래가 아래로). 둘 다 DOM에 있고 CSS가 하나만 보인다 —
// 한 그림을 줄이기만 하면 좁은 화면에서 글자가 읽을 수 없을 만큼 작아진다.
// GPU를 쓰는 둘(search-service, Ollama)은 호스트에 있다 — 점선 테두리와 연보라 바탕으로 묶는다.

interface Node { x: number; y: number; w: number; h: number; title: string; sub?: string[]; host?: boolean }

function Box({ n, titleSize, subSize }: { n: Node; titleSize: number; subSize: number }) {
  const lines = n.sub ?? [];
  const lineH = subSize * 1.35;
  const blockH = titleSize + lines.length * lineH;
  const top = n.y + (n.h - blockH) / 2 + titleSize * 0.85; // 첫 줄 기준선
  const cx = n.x + n.w / 2;
  return (
    <g>
      <rect className={n.host ? s.boxHost : s.box} x={n.x} y={n.y} width={n.w} height={n.h} rx={10} />
      <text className={s.title} x={cx} y={top} fontSize={titleSize} textAnchor="middle">{n.title}</text>
      {lines.map((l, i) => (
        <text key={i} className={s.sub} x={cx} y={top + (i + 1) * lineH} fontSize={subSize} textAnchor="middle">{l}</text>
      ))}
    </g>
  );
}

function Arrow({ d, id }: { d: string; id: string }) {
  return <path className={s.edge} d={d} markerEnd={`url(#${id})`} />;
}

function Marker({ id }: { id: string }) {
  return (
    <marker id={id} viewBox="0 0 10 10" refX={9} refY={5} markerWidth={7} markerHeight={7} orient="auto-start-reverse">
      <path className={s.arrowHead} d="M0,0 L10,5 L0,10 z" />
    </marker>
  );
}

const SUB = {
  browser: ["모바일 / 사내 PC"],
  pod: ["K8s Pod · replicas 2"],
  mysql: ["세션·턴 로그"],
  search: ["KURE + bge-reranker", "→ Milvus"],
  ollama: ["Tri-7B 원본 / 파인튜닝"],
};

/** 가로형 — viewBox 1000 × 580 */
function Wide() {
  const m = "arch-arrow-wide";
  const N = {
    browser: { x: 330, y: 10, w: 340, h: 76, title: "상담원 브라우저", sub: SUB.browser },
    edge: { x: 330, y: 136, w: 340, h: 60, title: "Cloudflare Tunnel + Access" },
    pod: { x: 330, y: 246, w: 340, h: 76, title: "FastAPI + React", sub: SUB.pod },
    mysql: { x: 30, y: 412, w: 280, h: 96, title: "MySQL StatefulSet", sub: SUB.mysql },
    search: { x: 380, y: 412, w: 280, h: 96, title: "search-service", sub: SUB.search, host: true },
    ollama: { x: 690, y: 412, w: 280, h: 96, title: "Ollama", sub: SUB.ollama, host: true },
  } satisfies Record<string, Node>;
  return (
    <svg className={`${s.svg} ${s.wide}`} viewBox="0 0 1000 580" aria-labelledby="arch-wide-title">
      <title id="arch-wide-title">서비스 구성도</title>
      <defs><Marker id={m} /></defs>
      {/* 호스트 묶음 — 상자들보다 먼저 그려 뒤에 깔린다 */}
      <rect className={s.hostGroup} x={360} y={386} width={630} height={148} rx={14} />
      <text className={s.groupLabel} x={975} y={560} fontSize={17} textAnchor="end">호스트 · GPU</text>

      <Arrow id={m} d="M500,86 V134" />
      <text className={s.edgeLabel} x={514} y={116} fontSize={16}>HTTPS · WSS</text>
      <Arrow id={m} d="M500,196 V244" />
      {/* Pod에서 세 갈래 */}
      <path className={s.edge} d="M500,322 V362 M170,362 H830" />
      <Arrow id={m} d="M170,362 V410" />
      <Arrow id={m} d="M520,362 V410" />
      <Arrow id={m} d="M830,362 V410" />
      <path className={s.edge} d="M500,362 H520" />

      {Object.values(N).map((n) => <Box key={n.title} n={n} titleSize={22} subSize={16} />)}
    </svg>
  );
}

/** 세로형 — viewBox 360 × 600. 세 갈래는 왼쪽 줄기에서 오른쪽으로 뻗는다 */
function Narrow() {
  const m = "arch-arrow-narrow";
  const N = {
    browser: { x: 20, y: 6, w: 320, h: 62, title: "상담원 브라우저", sub: SUB.browser },
    edge: { x: 20, y: 112, w: 320, h: 48, title: "Cloudflare Tunnel + Access" },
    pod: { x: 20, y: 200, w: 320, h: 62, title: "FastAPI + React", sub: SUB.pod },
    mysql: { x: 66, y: 296, w: 274, h: 62, title: "MySQL StatefulSet", sub: SUB.mysql },
    search: { x: 66, y: 392, w: 274, h: 74, title: "search-service", sub: SUB.search, host: true },
    ollama: { x: 66, y: 482, w: 274, h: 62, title: "Ollama", sub: SUB.ollama, host: true },
  } satisfies Record<string, Node>;
  return (
    <svg className={`${s.svg} ${s.narrow}`} viewBox="0 0 360 600" aria-labelledby="arch-narrow-title">
      <title id="arch-narrow-title">서비스 구성도</title>
      <defs><Marker id={m} /></defs>
      <rect className={s.hostGroup} x={54} y={380} width={298} height={176} rx={12} />
      <text className={s.groupLabel} x={348} y={576} fontSize={14} textAnchor="end">호스트 · GPU</text>

      <Arrow id={m} d="M180,68 V110" />
      <text className={s.edgeLabel} x={190} y={94} fontSize={13.5}>HTTPS · WSS</text>
      <Arrow id={m} d="M180,160 V198" />
      <path className={s.edge} d="M40,262 V513" />
      <Arrow id={m} d="M40,327 H64" />
      <Arrow id={m} d="M40,429 H64" />
      <Arrow id={m} d="M40,513 H64" />

      {Object.values(N).map((n) => <Box key={n.title} n={n} titleSize={16.5} subSize={13.5} />)}
    </svg>
  );
}

export function ArchDiagram() {
  return (
    <figure className={s.figure}>
      <Wide />
      <Narrow />
      <figcaption className={s.caption}>
        점선 안은 쿠버네티스 바깥, GPU가 있는 호스트에서 돕니다. Pod는 이 둘을 네트워크로 부릅니다.
      </figcaption>
    </figure>
  );
}
