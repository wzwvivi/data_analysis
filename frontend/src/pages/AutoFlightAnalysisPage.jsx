import React, { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card, Button, Space, message, Tag, Table,
  Upload, Select, Radio, Alert, Progress,
} from 'antd'
import {
  UploadOutlined, ReloadOutlined, PlayCircleOutlined,
} from '@ant-design/icons'
import { autoFlightAnalysisApi, sharedTsnApi, parseApi } from '../services/api'
import dayjs from 'dayjs'

function AutoFlightAnalysisPage() {
  const navigate = useNavigate()
  const [taskList, setTaskList] = useState([])
  const [listLoading, setListLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [dataSource, setDataSource] = useState('platform')
  const [sharedList, setSharedList] = useState([])
  const [platformId, setPlatformId] = useState(null)
  const [localFile, setLocalFile] = useState(null)
  const [parseTasks, setParseTasks] = useState([])
  const [parseTaskId, setParseTaskId] = useState(null)

  const loadTaskList = useCallback(async () => {
    setListLoading(true)
    try {
      const res = await autoFlightAnalysisApi.listTasks(1, 50)
      setTaskList(res.data.items || [])
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
    const formData = new FormData()
    formData.append('file', localFile)
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
    const formData = new FormData()
    formData.append('shared_tsn_id', String(platformId))
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
      render: (_, __, index) => (
        <span style={{ fontFamily: 'monospace' }}>{index + 1}</span>
      ),
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
                options={sharedList.map((s) => ({
                  value: s.id,
                  label: `#${s.id} ${s.original_filename}${s.experiment_label ? ` — ${s.experiment_label}` : ''}`,
                }))}
              />
              {sharedList.length === 0 && (
                <Alert type="info" showIcon message="暂无平台数据，请管理员上传" style={{ marginBottom: 12 }} />
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
          scroll={{ x: 980 }}
        />
      </Card>
    </div>
  )
}

export default AutoFlightAnalysisPage
