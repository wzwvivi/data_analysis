import React, { useMemo } from 'react'

/**
 * 协议位图（32 位数据字）示意（位 1 = LSB / 先传输，从左到右显示 1..32）
 * 高亮：BNR 数据区间、离散位、特殊字段区间；底纹：标准区段 Label/SDI/Data/SSM/P
 */
const SEGMENTS = [
  { from: 1, to: 8, label: 'Label', color: 'rgba(88, 166, 255, 0.15)' },
  { from: 9, to: 10, label: 'SDI', color: 'rgba(163, 113, 247, 0.15)' },
  { from: 11, to: 29, label: 'Data', color: 'rgba(63, 185, 80, 0.12)' },
  { from: 30, to: 31, label: 'SSM', color: 'rgba(210, 153, 34, 0.15)' },
  { from: 32, to: 32, label: 'P', color: 'rgba(248, 81, 73, 0.15)' },
]

function parseBitSpec(spec) {
  if (spec == null || spec === '') return null
  const s = String(spec).trim()
  const m = s.match(/^(\d+)(?:\s*-\s*(\d+))?$/)
  if (!m) return null
  const a = parseInt(m[1], 10)
  const b = m[2] != null ? parseInt(m[2], 10) : a
  return { lo: Math.min(a, b), hi: Math.max(a, b) }
}

function collectRanges(label) {
  const ranges = []
  if (!label) return ranges
  const bnr = label.bnr_fields || []
  bnr.forEach((f, i) => {
    let db = f.data_bits
    if (typeof db === 'string' && db.includes(',')) {
      const p = db.split(/[,，]/).map((x) => parseInt(x.trim(), 10))
      if (p.length >= 2 && !Number.isNaN(p[0]) && !Number.isNaN(p[1])) db = p
    }
    if (Array.isArray(db) && db.length >= 2) {
      const lo = Math.min(db[0], db[1])
      const hi = Math.max(db[0], db[1])
      ranges.push({ lo, hi, kind: 'bnr', name: f.name || `BNR${i}` })
    }
  })
  const disc = label.discrete_bits || {}
  Object.keys(disc).forEach((k) => {
    const p = parseBitSpec(k)
    if (p) ranges.push({ lo: p.lo, hi: p.hi, kind: 'disc', name: String(k) })
  })
  const spec = label.special_fields || []
  spec.forEach((f, i) => {
    let bits = f.bits
    if (typeof bits === 'string' && bits.includes(',')) {
      const p = bits.split(/[,，]/).map((x) => parseInt(x.trim(), 10))
      if (p.length >= 2 && !Number.isNaN(p[0]) && !Number.isNaN(p[1])) bits = p
    }
    if (Array.isArray(bits) && bits.length >= 2) {
      const lo = Math.min(bits[0], bits[1])
      const hi = Math.max(bits[0], bits[1])
      ranges.push({ lo, hi, kind: 'spec', name: f.name || `SF${i}` })
    }
  })
  return ranges
}

function segmentAt(bit) {
  return SEGMENTS.find((s) => bit >= s.from && bit <= s.to)
}

export default function BitMapDisplay({ label }) {
  const ranges = useMemo(() => collectRanges(label), [label])

  const cells = useMemo(() => {
    const out = []
    for (let b = 1; b <= 32; b += 1) {
      const seg = segmentAt(b)
      const hits = ranges.filter((r) => b >= r.lo && b <= r.hi)
      let border = '1px solid #30363d'
      let bg = seg?.color || '#21262d'
      let fg = '#8b949e'
      if (hits.length) {
        const k = hits[0].kind
        if (k === 'bnr') {
          bg = 'rgba(63, 185, 80, 0.35)'
          fg = '#3fb950'
        } else if (k === 'disc') {
          bg = 'rgba(210, 153, 34, 0.4)'
          fg = '#d29922'
        } else {
          bg = 'rgba(163, 113, 247, 0.35)'
          fg = '#a371f7'
        }
        border = '1px solid #58a6ff'
      }
      out.push({ bit: b, bg, fg, border, seg: seg?.label, hint: hits.map((h) => h.name).join(', ') })
    }
    return out
  }, [ranges])

  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontSize: 12, color: '#8b949e', marginBottom: 6 }}>32 位字位图（1=LSB）</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
        {cells.map((c) => (
          <div
            key={c.bit}
            title={`位 ${c.bit} ${c.seg ? `· ${c.seg}` : ''}${c.hint ? ` · ${c.hint}` : ''}`}
            style={{
              width: 28,
              height: 36,
              background: c.bg,
              border: c.border,
              borderRadius: 4,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 10,
              color: c.fg,
            }}
          >
            <span>{c.bit}</span>
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8, fontSize: 11, color: '#6e7681' }}>
        {SEGMENTS.map((s) => (
          <span key={s.label}>
            <span
              style={{
                display: 'inline-block',
                width: 10,
                height: 10,
                borderRadius: 2,
                background: s.color,
                marginRight: 4,
                verticalAlign: 'middle',
              }}
            />
            {s.label} {s.from}-{s.to}
          </span>
        ))}
      </div>
    </div>
  )
}
