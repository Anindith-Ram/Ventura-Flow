import { useState } from 'react'

interface Author {
  name: string
  author_id?: string | null
  affiliations?: string[]
  h_index?: number | null
  works_count?: number | null
  cited_by_count?: number | null
}

export function AuthorHoverCard({ author }: { author: Author }) {
  const [open, setOpen] = useState(false)
  const openalex = author.author_id
    ? `https://openalex.org/${author.author_id.replace('https://openalex.org/', '')}`
    : null
  return (
    <span
      style={{ position: 'relative', display: 'inline-block' }}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <span
        style={{
          borderBottom: '1px dotted var(--muted-2)',
          cursor: 'help',
          transition: 'color 0.15s',
          color: open ? 'var(--coral-dark)' : 'inherit',
        }}
      >
        {author.name}
      </span>
      {open && (author.h_index || author.cited_by_count || author.works_count || author.affiliations?.length) ? (
        <div
          style={{
            position: 'absolute', zIndex: 20,
            bottom: '140%', left: 0,
            background: 'var(--panel)',
            border: '1px solid var(--line-strong)',
            borderRadius: 10,
            padding: '12px 14px',
            width: 280,
            boxShadow: 'var(--shadow-lg)',
            fontSize: 12,
            lineHeight: 1.5,
            animation: 'fadeUp 0.18s cubic-bezier(0.22, 1, 0.36, 1)',
          }}
        >
          <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6, color: 'var(--text)' }}>
            {author.name}
          </div>
          {author.affiliations?.length ? (
            <div style={{ color: 'var(--muted)', marginBottom: 8 }}>
              {author.affiliations.slice(0, 2).join(' · ')}
            </div>
          ) : null}
          <div style={{ display: 'flex', gap: 14, marginBottom: openalex ? 8 : 0 }}>
            {author.h_index != null && (
              <div>
                <div style={{ color: 'var(--muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>
                  h-index
                </div>
                <div style={{ fontWeight: 700, color: 'var(--coral-dark)', fontSize: 15 }}>
                  {author.h_index}
                </div>
              </div>
            )}
            {author.works_count != null && (
              <div>
                <div style={{ color: 'var(--muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>
                  works
                </div>
                <div style={{ fontWeight: 700, fontSize: 15 }}>
                  {author.works_count}
                </div>
              </div>
            )}
            {author.cited_by_count != null && (
              <div>
                <div style={{ color: 'var(--muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>
                  cited
                </div>
                <div style={{ fontWeight: 700, fontSize: 15 }}>
                  {Intl.NumberFormat('en', { notation: 'compact' }).format(author.cited_by_count)}
                </div>
              </div>
            )}
          </div>
          {openalex && (
            <a
              href={openalex} target="_blank" rel="noreferrer"
              style={{ fontSize: 11, color: 'var(--coral-dark)' }}
            >
              View on OpenAlex ↗
            </a>
          )}
        </div>
      ) : null}
    </span>
  )
}
