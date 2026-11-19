import s from "./ArchDiagram.module.css";

// 서비스 구성도(2026-11-19 새로 그림). 라이브러리 없이 인라인 SVG. 색은 전부 CSS 클래스로 토큰(:root)에서 받고, 글자는 <text>라 선택과 검색이 된다.
// 넓은 화면은 가로형, 좁은 화면은 세로형. 둘 다 DOM에 있고 CSS가 하나만 보인다. 한 그림을 줄이기만 하면 좁은 화면에서 글자가 너무 작아진다.
// 그림은 운영 설정을 따른다: 앱 Pod 두 벌(ronanlab-infra apps/petmint/app/deployment.yaml), 그래픽카드를 쓰는 것은 모두 호스트(app/config.py 7-3),
// 검색 서버는 모델을 직접 올리지 않고 공용 모델 서버를 부른다(search_service/main.py 머리 주석), 조항 원문은 앱이 Milvus에서 바로 읽는다(MILVUS_URL).
// 주소와 포트는 그리지 않는다(공개 화면).

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

function Arrow({ d, id, dotted }: { d: string; id: string; dotted?: boolean }) {
  return <path className={`${s.edge} ${dotted ? s.edgeDotted : ""}`} d={d} markerEnd={`url(#${id})`} />;
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
  browser: { title: "브라우저", sub: ["상담원, 체험 방문자"] },
  tunnel: { title: "Cloudflare 터널", sub: ["바깥으로 연 포트 없음"] },
  app: { title: "앱: FastAPI + React", sub: ["두 벌을 노드 둘에 나눠 띄움", "검색 범위, 코드 답, 발췌 조립"] },
  mysql: { title: "MySQL", sub: ["상담 기록, 로그인", "고객 원장, 인사 원장(가상)"] },
  search: { title: "검색 서버", sub: ["벡터 + 키워드 검색", "리랭커로 다시 줄 세움"] },
  models: { title: "공용 모델 서버", sub: ["KURE-v1 임베딩", "bge-reranker-v2-m3"] },
  milvus: { title: "Milvus", sub: ["강아지 약관, 고양이 약관", "인사규정"] },
  nfs: { title: "NFS", sub: ["약관 조각, 참조 그래프", "앱에 읽기 전용으로 붙음"] },
  ollama: { title: "Ollama", sub: ["Tri-7B 원본: 일반, 사내규정", "Tri-7B + LoRA: 업무특화"] },
};

/** 가로형, viewBox 1000 × 650. 왼쪽 쿠버네티스, 오른쪽 호스트 */
function Wide() {
  const m = "arch-arrow-wide";
  const TS = 20, SS = 15, LS = 14;
  return (
    <svg className={`${s.svg} ${s.wide}`} viewBox="0 0 1000 650" aria-labelledby="arch-wide-title">
      <title id="arch-wide-title">서비스 구성도</title>
      <defs><Marker id={m} /></defs>

      {/* 묶음 — 상자보다 먼저 그려 뒤에 깔린다 */}
      <rect className={s.k8sGroup} x={14} y={200} width={430} height={320} rx={14} />
      <GroupLabel x={432} y={510} size={LS} anchor="end">쿠버네티스</GroupLabel>
      <rect className={s.hostGroup} x={480} y={200} width={506} height={440} rx={14} />
      <GroupLabel x={974} y={630} size={LS} anchor="end" host>호스트 (그래픽카드 한 장)</GroupLabel>

      <Arrow id={m} d="M500,74 V108" />
      <Label x={512} y={97} size={LS}>HTTPS, WebSocket</Label>
      <Arrow id={m} d="M500,174 V190 H235 V238" />
      <Arrow id={m} d="M235,340 V398" />
      <Arrow id={m} d="M430,270 H498" />
      <Label x={462} y={262} size={LS} anchor="middle">검색</Label>
      <Arrow id={m} d="M720,290 H744" />
      <Arrow id={m} d="M610,340 V388" />
      <Arrow id={m} d="M430,310 H462 V435 H498" dotted />
      {/* 답 생성: 앱 왼쪽에서 내려가 쿠버네티스 묶음 아래로 Ollama까지 */}
      <Arrow id={m} d="M40,290 H26 V565 H498" />
      <Label x={250} y={557} size={LS} anchor="middle">답 생성</Label>

      <Box n={{ x: 330, y: 10, w: 340, h: 64, ...T.browser }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 330, y: 110, w: 340, h: 64, ...T.tunnel }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 40, y: 240, w: 390, h: 100, ...T.app }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 40, y: 400, w: 390, h: 90, ...T.mysql }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 500, y: 240, w: 220, h: 100, ...T.search, host: true }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 746, y: 240, w: 214, h: 100, ...T.models, host: true }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 500, y: 390, w: 220, h: 90, ...T.milvus, host: true }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 746, y: 390, w: 214, h: 90, ...T.nfs, host: true }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 500, y: 520, w: 460, h: 90, ...T.ollama, host: true }} titleSize={TS} subSize={SS} />
    </svg>
  );
}

