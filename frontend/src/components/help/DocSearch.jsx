import React, { useMemo, useState } from 'react'
import { AutoComplete, Input } from 'antd'
import Fuse from 'fuse.js'

function DocSearch({ docs, onOpenDoc }) {
  const [value, setValue] = useState('')
  const [open, setOpen] = useState(false)

  const fuse = useMemo(() => new Fuse(docs, {
    threshold: 0.34,
    includeScore: true,
    keys: [
      { name: 'title', weight: 0.5 },
      { name: 'summary', weight: 0.3 },
      { name: 'raw', weight: 0.2 },
    ],
  }), [docs])

  const options = useMemo(() => {
    const q = value.trim()
    if (!q) return []
    return fuse.search(q, { limit: 8 }).map((item) => ({
      value: item.item.key,
      label: (
        <div>
          <div style={{ color: '#e4e4e7', fontWeight: 600 }}>{item.item.title}</div>
          <div style={{ color: '#a1a1aa', fontSize: 12 }}>{item.item.summary}</div>
        </div>
      ),
    }))
  }, [fuse, value])

  return (
    <AutoComplete
      value={value}
      options={options}
      onSelect={(docKey) => {
        setValue('')
        setOpen(false)
        onOpenDoc(docKey)
      }}
      onSearch={(text) => {
        setValue(text)
        setOpen(Boolean(text.trim()))
      }}
      open={open && options.length > 0}
      onBlur={() => setTimeout(() => setOpen(false), 120)}
      style={{ width: '100%' }}
    >
      <Input.Search
        placeholder="搜索文档、模块、关键词（例如：上传、端口、任务失败）"
        allowClear
        onPressEnter={() => {
          if (options[0]) onOpenDoc(options[0].value)
        }}
      />
    </AutoComplete>
  )
}

export default DocSearch
