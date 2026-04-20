import React, {
  useEffect, useLayoutEffect, useMemo, useRef, useState,
} from 'react'
import { createPortal } from 'react-dom'
import {
  CircleMarker,
  LayerGroup,
  MapContainer,
  Polyline,
  TileLayer,
  useMap,
} from 'react-leaflet'
import L from 'leaflet'

/** 轨迹范围 → 地图上点击选中点的最大允许偏差（约等于原 ECharts 图的选取半径） */
function pickThresholdDegrees(path) {
  if (!path?.length) return 1e-5
  let minLo = Infinity
  let maxLo = -Infinity
  let minLa = Infinity
  let maxLa = -Infinity
  for (const [lo, la] of path) {
    minLo = Math.min(minLo, lo)
    maxLo = Math.max(maxLo, lo)
    minLa = Math.min(minLa, la)
    maxLa = Math.max(maxLa, la)
  }
  const span = Math.max(maxLo - minLo, maxLa - minLa) || 0.01
  return Math.max(span * 0.03, 5e-6)
}

const PALETTE = ['#312e81', '#6366f1', '#a7f3d0', '#fde047', '#fb923c']

function parseRgb(hex) {
  const h = hex.replace('#', '')
  return {
    r: parseInt(h.slice(0, 2), 16),
    g: parseInt(h.slice(2, 4), 16),
    b: parseInt(h.slice(4, 6), 16),
  }
}

function rgbToHex({ r, g, b }) {
  const x = (n) => Math.max(0, Math.min(255, n)).toString(16).padStart(2, '0')
  return `#${x(r)}${x(g)}${x(b)}`
}

function gradientColorFromT01(t01) {
  const t = Math.max(0, Math.min(1, t01))
  const max = PALETTE.length - 1
  const x = t * max
  const i = Math.min(Math.floor(x), max - 1)
  const f = x - i
  const a = parseRgb(PALETTE[i])
  const b = parseRgb(PALETTE[i + 1])
  return rgbToHex({
    r: a.r + (b.r - a.r) * f,
    g: a.g + (b.g - a.g) * f,
    b: a.b + (b.b - a.b) * f,
  })
}

function FitBounds({ latLngs }) {
  const map = useMap()
  useEffect(() => {
    if (!latLngs?.length) return
    if (latLngs.length === 1) {
      map.setView(latLngs[0], 16, { animate: false })
      return
    }
    const b = L.latLngBounds(latLngs)
    map.fitBounds(b, { padding: [40, 40], maxZoom: 17, animate: false })
  }, [map, latLngs])
  return null
}

/** 列表 / 滑块改选中索引时，将视图平移到该点（保持缩放；短时防抖减轻滑块连拖时的抖动） */
/** 轨迹采样点密度上限（过多 CircleMarker 会拖慢交互） */
const SAMPLE_MARKERS_CAP = 1800

function TrajectorySampleMarkers({
  path,
  selectedIdx,
  onSelectIdx,
  maxMarkers = SAMPLE_MARKERS_CAP,
}) {
  const { stride, indices } = useMemo(() => {
    const n = path?.length || 0
    if (n === 0) return { stride: 1, indices: [] }
    const s = n <= maxMarkers ? 1 : Math.ceil(n / maxMarkers)
    const idxs = []
    for (let i = 0; i < n; i += s) idxs.push(i)
    const last = n - 1
    if (last > 0 && idxs[idxs.length - 1] !== last) idxs.push(last)
    return { stride: s, indices: idxs }
  }, [path, maxMarkers])

  if (!path?.length) return null

  return (
    <>
      {indices.map((i) => {
        const [lon, lat] = path[i]
        const isSel = selectedIdx === i
        const isStart = i === 0
        const isEndPt = i === path.length - 1 && path.length > 1
        const small = { r: 4, c: 'rgba(226,232,240,0.9)', f: 'rgba(148,163,184,0.55)', w: 1, o: 0.75 }
        const startM = { r: 8, c: '#ecfccb', f: '#22c55e', w: 2, o: 1 }
        const endM = { r: 8, c: '#fecaca', f: '#ef4444', w: 2, o: 1 }
        const m = isStart ? startM : isEndPt ? endM : small
        return (
          <CircleMarker
            key={`s-${i}-${stride}`}
            pane="samplePointsPane"
            center={[lat, lon]}
            radius={isSel ? 7 : m.r}
            pathOptions={{
              color: isSel ? '#fde047' : m.c,
              fillColor: isSel ? '#facc15' : m.f,
              fillOpacity: isSel ? 0.95 : m.o,
              weight: isSel ? 3 : m.w,
            }}
            eventHandlers={{
              click: (e) => {
                L.DomEvent.stopPropagation(e)
                onSelectIdx(i)
              },
            }}
          />
        )
      })}
    </>
  )
}

