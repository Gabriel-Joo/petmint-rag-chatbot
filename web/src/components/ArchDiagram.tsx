import s from "./ArchDiagram.module.css";

// 서비스 구성도 — 라이브러리 없이 인라인 SVG. 색은 전부 CSS 클래스로 토큰(:root)에서 받고, 글자는 <text>라 선택·검색이 된다.
// 넓은 화면은 가로형, 좁은 화면은 세로형. 둘 다 DOM에 있고 CSS가 하나만 보인다 —
// 한 그림을 줄이기만 하면 좁은 화면에서 글자가 읽을 수 없을 만큼 작아진다.
// 구조는 docs/pipeline.md 2절을 따른다(2026-10-16 판):
//   Pod → search-service(청크 top-k) → Pod: 발췌 조립(그래프는 여기에 붙는다) → Ollama. 일반은 검색 없이 Pod → Ollama 원본.
//   점선 묶음 = 쿠버네티스 바깥 호스트. 흐린 상자·점선 화살표 = 예정(search-service 미배포, 인사규정 Milvus 색인 전) —
//   포트폴리오에서 돌아가는 것처럼 보이면 안 된다.

interface Node { x: number; y: number; w: number; h: number; title: string; sub?: string[]; host?: boolean; planned?: boolean }

function Box({ n, titleSize, subSize }: { n: Node; titleSize: number; subSize: number }) {
  const lines = n.sub ?? [];
  const lineH = subSize * 1.35;
  const blockH = titleSize + lines.length * lineH;
  const top = n.y + (n.h - blockH) / 2 + titleSize * 0.85; // 첫 줄 기준선
  const cx = n.x + n.w / 2;
  const tagW = subSize * 2.9;
  return (
    <g className={n.planned ? s.planned : undefined}>
      <rect className={n.host ? s.boxHost : s.box} x={n.x} y={n.y} width={n.w} height={n.h} rx={10} />
      <text className={s.title} x={cx} y={top} fontSize={titleSize} textAnchor="middle">{n.title}</text>
      {lines.map((l, i) => (
        <text key={i} className={s.sub} x={cx} y={top + (i + 1) * lineH} fontSize={subSize} textAnchor="middle">{l}</text>
      ))}
      {/* 꼬리표는 위 테두리에 걸쳐 둔다 — 상자 안에 넣으면 좁은 상자에서 제목과 겹친다 */}
      {n.planned && (
        <g>
          <rect className={s.tag} x={n.x + n.w - tagW - 8} y={n.y - subSize * 0.75} width={tagW} height={subSize * 1.5} rx={subSize * 0.75} />
          <text className={s.tagText} x={n.x + n.w - tagW / 2 - 8} y={n.y + subSize * 0.33} fontSize={subSize * 0.9} textAnchor="middle">예정</text>
        </g>
      )}
    </g>
  );
}

function Arrow({ d, id, planned, dotted }: { d: string; id: string; planned?: boolean; dotted?: boolean }) {
  const cls = [s.edge, planned ? s.edgePlanned : "", dotted ? s.edgeDotted : ""].join(" ");
  return <path className={cls} d={d} markerEnd={`url(#${id})`} />;
}

function Marker({ id }: { id: string }) {
  return (
    <marker id={id} viewBox="0 0 10 10" refX={9} refY={5} markerWidth={7} markerHeight={7} orient="auto-start-reverse">
      <path className={s.arrowHead} d="M0,0 L10,5 L0,10 z" />
    </marker>
  );
}

function Label({ x, y, size, children, anchor = "start", rotate }: {
  x: number; y: number; size: number; children: string; anchor?: "start" | "middle" | "end"; rotate?: number;
}) {
  return (
    <text className={s.edgeLabel} x={x} y={y} fontSize={size} textAnchor={anchor}
          transform={rotate ? `rotate(${rotate} ${x} ${y})` : undefined}>{children}</text>
  );
}

function GroupLabel({ x, y, size, children, anchor = "start", host }: {
  x: number; y: number; size: number; children: string; anchor?: "start" | "end"; host?: boolean;
}) {
  return <text className={host ? s.groupLabel : s.k8sLabel} x={x} y={y} fontSize={size} textAnchor={anchor}>{children}</text>;
}

