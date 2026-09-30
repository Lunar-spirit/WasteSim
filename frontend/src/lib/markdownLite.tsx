import type { ReactNode } from 'react'

// A deliberately small, dependency-free renderer — the copilot's answers
// only ever need bold text, inline/fenced code, and numbered/bulleted
// lists, so a full markdown library (react-markdown + remark/rehype) would
// be a lot of bundle weight for three constructs. Not a general-purpose
// parser: anything not matched below is rendered as plain paragraph text.

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter((p) => p !== '')
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={`${keyPrefix}-${i}`}>{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code key={`${keyPrefix}-${i}`} className="rounded bg-slate-900/10 px-1 py-0.5 font-mono text-[0.85em]">
          {part.slice(1, -1)}
        </code>
      )
    }
    return <span key={`${keyPrefix}-${i}`}>{part}</span>
  })
}

function renderTextBlock(text: string, keyPrefix: string): ReactNode[] {
  const lines = text.split('\n')
  const nodes: ReactNode[] = []
  let i = 0
  let group = 0

  while (i < lines.length) {
    const line = lines[i]
    const numbered = /^\s*\d+\.\s+(.*)$/.exec(line)
    const bulleted = /^\s*[-*]\s+(.*)$/.exec(line)

    if (numbered) {
      const items: string[] = []
      while (i < lines.length) {
        const m = /^\s*\d+\.\s+(.*)$/.exec(lines[i])
        if (!m) break
        items.push(m[1])
        i++
      }
      nodes.push(
        <ol key={`${keyPrefix}-ol-${group++}`} className="ml-4 list-decimal space-y-0.5">
          {items.map((item, idx) => (
            <li key={idx}>{renderInline(item, `${keyPrefix}-oli-${idx}`)}</li>
          ))}
        </ol>,
      )
      continue
    }

    if (bulleted) {
      const items: string[] = []
      while (i < lines.length) {
        const m = /^\s*[-*]\s+(.*)$/.exec(lines[i])
        if (!m) break
        items.push(m[1])
        i++
      }
      nodes.push(
        <ul key={`${keyPrefix}-ul-${group++}`} className="ml-4 list-disc space-y-0.5">
          {items.map((item, idx) => (
            <li key={idx}>{renderInline(item, `${keyPrefix}-uli-${idx}`)}</li>
          ))}
        </ul>,
      )
      continue
    }

    // Plain paragraph lines: consume until the next list or a blank line.
    const paragraphLines: string[] = []
    while (i < lines.length && !/^\s*\d+\.\s+/.test(lines[i]) && !/^\s*[-*]\s+/.test(lines[i])) {
      paragraphLines.push(lines[i])
      i++
    }
    const paragraphText = paragraphLines.join('\n').trim()
    if (paragraphText) {
      nodes.push(
        <p key={`${keyPrefix}-p-${group++}`} className="whitespace-pre-wrap">
          {renderInline(paragraphText, `${keyPrefix}-p-${group}`)}
        </p>,
      )
    }
  }

  return nodes
}

export function renderMarkdownLite(content: string): ReactNode {
  const segments = content.split(/(```[\s\S]*?```)/g).filter((s) => s !== '')

  return (
    <div className="flex flex-col gap-1.5">
      {segments.map((segment, idx) => {
        if (segment.startsWith('```') && segment.endsWith('```')) {
          const inner = segment.slice(3, -3).replace(/^[a-zA-Z0-9_-]*\n/, '')
          return (
            <pre
              key={`code-${idx}`}
              className="overflow-x-auto rounded-md bg-slate-900 px-2.5 py-2 text-[0.8em] text-slate-100"
            >
              <code>{inner}</code>
            </pre>
          )
        }
        return <div key={`text-${idx}`}>{renderTextBlock(segment, `t${idx}`)}</div>
      })}
    </div>
  )
}