function PanToSelected({ latLngs, selectedIdx }) {
  const map = useMap()
  useEffect(() => {
    if (selectedIdx == null || !latLngs?.length) return
    const ll = latLngs[selectedIdx]
    if (!ll) return
    const id = window.setTimeout(() => {
      map.panTo(ll, { animate: true })
    }, 100)
    return () => window.clearTimeout(id)
  }, [map, latLngs, selectedIdx])
  return null
}

function EnsurePane({ name, zIndex }) {
  const map = useMap()
  useLayoutEffect(() => {
    if (map.getPane(name)) return
    map.createPane(name)
    const el = map.getPane(name)
    if (el) el.style.zIndex = String(zIndex)
  }, [map, name, zIndex])
  return null
}

function nearestTrajectoryIndex(latlng, path) {
  const { lat, lng } = latlng
  let best = 0
  let bestD = Infinity
  for (let i = 0; i < path.length; i += 1) {
    const p = path[i]
    const d = (p[0] - lng) ** 2 + (p[1] - lat) ** 2
    if (d < bestD) {
      bestD = d
      best = i
    }
  }
  return { idx: best, distDeg: Math.sqrt(bestD) }
}

function MapClickSelect({ path, maxPickDeg, onSelect }) {
  const map = useMap()
  useEffect(() => {
    if (!path?.length) return undefined
    const handler = (e) => {
      const { idx, distDeg } = nearestTrajectoryIndex(e.latlng, path)
      if (distDeg > maxPickDeg) return
      onSelect(idx)
    }
    map.on('click', handler)
    return () => { map.off('click', handler) }
  }, [map, path, maxPickDeg, onSelect])
  return null
}

/** 悬停到轨迹附近时，在鼠标旁展示最近采样点的经纬度与 ENU 速度、地速 */
function TrajectoryHoverReadout({
  path,
  eastVals,
  northVals,
  groundSpeedVals,
  beijingTimeStrs,
  maxPickDeg,
}) {
  const map = useMap()
  const [tip, setTip] = useState(null)
  const rafRef = useRef(0)

  useEffect(() => {
    setTip(null)
  }, [path])

  useEffect(() => {
    if (!path?.length) return undefined
    const thr = maxPickDeg

    const flush = (e) => {
      const { idx, distDeg } = nearestTrajectoryIndex(e.latlng, path)
      if (distDeg > thr) {
        setTip(null)
        return
      }
      const oe = e.originalEvent
      setTip({
        idx,
        left: oe.clientX + 14,
        top: oe.clientY - 8,
      })
    }

    const onMove = (e) => {
      if (rafRef.current) return
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = 0
        flush(e)
      })
    }

    const onOut = () => {
      setTip(null)
    }

    map.on('mousemove', onMove)
    map.on('mouseout', onOut)
    return () => {
      map.off('mousemove', onMove)
      map.off('mouseout', onOut)
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [map, path, maxPickDeg])

  if (!tip) return null

  const lon = path[tip.idx][0]
  const lat = path[tip.idx][1]
  const ve = eastVals?.[tip.idx]
  const vn = northVals?.[tip.idx]
  let gs = groundSpeedVals?.[tip.idx]
  if (gs == null && ve != null && vn != null && Number.isFinite(ve) && Number.isFinite(vn)) {
    gs = Math.sqrt(ve * ve + vn * vn)
  }

  const fmt = (v, decimals = 4) => {
    if (v == null || !Number.isFinite(Number(v))) return '—'
    return Number(v).toFixed(decimals)
  }

  const panel = (
    <div
      style={{
        position: 'fixed',
        left: tip.left,
        top: tip.top,
        transform: 'translate(0, -100%)',
        pointerEvents: 'none',
        zIndex: 10000,
        background: 'rgba(15,23,42,0.95)',
        border: '1px solid rgba(148,163,184,0.4)',
        borderRadius: 8,
        padding: '8px 11px',
        fontSize: 11,
        color: '#e4e4e7',
        lineHeight: 1.5,
        whiteSpace: 'nowrap',
        boxShadow: '0 6px 18px rgba(0,0,0,0.38)',
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 6, color: '#fef08a' }}>
        北京时间{' '}
        {beijingTimeStrs?.[tip.idx] ?? '—'}
      </div>
      <div>经度 {fmt(lon, 6)}°</div>
      <div>纬度 {fmt(lat, 6)}°</div>
      <div>东向速度 {fmt(ve)} m/s</div>
      <div>北向速度 {fmt(vn)} m/s</div>
      <div>地速 √(东²+北²) {fmt(gs)} m/s</div>
    </div>
  )

  return createPortal(panel, document.body)
}