const T = {
  browser: { title: "상담원 브라우저", sub: ["모바일 / 사내 PC"] },
  edge: { title: "Cloudflare Tunnel + Access" },
  pod: { title: "FastAPI + React", sub: ["K8s Pod · replicas 2"] },
  mysql: { title: "MySQL", sub: ["세션·턴 로그"] },
  search: { title: "search-service", sub: ["KURE-v1 + bge-reranker"] },
  graph: { title: "조항 참조 그래프" },
  assemble: { title: "Pod: 발췌 조립", sub: ["청크 + 참조 조문 + 길이 예산"] },
  base: { title: "Ollama", sub: ["Tri-7B 원본"] },
  lora: { title: "Ollama", sub: ["Tri-7B + LoRA"] },
};

/** Milvus 컬렉션 셋을 한 묶음으로. 인사규정은 아직 색인 전(예정) */
function Milvus({ x, y, w, h, cols, titleSize, boxSize }: {
  x: number; y: number; w: number; h: number; titleSize: number; boxSize: number;
  cols: { x: number; y: number; w: number; h: number }[];
}) {
  const names = ["인사규정", "강아지 약관", "고양이 약관"];
  return (
    <g>
      <rect className={s.milvus} x={x} y={y} width={w} height={h} rx={10} />
      <text className={s.title} x={x + w / 2} y={y + titleSize * 1.3} fontSize={titleSize} textAnchor="middle">Milvus</text>
      {cols.map((c, i) => (
        <Box key={names[i]} n={{ ...c, title: names[i], host: true, planned: i === 0 }} titleSize={boxSize} subSize={boxSize} />
      ))}
    </g>
  );
}

/** 가로형 — viewBox 1000 × 860. 왼쪽 쿠버네티스, 오른쪽 위 호스트(검색·Milvus), 아래 호스트(Ollama) */
function Wide() {
  const m = "arch-arrow-wide";
  const TS = 20, SS = 15, LS = 14;
  return (
    <svg className={`${s.svg} ${s.wide}`} viewBox="0 0 1000 860" aria-labelledby="arch-wide-title">
      <title id="arch-wide-title">서비스 구성도</title>
      <defs><Marker id={m} /></defs>

      {/* 묶음 — 상자보다 먼저 그려 뒤에 깔린다 */}
      <rect className={s.k8sGroup} x={14} y={228} width={498} height={444} rx={14} />
      <GroupLabel x={26} y={250} size={LS}>Kubernetes</GroupLabel>
      <rect className={s.hostGroup} x={530} y={228} width={456} height={268} rx={14} />
      <GroupLabel x={544} y={486} size={LS} host>호스트</GroupLabel>
      <rect className={s.hostGroup} x={14} y={700} width={972} height={146} rx={14} />
      <GroupLabel x={974} y={836} size={LS} anchor="end" host>호스트 · GPU</GroupLabel>

      {/* 흐름 */}
      <Arrow id={m} d="M500,84 V128" />
      <Label x={512} y={112} size={LS}>HTTPS · WSS</Label>
      <Arrow id={m} d="M500,190 V214 H220 V256" />
      <Arrow id={m} d="M120,336 V388" />
      {/* 일반: 검색 없이 원본으로 — 왼쪽 가장자리를 타고 내려간다 */}
      <Arrow id={m} d="M60,300 H36 V770 H68" />
      <Label x={28} y={560} size={LS} anchor="middle" rotate={-90}>일반 · 검색 없음</Label>
      {/* 사내규정·업무특화: search-service(예정) */}
      <Arrow id={m} d="M380,316 H550" planned />
      <Label x={388} y={306} size={LS}>사내규정 · 업무특화</Label>
      <Arrow id={m} d="M790,362 H808" planned />
      {/* 조항 원문 — Pod가 Milvus를 바로 읽는다 */}
      <Arrow id={m} d="M380,270 H892 V280" dotted />
      <Label x={560} y={262} size={LS}>조항 원문</Label>
      {/* 청크 top-k → 발췌 조립 */}
      <Arrow id={m} d="M670,412 V604 H472" planned />
      <Label x={680} y={560} size={LS}>청크 top-k</Label>
      <Arrow id={m} d="M365,512 V556" />
      {/* 조립 → 모델 */}
      <Arrow id={m} d="M260,652 V728" planned />
      <Label x={268} y={694} size={LS}>사내규정 (예정)</Label>
      <Arrow id={m} d="M470,630 H750 V728" />
      <Label x={600} y={622} size={LS}>업무특화</Label>

      <Box n={{ x: 330, y: 10, w: 340, h: 74, ...T.browser }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 330, y: 130, w: 340, h: 60, ...T.edge }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 60, y: 258, w: 320, h: 78, ...T.pod }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 60, y: 390, w: 170, h: 70, ...T.mysql }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 552, y: 312, w: 238, h: 100, ...T.search, host: true, planned: true }} titleSize={TS} subSize={SS} />
      <Milvus x={810} y={282} w={164} h={200} titleSize={18} boxSize={15}
              cols={[{ x: 822, y: 324, w: 140, h: 46 }, { x: 822, y: 376, w: 140, h: 46 }, { x: 822, y: 428, w: 140, h: 46 }]} />
      <Box n={{ x: 260, y: 452, w: 210, h: 60, ...T.graph }} titleSize={18} subSize={SS} />
      <Box n={{ x: 160, y: 558, w: 310, h: 94, ...T.assemble }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 70, y: 730, w: 380, h: 80, ...T.base, host: true }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 560, y: 730, w: 380, h: 80, ...T.lora, host: true }} titleSize={TS} subSize={SS} />
    </svg>
  );
}

