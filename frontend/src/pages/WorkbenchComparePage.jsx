import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  Card, Space, Button, Select, Tag, Table, Typography, Empty, Spin, Alert, message,
} from 'antd'
import { LeftOutlined, ReloadOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { sharedTsnApi, workbenchApi } from '../services/api'

const { Title, Text } = Typography

function parseSortieIds(search) {
  const qs = new URLSearchParams(search)
  const raw = qs.get('sortieIds') || ''
  return Array.from(new Set(raw.split(',').map((s) => Number(s)).filter((n) => Number.isFinite(n) && n > 0)))
}

export default function WorkbenchComparePage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [allSorties, setAllSorties] = useState([])
  const [selectedIds, setSelectedIds] = useState(() => parseSortieIds(location.search))
  const [matchedBySortie, setMatchedBySortie] = useState({}) // { sortieId: matchedResp }
  const [pickedTaskBySortie, setPickedTaskBySortie] = useState({}) // { sortieId: parseTaskId }
  const [loading, setLoading] = useState(false)
  const [dataBySortie, setDataBySortie] = useState({}) // { sortieId: { overview, events } }

  useEffect(() => {
    (async () => {
      try {
        const res = await sharedTsnApi.listSorties()
        setAllSorties((res.data || []).filter((s) => s.id && s.id > 0))
      } catch {
        setAllSorties([])
      }
    })()
  }, [])

  useEffect(() => {
    const qs = new URLSearchParams()
    if (selectedIds.length) qs.set('sortieIds', selectedIds.join(','))
    navigate({ pathname: '/workbench/compare', search: qs.toString() }, { replace: true })
  }, [selectedIds, navigate])

  const loadMatched = useCallback(async (sid) => {
    try {
      const res = await workbenchApi.listMatchedTasks(sid)
      setMatchedBySortie((prev) => ({ ...prev, [sid]: res.data }))
      const first = res.data?.parse_tasks?.[0]?.parse_task_id
      setPickedTaskBySortie((prev) => (prev[sid] ? prev : { ...prev, [sid]: first || null }))
    } catch {
      setMatchedBySortie((prev) => ({ ...prev, [sid]: null }))
    }
  }, [])

  useEffect(() => {
    selectedIds.forEach((sid) => {
      if (matchedBySortie[sid] === undefined) loadMatched(sid)
    })
  }, [selectedIds, matchedBySortie, loadMatched])

  const runCompare = useCallback(async () => {
    const pairs = selectedIds
      .map((sid) => ({ sid, tid: pickedTaskBySortie[sid] }))
      .filter((p) => p.tid)
    if (!pairs.length) {
      message.warning('请为每个架次选择一个解析任务')
      return
    }
    setLoading(true)
    try {
      const results = await Promise.all(pairs.map(async ({ sid, tid }) => {
        const [ovw, evt] = await Promise.all([
          workbenchApi.getOverview(sid, tid),
          workbenchApi.getEventsSummary(sid, tid),
        ])
        return [sid, { overview: ovw.data, events: evt.data, tid }]
      }))
      const next = {}
      results.forEach(([sid, v]) => { next[sid] = v })
      setDataBySortie(next)
    } catch {
      message.error('加载对比数据失败')
    } finally {
      setLoading(false)
    }
  }, [selectedIds, pickedTaskBySortie])

  const sortieLabel = useCallback((sid) => {
    const s = allSorties.find((x) => x.id === sid)
    return s?.sortie_label || `架次 #${sid}`
  }, [allSorties])

  const compareRows = useMemo(() => {
    const metrics = [
      { key: 'max_altitude_m', name: '最大高度 (m)', get: (d) => d.overview?.flight_profile?.max_altitude_m },
      { key: 'altitude_range_m', name: '高度变化 (m)', get: (d) => d.overview?.flight_profile?.altitude_range_m },
      { key: 'max_ground_speed', name: '最大地速 (m/s)', get: (d) => d.overview?.flight_profile?.max_ground_speed },
      { key: 'max_airspeed', name: '最大空速 (m/s)', get: (d) => d.overview?.flight_profile?.max_airspeed },
      { key: 'max_mach', name: '最大马赫', get: (d) => d.overview?.flight_profile?.max_mach },
      { key: 'duration', name: '时长', get: (d) => d.overview?.flight_info?.duration },
      { key: 'quality', name: '质量', get: (d) => d.overview?.quality },
      { key: 'dataset_count', name: '解析端口数', get: (d) => d.overview?.flight_info?.dataset_count },
      { key: 'phases', name: '飞行阶段数', get: (d) => (d.overview?.phases || []).length },
      { key: 'anomalies', name: '异常条数', get: (d) => (d.overview?.anomalies || []).length },
      { key: 'pitch_max', name: 'Pitch 最大 (°)', get: (d) => d.overview?.attitude?.pitch?.max },
      { key: 'pitch_min', name: 'Pitch 最小 (°)', get: (d) => d.overview?.attitude?.pitch?.min },
      { key: 'roll_max', name: 'Roll 最大 (°)', get: (d) => d.overview?.attitude?.roll?.max },
      { key: 'roll_min', name: 'Roll 最小 (°)', get: (d) => d.overview?.attitude?.roll?.min },
      { key: 'yaw_max', name: 'Yaw 最大 (°)', get: (d) => d.overview?.attitude?.heading?.max },
      { key: 'yaw_min', name: 'Yaw 最小 (°)', get: (d) => d.overview?.attitude?.heading?.min },
    ]
    const moduleMetrics = [
      { module: 'fms', label: 'FMS 失败数', count: 'fail' },
      { module: 'fms', label: 'FMS 通过数', count: 'pass' },
      { module: 'fcc', label: 'FCC 失败数', count: 'fail' },
      { module: 'fcc', label: 'FCC 通过数', count: 'pass' },
      { module: 'auto_flight', label: '触底事件数', count: 'touchdown' },
      { module: 'auto_flight', label: '稳态事件数', count: 'steady' },
      { module: 'compare', label: '比对缺失端口数', count: 'missing_ports' },
      { module: 'compare', label: '比对周期失败数', count: 'timing_fail' },
    ]
    const rows = []
    metrics.forEach((m) => {
      const row = { key: m.key, name: m.name }
      selectedIds.forEach((sid) => {
        const d = dataBySortie[sid]
        row[`s_${sid}`] = d ? (m.get(d) ?? '—') : '—'
      })
      rows.push(row)
    })
    moduleMetrics.forEach((mm) => {
      const key = `${mm.module}_${mm.count}`
      const row = { key, name: mm.label }
      selectedIds.forEach((sid) => {
        const d = dataBySortie[sid]
        const mod = d?.events?.modules?.find((x) => x.module === mm.module)
        row[`s_${sid}`] = mod?.counts?.[mm.count] ?? '—'
      })
      rows.push(row)
    })
    return rows
  }, [selectedIds, dataBySortie])

  const compareColumns = useMemo(() => [
    { title: '指标', dataIndex: 'name', width: 180, fixed: 'left' },
    ...selectedIds.map((sid) => ({
      title: (
        <Space direction="vertical" size={2} style={{ lineHeight: 1.2 }}>
          <Space size={6} wrap>
            <span>{sortieLabel(sid)}</span>
            <Button
              type="link"
              size="small"
              style={{ padding: 0, height: 'auto', fontSize: 11 }}
              onClick={() => navigate(`/workbench/${sid}`)}
            >
              打开架次
            </Button>
          </Space>
          <Text type="secondary" style={{ fontSize: 11 }}>
            任务 #{pickedTaskBySortie[sid] ?? '—'}
          </Text>
        </Space>
      ),
      dataIndex: `s_${sid}`,
      render: (v) => (
        <span style={{ fontVariantNumeric: 'tabular-nums' }}>{String(v ?? '—')}</span>
      ),
    })),
  ], [selectedIds, sortieLabel, pickedTaskBySortie, navigate])

  const eventCountChartOption = useMemo(() => {
    if (!selectedIds.length) return null
    const categories = ['FMS 失败', 'FCC 失败', '触底', '稳态', '比对缺失端口', '比对周期失败']
    const series = selectedIds.map((sid) => {
      const d = dataBySortie[sid]
      const modFor = (m) => d?.events?.modules?.find((x) => x.module === m)
      return {
        name: sortieLabel(sid),
        type: 'bar',
        data: [
          modFor('fms')?.counts?.fail ?? 0,
          modFor('fcc')?.counts?.fail ?? 0,
          modFor('auto_flight')?.counts?.touchdown ?? 0,
          modFor('auto_flight')?.counts?.steady ?? 0,
          modFor('compare')?.counts?.missing_ports ?? 0,
          modFor('compare')?.counts?.timing_fail ?? 0,
        ],
      }
    })
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      legend: { textStyle: { color: '#d4d4d8' } },
      grid: { left: 56, right: 16, top: 40, bottom: 48 },
      xAxis: { type: 'category', data: categories, axisLabel: { color: '#9393a1' } },
      yAxis: { type: 'value', axisLabel: { color: '#9393a1' } },
      series,
    }
  }, [selectedIds, dataBySortie, sortieLabel])

  const sortieOptions = allSorties.map((s) => ({ value: s.id, label: s.sortie_label }))

  return (
    <div className="fade-in">
      <Space style={{ marginBottom: 8 }} align="center" wrap>
        <Button type="link" icon={<LeftOutlined />} onClick={() => navigate('/workbench')}>返回架次列表</Button>
        <Title level={4} style={{ margin: 0 }}>跨架次对比</Title>
        <Tag color="purple">架次级复盘</Tag>
      </Space>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="本页按架次汇总指标、事件与异常，用于复盘对比不同架次的表现差异。"
        description="如需对比「两次解析任务」本身的数据包差异（时间同步、端口覆盖、周期抖动等），请使用侧栏「专项分析 → TSN 异常检查」。"
      />

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space wrap align="start">
            <Text type="secondary">参与对比的架次（至少 2 个）：</Text>
            <Select
              mode="multiple"
              style={{ minWidth: 360 }}
              placeholder="选择多个架次"
              value={selectedIds}
              onChange={(ids) => setSelectedIds(ids)}
              options={sortieOptions}
              showSearch
              optionFilterProp="label"
              maxTagCount="responsive"
            />
            <Button type="primary" icon={<ReloadOutlined />} onClick={runCompare} disabled={selectedIds.length < 2}>
              加载/刷新对比
            </Button>
          </Space>

          {selectedIds.map((sid) => {
            const m = matchedBySortie[sid]
            const opts = (m?.parse_tasks || []).map((t) => ({
              value: t.parse_task_id,
              label: `#${t.parse_task_id} ${t.filename || ''} (${t.status})`,
            }))
            return (
              <Space key={sid} wrap>
                <Tag color="blue">{sortieLabel(sid)}</Tag>
                <Text type="secondary">解析任务</Text>
                <Select
                  style={{ minWidth: 320 }}
                  placeholder="选择该架次下的解析任务"
                  value={pickedTaskBySortie[sid]}
                  onChange={(v) => setPickedTaskBySortie((prev) => ({ ...prev, [sid]: v }))}
                  options={opts}
                  allowClear
                  notFoundContent={m ? '该架次无候选解析任务' : '加载中…'}
                />
                <Button size="small" onClick={() => setSelectedIds((ids) => ids.filter((x) => x !== sid))}>
                  移除
                </Button>
              </Space>
            )
          })}
        </Space>
      </Card>

      {selectedIds.length < 2 && (
        <Alert type="info" showIcon message="请至少选择 2 个架次进行对比" style={{ marginBottom: 16 }} />
      )}

      <Card size="small" title="指标对比" style={{ marginBottom: 16 }}>
        <Spin spinning={loading}>
          {Object.keys(dataBySortie).length === 0 ? (
            <Empty description="点击「加载/刷新对比」开始" />
          ) : (
            <Table
              size="small"
              pagination={false}
              rowKey="key"
              dataSource={compareRows}
              columns={compareColumns}
              scroll={{ x: 'max-content' }}
            />
          )}
        </Spin>
      </Card>

      <Card size="small" title="事件数量对比（柱状）">
        {!eventCountChartOption || Object.keys(dataBySortie).length === 0 ? (
          <Empty description="暂无数据" />
        ) : (
          <ReactECharts option={eventCountChartOption} style={{ height: 360 }} notMerge lazyUpdate theme="dark" />
        )}
      </Card>
    </div>
  )
}
