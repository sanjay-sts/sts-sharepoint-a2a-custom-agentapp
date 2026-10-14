import * as React from 'react';
import { Link } from '@fluentui/react/lib/Link';
import { Text } from '@fluentui/react/lib/Text';

/**
 * Markdown-lite renderer for agent answers: paragraphs, list markers, **bold**,
 * [label](url) and bare http(s) links. Links open in a new tab. No HTML is injected.
 */

const LINK_RE = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<>()]+)/g;
const BOLD_RE = /\*\*([^*]+)\*\*/g;

function renderBold(text: string, keyBase: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  BOLD_RE.lastIndex = 0;
  while ((m = BOLD_RE.exec(text)) !== null) {
    if (m.index > last) { out.push(text.substring(last, m.index)); }
    out.push(<strong key={`${keyBase}-b${m.index}`}>{m[1]}</strong>);
    last = m.index + m[0].length;
  }
  if (last < text.length) { out.push(text.substring(last)); }
  return out;
}

function renderInline(text: string, keyBase: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  LINK_RE.lastIndex = 0;
  while ((m = LINK_RE.exec(text)) !== null) {
    if (m.index > last) { out.push(...renderBold(text.substring(last, m.index), `${keyBase}-t${last}`)); }
    const label = m[1] || m[3];
    const href = (m[2] || m[3]).replace(/[.,;:]+$/, '');
    out.push(
      <Link key={`${keyBase}-l${m.index}`} href={href} target="_blank" rel="noopener noreferrer">{label}</Link>
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) { out.push(...renderBold(text.substring(last), `${keyBase}-t${last}`)); }
  return out;
}

export interface IAnswerTextProps { text: string }

export const AnswerText: React.FunctionComponent<IAnswerTextProps> = ({ text }) => {
  const lines = text.split('\n');
  return (
    <div>
      {lines.map((raw, i) => {
        let line = raw;
        let bullet = false;
        const lm = /^\s*([-*]|\d+\.)\s+/.exec(line);
        if (lm) { bullet = true; line = line.substring(lm[0].length); }
        if (/^\s*\|?[\s:-]+\|[\s|:-]*$/.test(line)) { return null; } // markdown table separator row
        line = line.replace(/^#+\s*/, '').replace(/^\|/, '').replace(/\|$/, '').split('|').join('  ·  ');
        if (line.trim() === '') { return <div key={i} style={{ height: 6 }} />; }
        return (
          <Text key={i} block style={{ whiteSpace: 'pre-wrap', paddingLeft: bullet ? 16 : 0 }}>
            {bullet ? '• ' : ''}{renderInline(line, `L${i}`)}
          </Text>
        );
      })}
    </div>
  );
};
