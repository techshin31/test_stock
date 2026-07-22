import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  CheckCircle2,
  XCircle,
  FileText,
  TrendingUp,
  ListChecks,
  ShieldCheck,
  Info
} from 'lucide-react'

function CustomListItem({ children, ...props }) {
  const content = Array.isArray(children) ? children : [children]

  // Check if list item text contains markdown checkbox patterns
  let isTask = false
  let isChecked = false

  const processChild = (child) => {
    if (typeof child === 'string') {
      if (child.startsWith('[x] ') || child.startsWith('[X] ')) {
        isTask = true
        isChecked = true
        return child.slice(4)
      }
      if (child.startsWith('[ ] ')) {
        isTask = true
        isChecked = false
        return child.slice(4)
      }
    }
    return child
  }

  const processedChildren = content.map((c) => {
    if (typeof c === 'string') return processChild(c)
    if (c?.props?.children) {
      if (typeof c.props.children === 'string') {
        const text = processChild(c.props.children)
        if (isTask) return text
      }
    }
    return c
  })

  if (isTask) {
    return (
      <li className={`report-task-item ${isChecked ? 'is-pass' : 'is-fail'}`} {...props}>
        <span className={`report-task-badge ${isChecked ? 'badge-pass' : 'badge-fail'}`}>
          {isChecked ? <CheckCircle2 size={13} /> : <XCircle size={13} />}
          <span>{isChecked ? '통과' : '미완료'}</span>
        </span>
        <div className="report-task-content">{processedChildren}</div>
      </li>
    )
  }

  return <li {...props}>{children}</li>
}

function CustomTable({ children, ...props }) {
  return (
    <div className="table-wrap report-table-wrap">
      <table className="report-table" {...props}>
        {children}
      </table>
    </div>
  )
}

function CustomHeading({ level, children, ...props }) {
  const text = String(children)
  let icon = null

  if (text.includes('Executive Summary') || text.includes('요약')) icon = <FileText size={16} />
  else if (text.includes('KPI') || text.includes('성과')) icon = <TrendingUp size={16} />
  else if (text.includes('기준') || text.includes('조치')) icon = <ListChecks size={16} />
  else if (text.includes('검증') || text.includes('한계')) icon = <ShieldCheck size={16} />
  else if (text.includes('주의') || text.includes('근거')) icon = <Info size={16} />

  const Tag = `h${level}`
  return (
    <Tag className="report-heading" {...props}>
      {icon && <span className="report-heading__icon">{icon}</span>}
      <span>{children}</span>
    </Tag>
  )
}

export default function MarkdownReport({ content }) {
  if (!content) return null

  return (
    <article className="markdown-body report-reader-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          li: CustomListItem,
          table: CustomTable,
          h1: (p) => <CustomHeading level={1} {...p} />,
          h2: (p) => <CustomHeading level={2} {...p} />,
          h3: (p) => <CustomHeading level={3} {...p} />,
        }}
      >
        {content}
      </ReactMarkdown>
    </article>
  )
}
