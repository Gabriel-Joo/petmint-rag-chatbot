import type { ReactNode } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import s from "./AnswerMarkdown.module.css";

// 모델 답변 마크다운(세 모드 공통). XSS: react-markdown은 HTML 문자열을 넣지 않고 React 요소로만 그린다 —
// 원시 HTML(rehype-raw)을 붙이지 않으므로 답변 속 <script>·<img onerror>는 글자로만 보인다. 링크는 기본 urlTransform이
// javascript: 같은 위험 주소를 지운다. 이미지는 그리지 않는다(외부 주소로 요청이 나가므로) — 허용 목록 밖 요소는 내용만 남긴다
const ALLOWED = ["p", "br", "strong", "em", "del", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote",
  "code", "pre", "hr", "table", "thead", "tbody", "tr", "th", "td", "a"];

/** 글자 속 "<br>"만 줄바꿈 요소로 — 모델이 표 칸 안 줄바꿈을 HTML로 쓴다(마크다운 표는 칸 안에 줄을 못 바꾼다).
 *  HTML을 여는 것이 아니라 이 태그 하나의 글자를 찾아 우리가 <br />을 만든다. 나머지 HTML은 그대로 글자다 */
const BR = /<br\s*\/?>/gi;
function withBreaks(children: ReactNode): ReactNode {
  const split = (c: ReactNode, k: number): ReactNode => {
    if (typeof c !== "string" || !BR.test(c)) return c;
    BR.lastIndex = 0;
    return c.split(BR).flatMap((part, i) => (i === 0 ? [part] : [<br key={`${k}-${i}`} />, part]));
  };
  return Array.isArray(children) ? children.map(split) : split(children, 0);
}

const COMPONENTS: Components = {
  a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
  td: ({ children }) => <td>{withBreaks(children)}</td>,
  th: ({ children }) => <th>{withBreaks(children)}</th>,
  p: ({ children }) => <p>{withBreaks(children)}</p>,
  li: ({ children }) => <li>{withBreaks(children)}</li>,
};

/** 스트리밍 중 덜 닫힌 표시를 임시로 닫는다 — 토큰이 하나씩 와서 "**굵" 상태가 그대로 "**"째 보였다. 다 받은 뒤에는 원문 그대로 그린다.
 *  1) 코드 블록(```)이 열려 있으면 닫는다(뒤 글이 통째로 코드가 되지 않게). 줄 첫머리의 백틱 한두 개는 아직 오는 중이라 뗀다
 *  2) 끝에 별표가 홀수 개면 하나를 뗀다 — 닫는 "**"의 첫 별표만 온 상태("**리스트*")거나 막 시작한 기울임·목록 표시다
 *  3) 마지막 줄의 ** · ` 개수가 홀수면 닫는다. 방금 연 표시 뒤에 아직 글자가 없으면("…설명 **") 닫지 않고 지운다 —
 *     닫으면 빈 굵게("****")가 글자째 보인다. 닫기 전에 끝 공백을 지운다 — "**해시 **"는 굵게로 읽히지 않는다 */
export function closeOpenMarks(text: string): string {
  let out = text.replace(/\n`{1,2}$/, "\n");      // 코드 블록 표시가 한 글자씩 오는 중("\n`", "\n``") — 아직 표시가 아니다
  const fences = (out.match(/^```/gm) ?? []).length;
  if (fences % 2 === 1) return `${out}\n\`\`\``;
  const stars = out.match(/\*+$/)?.[0].length ?? 0;
  if (stars % 2 === 1) out = out.slice(0, -1);
  const lastLine = out.slice(out.lastIndexOf("\n") + 1);
  for (const mark of ["**", "`"]) {
    if ((lastLine.split(mark).length - 1) % 2 === 0) continue;
    if (mark === "`" && lastLine.startsWith("```")) continue;   // 코드 블록 표시 줄 — 인라인 코드가 아니다
    out = out.endsWith(mark) ? out.slice(0, -mark.length) : out.trimEnd() + mark;
  }
  return out;
}

export function AnswerMarkdown({ text, streaming }: { text: string; streaming: boolean }) {
  return (
    <div className={s.md}>
      <Markdown remarkPlugins={[remarkGfm, remarkBreaks]} allowedElements={ALLOWED} unwrapDisallowed components={COMPONENTS}>
        {streaming ? closeOpenMarks(text) : text}
      </Markdown>
    </div>
  );
}