function ResizeInvalidate({ trigger }) {
  const map = useMap()
  useEffect(() => {
    map.invalidateSize()
    const t = window.setTimeout(() => map.invalidateSize(), 120)
    return () => window.clearTimeout(t)
  }, [map, trigger])
  return null
}

/**
 * path: [[lon, lat], ...]
 * groundSpeedVals: √(东向²+北向²) 与 path 等长；有有效值时按地速着色，否则按采样序号着色
 */
export default function MapTrajectoryLeaflet({
  path,
  groundSpeedVals,
  eastVals,
  northVals,
  beijingTimeStrs,
  selectedTrajIdx,
  onSelectIdx,
  height = 460,
  showSampleMarkers = true,
}) {
  const latLngs = useMemo(
    () => (path || []).map(([lon, lat]) => L.latLng(lat, lon)),
    [path],
  )

  const maxPickDeg = useMemo(() => pickThresholdDegrees(path), [path])

  const { segments, vmin, vmax, colorByGroundSpeed } = useMemo(() => {
    const n = path?.length || 0
    if (n < 2) return { segments: [], vmin: 0, vmax: 1, colorByGroundSpeed: false }
    const finite = (groundSpeedVals || []).filter((s) => s != null && Number.isFinite(s))
    const byGs = finite.length > 0
    let vmin
    let vmax
    if (byGs) {
      vmin = Math.min(...finite)
      vmax = Math.max(...finite)
      if (!(vmax > vmin)) vmax = vmin + 1e-9
    }
    const segs = []
    for (let i = 0; i < n - 1; i += 1) {
      const p0 = path[i]
      const p1 = path[i + 1]
      let t01
      if (byGs) {
        const s0 = groundSpeedVals[i]
        const s1 = groundSpeedVals[i + 1]
        const m =
          (s0 != null && Number.isFinite(s0) ? s0 : vmin) +
          (s1 != null && Number.isFinite(s1) ? s1 : vmin)
        const mid = m / 2
        t01 = (mid - vmin) / (vmax - vmin)
      } else {
        t01 = (i + 0.5) / Math.max(n - 1, 1)
      }
      const color = gradientColorFromT01(t01)
      segs.push({
        key: i,
        positions: [
          [p0[1], p0[0]],
          [p1[1], p1[0]],
        ],
        color,
      })
    }
    return { segments: segs, vmin, vmax, colorByGroundSpeed: byGs }
  }, [path, groundSpeedVals])

  const selectedIdx = selectedTrajIdx

  const boundsCenter = useMemo(() => {
    if (!latLngs.length) return L.latLng(34, 108)
    if (latLngs.length === 1) return latLngs[0]
    return L.latLngBounds(latLngs).getCenter()
  }, [latLngs])

  if (!path?.length) return null

  return (
    <div style={{ borderRadius: 10, overflow: 'hidden', border: '1px solid rgba(70,70,82,0.45)' }}>
      <MapContainer
        center={boundsCenter}
        zoom={13}
        style={{ height, width: '100%', background: '#1a1d29' }}
        scrollWheelZoom
      >
        <ResizeInvalidate trigger={path?.length} />
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds latLngs={latLngs} />
        <MapClickSelect path={path} maxPickDeg={maxPickDeg} onSelect={onSelectIdx} />
        <TrajectoryHoverReadout
          path={path}
          eastVals={eastVals}
          northVals={northVals}
          groundSpeedVals={groundSpeedVals}
          beijingTimeStrs={beijingTimeStrs}
          maxPickDeg={maxPickDeg}
        />
        <PanToSelected latLngs={latLngs} selectedIdx={selectedIdx} />
        {/* 整条轨迹底层连线，保证折线接缝处视觉连续（线宽约为原先一半） */}
        {latLngs.length >= 2 && (
          <Polyline
            positions={latLngs}
            pathOptions={{
              color: '#0f172a',
              weight: 5,
              opacity: 0.5,
              lineCap: 'round',
              lineJoin: 'round',
            }}
          />
        )}
        <LayerGroup>
          {segments.map((s) => (
            <Polyline
              key={s.key}
              positions={s.positions}
              pathOptions={{
                color: s.color,
                weight: 2,
                opacity: 0.95,
                lineCap: 'round',
                lineJoin: 'round',
              }}
            />
          ))}
        </LayerGroup>
        {showSampleMarkers && (
          <LayerGroup>
            <EnsurePane name="samplePointsPane" zIndex={620} />
            <TrajectorySampleMarkers
              path={path}
              selectedIdx={selectedIdx}
              onSelectIdx={onSelectIdx}
            />
          </LayerGroup>
        )}
        {!showSampleMarkers && (
          <>
            <CircleMarker
              center={[path[0][1], path[0][0]]}
              radius={9}
              pathOptions={{
                color: '#ecfccb',
                fillColor: '#22c55e',
                fillOpacity: 1,
                weight: 2,
              }}
              eventHandlers={{
                click: (e) => {
                  L.DomEvent.stopPropagation(e)
                  onSelectIdx(0)
                },
              }}
            />
            <CircleMarker
              center={[path[path.length - 1][1], path[path.length - 1][0]]}
              radius={9}
              pathOptions={{
                color: '#fecaca',
                fillColor: '#ef4444',
                fillOpacity: 1,
                weight: 2,
              }}
              eventHandlers={{
                click: (e) => {
                  L.DomEvent.stopPropagation(e)
                  onSelectIdx(path.length - 1)
                },
              }}
            />
          </>
        )}
        {selectedIdx != null && path[selectedIdx] && (
          <>
            <EnsurePane name="selectedFocusPane" zIndex={650} />
            <CircleMarker
              pane="selectedFocusPane"
              center={[path[selectedIdx][1], path[selectedIdx][0]]}
              radius={28}
              pathOptions={{
                color: '#fbbf24',
                fillColor: '#fbbf24',
                fillOpacity: 0.18,
                weight: 4,
                opacity: 1,
              }}
              eventHandlers={{
                click: (e) => {
                  L.DomEvent.stopPropagation(e)
                  onSelectIdx(selectedIdx)
                },
              }}
            />
            <CircleMarker
              pane="selectedFocusPane"
              center={[path[selectedIdx][1], path[selectedIdx][0]]}
              radius={12}
              pathOptions={{
                color: '#fff',
                fillColor: '#facc15',
                fillOpacity: 1,
                weight: 4,
              }}
              eventHandlers={{
                click: (e) => {
                  L.DomEvent.stopPropagation(e)
                  onSelectIdx(selectedIdx)
                },
              }}
            />
          </>
        )}
      </MapContainer>
      <div
        style={{
          padding: '8px 12px',
          fontSize: 11,
          color: '#a1a1aa',
          background: 'rgba(15,23,42,0.65)',
          borderTop: '1px solid rgba(70,70,82,0.35)',
          display: 'flex',
          flexWrap: 'wrap',
          gap: 12,
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <span>
          加载后自动居中缩放至整条轨迹；颜色按地速渐变（优先 √(东²+北²) 或解析标量速度；缺列或数值近似常数时用路程/时间推算地速）。
          深色底层保证连线闭合；沿途小圆点为采样点（极密轨迹自动抽稀显示）；点击圆点或轨迹附近可选点。鼠标靠近轨迹可看速度与北京时间。
          {!colorByGroundSpeed && (
            <> 当前无法得到有效地速序列时，颜色沿采样序号渐变。</>
          )}
        </span>
        <span style={{ opacity: 0.85 }}>
          {colorByGroundSpeed && vmin != null && vmax != null && (
            <>
              地速范围 {vmin.toFixed(3)} … {vmax.toFixed(3)} m/s
            </>
          )}
        </span>
      </div>
    </div>
  )
}
