import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSlug from 'rehype-slug'
import rehypeAutolinkHeadings from 'rehype-autolink-headings'

function DocRenderer({ raw }) {
  return (
    <div className="doc-renderer">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[
          rehypeSlug,
          [rehypeAutolinkHeadings, { behavior: 'append', properties: { className: ['doc-anchor'] } }],
        ]}
        components={{
          a: ({ node, ...props }) => <a {...props} target={props.href?.startsWith('#') ? undefined : '_blank'} rel="noreferrer" />,
          code: ({ inline, children, ...props }) => (
            inline
              ? <code className="doc-inline-code" {...props}>{children}</code>
              : <code className="doc-block-code" {...props}>{children}</code>
          ),
        }}
      >
        {raw}
      </ReactMarkdown>
    </div>
  )
}

export default DocRenderer
