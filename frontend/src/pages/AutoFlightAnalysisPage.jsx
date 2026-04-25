import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card, Button, Space, message, Tag, Table,
  Upload, Select, Radio, Alert, Progress,
} from 'antd'
import {
  UploadOutlined, ReloadOutlined, PlayCircleOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { autoFlightAnalysisApi, sharedTsnApi, parseApi, protocolApi } from '../services/api'
import AppPageHeader from '../components/AppPageHeader'
import { isParseCompatibleSharedItem } from '../utils/sharedPlatform'
import {
  HISTORY_TASK_LIST_PAGE,
  HISTORY_TASK_LIST_PAGE_SIZE,
  newestFirstTaskNo,
} from '../utils/historyTaskList'
import dayjs from 'dayjs'

function AutoFlightAnalysisPage() {
  const navigate = useNavigate()
  const [taskList, setTaskList] = useState([])
  const [listTotal, setListTotal] = useState(0)
  const [listLoading, setListLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [dataSource, setDataSource] = useState('platform')
  const [sharedList, setSharedList] = useState([])
  const parseSharedList = useMemo(
    () => sharedList.filter(isParseCompatibleSharedItem),
    [sharedList],
  )
  const [platformId, setPlatformId] = useState(null)
  const [localFile, setLocalFile] = useState(null)
  const [parseTasks, setParseTasks] = useState([])
  const [parseTaskId, setParseTaskId] = useState(null)

  // MR4：TSN 网络协议版本（bundle）选择
  const [availableVersions, setAvailableVersions] = useState([])
  const [bundleVersionId, setBundleVersionId] = useState(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await protocolApi.listVersions()
        if (cancelled) return
        const items = (res.data?.items || res.data || []).filter(v =>
          !v.availability_status || v.availability_status === 'Available'
        )
        setAvailableVersions(items)
        if (items.length > 0) {
          setBundleVersionId((prev) => prev ?? items[0].id)
        }
      } catch {
        setAvailableVersions([])
      }
    })()
    return () => { cancelled = true }
  }, [])

  // 当选择"基于解析任务"且目标解析任务已绑定版本时，自动切到该版本（可被用户手动改回）
  useEffect(() => {
    if (!parseTaskId) return
    const task = parseTasks.find((t) => t.id === parseTaskId)
    const inherit = task?.protocol_version_id
    if (inherit) setBundleVersionId(inherit)
  }, [parseTaskId, parseTasks])

  const loadTaskList = useCallback(async () => {
    setListLoading(true)
    try {
      const res = await autoFlightAnalysisApi.listTasks(
        HISTORY_TASK_LIST_PAGE,
        HISTORY_TASK_LIST_PAGE_SIZE,
      )
      const items = res.data.items || []
      setTaskList(items)
      setListTotal(res.data?.total ?? items.length)
    } catch {
      message.error('加载任务列表失败')
    } finally {
      setListLoading(false)
    }
  }, [])

  const loadShared = useCallback(async () => {
    try {
      const res = await sharedTsnApi.list()
      setSharedList(res.data || [])
    } catch {
      setSharedList([])
    }
  }, [])

  const loadParseTasks = useCallback(async () => {
    try {
      const res = await parseApi.listTasks(1, 100)
      const tasks = (res.data.items || []).filter((x) => x.status === 'completed')
      setParseTasks(tasks)
    } catch {
      setParseTasks([])
    }
  }, [])

  useEffect(() => { loadTaskList() }, [loadTaskList])
  useEffect(() => { loadShared() }, [loadShared])
  useEffect(() => { loadParseTasks() }, [loadParseTasks])

  const runLocal = async () => {
    if (!localFile) {
      message.warning('请先选择文件')
      return
    }
    if (!bundleVersionId) {
      message.warning('请选择 TSN 网络协议版本')
      return
    }
    const formData = new FormData()
    formData.append('file', localFile)
    formData.append('bundle_version_id', String(bundleVersionId))
    setUploading(true)
    setUploadProgress(0)
    try {
      const res = await autoFlightAnalysisApi.upload(formData, (e) => {
        if (e.total) setUploadProgress(Math.round((e.loaded * 100) / e.total))
      })
      message.success(res.data.message || '已开始分析')
      loadTaskList()
      navigate(`/auto-flight-analysis/task/${res.data.task_id}`)
    } catch (err) {
      message.error(err.response?.data?.detail || '上传失败')
    } finally {
      setUploading(false)
      setUploadProgress(0)
    }
  }

  const runPlatform = async () => {
    if (!platformId) {
      message.warning('请选择平台数据')
      return
    }
    if (!bundleVersionId) {
      message.warning('请选择 TSN 网络协议版本')
      return
    }
    const formData = new FormData()
    formData.append('shared_tsn_id', String(platformId))
    formData.append('bundle_version_id', String(bundleVersionId))
    setUploading(true)
    try {
      const res = await autoFlightAnalysisApi.fromShared(formData)
      message.success(res.data.message || '已开始分析')
      loadTaskList()
      navigate(`/auto-flight-analysis/task/${res.data.task_id}`)
    } catch (err) {
      message.error(err.response?.data?.detail || '启动失败')
    } finally {
      setUploading(false)
    }
  }

  const runFromParse = async () => {
    if (!parseTaskId) {
      message.warning('请选择解析任务')
      return
    }
    const formData = new FormData()
    formData.append('parse_task_id', String(parseTaskId))
    // bundle_version_id 省略时后端会默认继承 ParseTask.protocol_version_id；
    // 这里若用户显式选择则传入，覆盖默认继承行为。
    if (bundleVersionId) {
      formData.append('bundle_version_id', String(bundleVersionId))
    }
    setUploading(true)
    try {
      const res = await autoFlightAnalysisApi.fromParseTask(formData)
      message.success(res.data.message || '已开始分析')
      loadTaskList()
      navigate(`/auto-flight-analysis/task/${res.data.task_id}`)
    } catch (err) {
      message.error(err.response?.data?.detail || '启动失败')
    } finally {
      setUploading(false)
    }
  }

  const historyColumns = [
    {
      title: '任务编号',
      key: 'task_no',
      width: 90,
      render: (_, __, index) => {
        const n = newestFirstTaskNo(
          listTotal,
          HISTORY_TASK_LIST_PAGE,
          HISTORY_TASK_LIST_PAGE_SIZE,
          index,
        )
        return <span style={{ fontFamily: 'monospace' }}>{n != null ? n : '—'}</span>
      },
    },
    { title: '任务名', dataIndex: 'name', key: 'name', ellipsis: true },
    {
      title: '来源',
      dataIndex: 'source_type',
      key: 'source_type',
      width: 110,
      render: (s) => {
        if (s === 'parse_task') return <Tag color="blue">解析任务</Tag>
        if (s === 'shared') return <Tag color="purple">平台共享</Tag>
        return <Tag>本地上传</Tag>
      },
    },
    {
      title: 'TSN 版本',
      key: 'bundle_version',
      width: 110,
      render: (_, record) => record.bundle_version_id ? (
        <Tag color="purple" title={`bundle v#${record.bundle_version_id}`}>
          {record.bundle_version_label || `v${record.bundle_version_id}`}
        </Tag>
      ) : <span style={{ color: '#71717a' }}>-</span>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (s) => {
        const color = s === 'completed' ? 'green' : s === 'failed' ? 'red' : s === 'processing' ? 'gold' : 'default'
        return <Tag color={color}>{s}</Tag>
      },
    },
    { title: '触底', dataIndex: 'touchdown_count', key: 'touchdown_count', width: 70 },
    { title: '稳态段', dataIndex: 'steady_count', key: 'steady_count', width: 80 },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (t) => (t ? dayjs(t).format('YYYY-MM-DD HH:mm:ss') : '-'),
    },
    {
      title: '操作',
      key: 'op',
      width: 100,
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => navigate(`/auto-flight-analysis/task/${record.id}`)}>
          查看
        </Button>
      ),
    },
  ]

  return (
    <div className="fade-in">
      <AppPageHeader
        variant="lite"
        icon={<ThunderboltOutlined />}
        eyebrow="专项分析"
        title="自动飞行性能分析"
        subtitle="上传 pcap / pcapng 或选择平台共享数据，对自动飞行相关子系统进行性能与一致性检查，并形成历史分析任务。"
      />
      <Card title="上传 pcap / pcapng 进行自动飞行性能分析" style={{ marginBottom: 24 }}>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <div>
            <span style={{ color: '#a1a1aa', marginRight: 12 }}>数据来源</span>
            <Radio.Group
              value={dataSource}
              onChange={(e) => {
                setDataSource(e.target.value)
                setLocalFile(null)
                setPlatformId(null)
                setParseTaskId(null)
              }}
            >
              <Radio.Button value="platform">平台共享数据</Radio.Button>
              <Radio.Button value="local">本地上传</Radio.Button>
              <Radio.Button value="parse">已有解析任务</Radio.Button>
            </Radio.Group>
          </div>

          <Space wrap align="center">
            <span style={{ color: '#a1a1aa' }}>TSN 网络协议版本</span>
            <Select
              value={bundleVersionId}
              onChange={setBundleVersionId}
              style={{ width: 260 }}
              placeholder="选择用于本次分析的 TSN 协议版本"
              notFoundContent="暂无可用版本"
              options={availableVersions.map(v => ({
                value: v.id,
                label: `${v.version || `v${v.id}`}${v.protocol_name ? ` · ${v.protocol_name}` : ''}`,
              }))}
            />
            {dataSource === 'parse' && parseTaskId && (
              <span style={{ color: '#71717a', fontSize: 12 }}>
                默认跟随所选解析任务版本
              </span>
            )}
          </Space>

          {dataSource === 'platform' ? (
            <div>
              <Select
                placeholder="选择平台共享数据"
                style={{ width: '100%', maxWidth: 560, marginBottom: 12 }}
                value={platformId}
                onChange={setPlatformId}
                allowClear
                showSearch
                optionFilterProp="label"
                options={parseSharedList.map((s) => ({
                  value: s.id,
                  label: `#${s.id} ${s.original_filename}${s.asset_label ? ` · ${s.asset_label}` : ''}${s.sortie_label ? ` · ${s.sortie_label}` : ''}`,
                }))}
              />
              {parseSharedList.length === 0 && (
                <Alert type="info" showIcon message="暂无可用的 PCAP 类平台数据" style={{ marginBottom: 12 }} />
              )}
              <Button type="primary" icon={<PlayCircleOutlined />} loading={uploading} disabled={!platformId} onClick={runPlatform}>
                使用平台数据开始分析
              </Button>
            </div>
          ) : dataSource === 'parse' ? (
            <div>
              <Select
                placeholder="选择已完成的解析任务"
                style={{ width: '100%', maxWidth: 560, marginBottom: 12 }}
                value={parseTaskId}
                onChange={setParseTaskId}
                allowClear
                showSearch
                optionFilterProp="label"
                options={parseTasks.map((t) => ({
                  value: t.id,
                  label: `#${t.id} ${t.filename}`,
                }))}
              />
              {parseTasks.length === 0 && (
                <Alert type="info" showIcon message="暂无已完成的解析任务" style={{ marginBottom: 12 }} />
              )}
              <Button type="primary" icon={<PlayCircleOutlined />} loading={uploading} disabled={!parseTaskId} onClick={runFromParse}>
                基于解析任务开始分析
              </Button>
            </div>
          ) : (
            <div>
              <Space wrap>
                <Upload
                  beforeUpload={(file) => {
                    setLocalFile(file)
                    return false
                  }}
                  onRemove={() => setLocalFile(null)}
                  maxCount={1}
                  accept=".pcap,.pcapng,.cap"
                  fileList={localFile ? [{ uid: '-1', name: localFile.name, status: 'done' }] : []}
                >
                  <Button icon={<UploadOutlined />}>选择文件</Button>
                </Upload>
                <Button type="primary" icon={<PlayCircleOutlined />} loading={uploading} disabled={!localFile} onClick={runLocal}>
                  {uploading ? `上传中 ${uploadProgress}%` : '开始分析'}
                </Button>
              </Space>
              {uploading && uploadProgress > 0 && (
                <Progress percent={uploadProgress} status="active" style={{ marginTop: 8, maxWidth: 400 }} />
              )}
            </div>
          )}

          <Button icon={<ReloadOutlined />} onClick={loadTaskList} loading={listLoading}>
            刷新列表
          </Button>
        </Space>
        <div style={{ marginTop: 12, color: '#a1a1aa', fontSize: 12 }}>
          分析触底垂直速度/过载三机一致性，以及稳态段高度偏差、水平偏差、速度控制偏差。
        </div>
      </Card>

      <Card title="历史任务" style={{ marginBottom: 24 }} extra={<Tag>{taskList.length} 条</Tag>}>
        <Table
          rowKey="id"
          size="small"
          loading={listLoading}
          dataSource={taskList}
          columns={historyColumns}
          pagination={false}
          scroll={{ x: 1090 }}
        />
      </Card>
    </div>
  )
}

export default AutoFlightAnalysisPage