/** 세로형 — viewBox 360 × 830. 일반은 오른쪽 가장자리를 타고 원본으로 */
function Narrow() {
  const m = "arch-arrow-narrow";
  const TS = 15, SS = 11.5, LS = 11;
  return (
    <svg className={`${s.svg} ${s.narrow}`} viewBox="0 0 360 830" aria-labelledby="arch-narrow-title">
      <title id="arch-narrow-title">서비스 구성도</title>
      <defs><Marker id={m} /></defs>

      <rect className={s.hostGroup} x={10} y={326} width={332} height={156} rx={12} />
      <GroupLabel x={20} y={474} size={LS} host>호스트</GroupLabel>
      <rect className={s.hostGroup} x={10} y={688} width={342} height={130} rx={12} />
      <GroupLabel x={344} y={810} size={LS} anchor="end" host>호스트 · GPU</GroupLabel>

      <Arrow id={m} d="M180,62 V94" />
      <Label x={190} y={83} size={LS}>HTTPS · WSS</Label>
      <Arrow id={m} d="M180,140 V170" />
      <Arrow id={m} d="M60,228 V258" />
      <Arrow id={m} d="M300,200 H346 V744 H342" />
      <Label x={334} y={600} size={LS} anchor="middle" rotate={-90}>일반 · 검색 없음</Label>
      <Arrow id={m} d="M140,228 V340" planned />
      <Label x={146} y={292} size={LS} anchor="start">사내규정·업무특화</Label>
      <Arrow id={m} d="M160,385 H170" planned />
      <Arrow id={m} d="M285,228 V334" dotted />
      <Label x={278} y={262} size={LS} anchor="end">조항 원문</Label>
      <Arrow id={m} d="M90,420 V560" planned />
      <Label x={98} y={512} size={LS}>청크 top-k</Label>
      <Arrow id={m} d="M225,540 V560" />
      <Arrow id={m} d="M80,628 V712" />
      <Label x={88} y={664} size={LS}>업무특화</Label>
      <Arrow id={m} d="M260,628 V712" planned />
      <Label x={252} y={664} size={LS} anchor="end">사내규정 (예정)</Label>

      <Box n={{ x: 20, y: 6, w: 320, h: 56, ...T.browser }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 20, y: 96, w: 320, h: 44, ...T.edge }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 20, y: 172, w: 280, h: 56, ...T.pod }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 20, y: 260, w: 92, h: 50, ...T.mysql }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 20, y: 342, w: 140, h: 78, title: T.search.title, sub: ["KURE-v1", "+ bge-reranker"], host: true, planned: true }}
           titleSize={TS} subSize={SS} />
      <Milvus x={172} y={336} w={162} h={128} titleSize={12.5} boxSize={12}
              cols={[{ x: 180, y: 358, w: 146, h: 30 }, { x: 180, y: 392, w: 146, h: 30 }, { x: 180, y: 426, w: 146, h: 30 }]} />
      <Box n={{ x: 150, y: 500, w: 150, h: 40, ...T.graph }} titleSize={12.5} subSize={SS} />
      <Box n={{ x: 20, y: 562, w: 280, h: 66, ...T.assemble }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 20, y: 714, w: 150, h: 60, ...T.lora, host: true }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 190, y: 714, w: 150, h: 60, ...T.base, host: true }} titleSize={TS} subSize={SS} />
    </svg>
  );
}

export function ArchDiagram() {
  return (
    <figure className={s.figure}>
      <Wide />
      <Narrow />
      <figcaption className={s.caption}>
        점선 묶음은 쿠버네티스 바깥의 호스트입니다. 흐리게 표시한 search-service와 인사규정 색인은 아직 배포 전입니다.
        <br />
        answer.py와 search-service가 붙기 전까지 답변은 더미입니다.
      </figcaption>
    </figure>
  );
}
