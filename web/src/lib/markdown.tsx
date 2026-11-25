import type { ReactNode } from "react";

/** Inline Markdown: **bold**, *italic*, `code`. Text only, no HTML is ever injected. */
function inline(text: string, key: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`)/).filter(Boolean).map((p, i) => {
    const k = `${key}-${i}`;
    if (p.startsWith("**") && p.endsWith("**") && p.length > 4) return <b key={k}>{p.slice(2, -2)}</b>;
    if (p.startsWith("`") && p.endsWith("`") && p.length > 2) return <code key={k}>{p.slice(1, -1)}</code>;
    if (p.startsWith("*") && p.endsWith("*") && p.length > 2) return <em key={k}>{p.slice(1, -1)}</em>;
    return <span key={k}>{p}</span>;
  });
}

/** The small Markdown subset Smart Notes uses: headings, bullet and numbered lists, paragraphs. */
export function Markdown({ text }: { text: string }) {
  const out: ReactNode[] = [];
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  let list: { ordered: boolean; items: string[] } | null = null;
  let para: string[] = [];
  const flushPara = () => { if (para.length) { out.push(<p key={`p${out.length}`}>{inline(para.join(" "), `p${out.length}`)}</p>); para = []; } };
  const flushList = () => {
    if (!list) return;
    const items = list.items.map((it, i) => <li key={i}>{inline(it, `l${out.length}-${i}`)}</li>);
    out.push(list.ordered ? <ol key={`o${out.length}`}>{items}</ol> : <ul key={`u${out.length}`}>{items}</ul>);
    list = null;
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    const ul = /^\s*[-*•]\s+(.*)$/.exec(line);
    const ol = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (h) {
      flushPara(); flushList();
      const level = h[1].length;
      const content = inline(h[2], `h${out.length}`);
      out.push(level === 1 ? <h2 key={`h${out.length}`} className="md-h1">{content}</h2> : level === 2 ? <h3 key={`h${out.length}`}>{content}</h3> : <h4 key={`h${out.length}`}>{content}</h4>);
    } else if (ul || ol) {
      flushPara();
      const ordered = !!ol;
      if (list && list.ordered !== ordered) flushList();
      if (!list) list = { ordered, items: [] };
      list.items.push((ul ?? ol)![1]);
    } else if (!line.trim()) {
      flushPara(); flushList();
    } else {
      flushList();
      para.push(line.trim());
    }
  }
  flushPara(); flushList();
  return <div className="md">{out}</div>;
}
