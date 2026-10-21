import { Fragment, type ReactNode } from 'react';

/** Inline **bold** only; everything else is plain text (React escapes it). */
function inline(text: string): ReactNode[] {
  return text
    .split(/(\*\*[^*]+\*\*)/g)
    .map((part, i) =>
      part.startsWith('**') && part.endsWith('**') ? (
        <strong key={i}>{part.slice(2, -2)}</strong>
      ) : (
        <Fragment key={i}>{part}</Fragment>
      ),
    );
}

/**
 * A deliberately small Markdown subset for model output: paragraphs, numbered
 * and bulleted lists, and bold. No HTML, links or images are ever rendered.
 */
export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const items = list.items.map((item, i) => <li key={i}>{inline(item)}</li>);
    blocks.push(list.ordered ? <ol key={blocks.length}>{items}</ol> : <ul key={blocks.length}>{items}</ul>);
    list = null;
  };
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    const item = line.match(/^(\d+[.)]|[-*•])\s+(.*)$/);
    if (item) {
      const ordered = /^\d/.test(item[1]);
      if (!list || list.ordered !== ordered) {
        flush();
        list = { ordered, items: [] };
      }
      list.items.push(item[2]);
    } else {
      flush();
      if (line) blocks.push(<p key={blocks.length}>{inline(line.replace(/^#+\s*/, ''))}</p>);
    }
  }
  flush();
  return <>{blocks}</>;
}