/** 세로형, viewBox 360 × 700. 검색은 왼쪽 가장자리, 답 생성은 오른쪽 가장자리를 탄다 */
function Narrow() {
  const m = "arch-arrow-narrow";
  const TS = 15, SS = 11.5, LS = 11;
  return (
    <svg className={`${s.svg} ${s.narrow}`} viewBox="0 0 360 700" aria-labelledby="arch-narrow-title">
      <title id="arch-narrow-title">서비스 구성도</title>
      <defs><Marker id={m} /></defs>

      <rect className={s.k8sGroup} x={8} y={150} width={344} height={196} rx={12} />
      <GroupLabel x={340} y={340} size={LS} anchor="end">쿠버네티스</GroupLabel>
      <rect className={s.hostGroup} x={8} y={362} width={344} height={330} rx={12} />
      <GroupLabel x={340} y={684} size={LS} anchor="end" host>호스트 (그래픽카드 한 장)</GroupLabel>

      <Arrow id={m} d="M180,58 V86" />
      <Label x={190} y={76} size={LS}>HTTPS, WebSocket</Label>
      <Arrow id={m} d="M180,136 V162" />
      <Arrow id={m} d="M180,236 V258" />
      <Arrow id={m} d="M30,200 H18 V415 H28" />
      <Label x={34} y={375} size={LS}>검색</Label>
      <Arrow id={m} d="M18,415 V513 H28" dotted />
      <Arrow id={m} d="M170,415 H188" />
      <Arrow id={m} d="M100,450 V476" />
      <Arrow id={m} d="M330,200 H344 V618 H332" />
      <Label x={326} y={571} size={LS} anchor="end">답 생성</Label>

      <Box n={{ x: 20, y: 6, w: 320, h: 52, ...T.browser }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 20, y: 88, w: 320, h: 48, ...T.tunnel }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 30, y: 164, w: 300, h: 72, ...T.app }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 30, y: 260, w: 300, h: 66, ...T.mysql }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 30, y: 380, w: 140, h: 70, title: T.search.title, sub: ["벡터 + 키워드", "리랭커"], host: true }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 190, y: 380, w: 140, h: 70, title: "공용 모델 서버", sub: ["KURE-v1", "bge-reranker"], host: true }} titleSize={TS - 1} subSize={SS} />
      <Box n={{ x: 30, y: 478, w: 140, h: 70, title: T.milvus.title, sub: ["약관 둘", "인사규정"], host: true }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 190, y: 478, w: 140, h: 70, title: T.nfs.title, sub: ["약관 조각", "참조 그래프"], host: true }} titleSize={TS} subSize={SS} />
      <Box n={{ x: 30, y: 578, w: 300, h: 80, title: T.ollama.title, sub: ["Tri-7B 원본: 일반, 사내규정", "Tri-7B + LoRA: 업무특화"], host: true }}
           titleSize={TS} subSize={SS} />
    </svg>
  );
}

export function ArchDiagram() {
  return (
    <figure className={s.figure}>
      <Wide />
      <Narrow />
      <figcaption className={s.caption}>
        점선 묶음은 쿠버네티스 밖의 호스트입니다. 그래픽카드를 쓰는 것은 모두 호스트에 두고, 앱이 사설망으로 부릅니다.
        <br />
        잔 점선은 앱이 근거 조항의 원문을 Milvus에서 바로 읽는 길입니다.
      </figcaption>
    </figure>
  );
}
