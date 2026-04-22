import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card, Button, Space, message, Tag, Table,
  Upload, Select, Radio, Alert, Progress,
} from 'antd'
import {
  UploadOutlined, ReloadOutlined, PlayCircleOutlined,
} from '@ant-design/icons'
import { standaloneFmsEventApi, sharedTsnApi, protocolApi } from '../services/api'
import { isParseCompatibleSharedItem } from '../utils/sharedPlatform'
import {
  HISTORY_TASK_LIST_PAGE,
  HISTORY_TASK_LIST_PAGE_SIZE,
  chronologicalTaskNo,
} from '../utils/historyTaskList'
import dayjs from 'dayjs'

/**
 * 独立事件分析：上传与历史列表。单任务结果在 /event-analysis/task/:id
 */
function StandaloneFmsEventPage() {
  const navigate = useNavigate()
  const [taskList, setTaskList] = useState([])
  const [listLoading, setListLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [ruleTemplate, setRuleTemplate] = useState('default_v1')
  const [dataSource, setDataSource] = useState('platform')
  const [sharedList, setSharedList] = useState([])
  const parseSharedList = useMemo(
    () => sharedList.filter(isParseCompatibleSharedItem),
    [sharedList],
  )
  const [platformId, setPlatformId] = useState(null)
  const [localFile, setLocalFile] = useState(null)

  // MR4：网络配置版本（bundle）选择
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
        if (items.length > 0 && !bundleVersionId) {
          setBundleVersionId(items[0].id)
        }
      } catch {
        setAvailableVersions([])
      }
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadTaskList = useCallback(async () => {
    setListLoading(true)
    try {
      const res = await standaloneFmsEventApi.listTasks(
        HISTORY_TASK_LIST_PAGE,
        HISTORY_TASK_LIST_PAGE_SIZE,
      )
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

  useEffect(() => {
    loadTaskList()
  }, [loadTaskList])

  useEffect(() => {
    loadShared()
  }, [loadShared])

  const runLocal = async () => {
    if (!localFile) {
      message.warning('请先选择文件')
      return
    }
    if (!bundleVersionId) {
      message.warning('请选择网络配置版本')
      return
    }
    const formData = new FormData()
    formData.append('file', localFile)
    formData.append('rule_template', ruleTemplate)
    formData.append('bundle_version_id', String(bundleVersionId))
    setUploading(true)
    setUploadProgress(0)
    try {
      const res = await standaloneFmsEventApi.upload(formData, (e) => {
        if (e.total) setUploadProgress(Math.round((e.loaded * 100) / e.total))
      })
      message.success(res.data.message || '已开始分析')
      loadTaskList()
      navigate(`/event-analysis/task/${res.data.task_id}`)
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
      message.warning('请选择网络配置版本')
      return
    }
    const formData = new FormData()
    formData.append('shared_tsn_id', String(platformId))
    formData.append('rule_template', ruleTemplate)
    formData.append('bundle_version_id', String(bundleVersionId))
    setUploading(true)
    try {
      const res = await standaloneFmsEventApi.fromShared(formData)
      message.success(res.data.message || '已开始分析')
      loadTaskList()
      navigate(`/event-analysis/task/${res.data.task_id}`)
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
        <span style={{ fontFamily: 'monospace' }}>
          {chronologicalTaskNo(HISTORY_TASK_LIST_PAGE, HISTORY_TASK_LIST_PAGE_SIZE, index)}
        </span>
      ),
    },
    { title: '文件', dataIndex: 'pcap_filename', key: 'pcap_filename', ellipsis: true },
    {
      title: '规则',
      dataIndex: 'rule_template',
      key: 'rule_template',
      width: 100,
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
        <Button type="link" size="small" onClick={() => navigate(`/event-analysis/task/${record.id}`)}>
          查看
        </Button>
      ),
    },
  ]

  return (
    <div className="fade-in">
      <Card title="上传 pcap / pcapng 进行飞管事件分析" style={{ marginBottom: 24 }}>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <div>
            <span style={{ color: '#a1a1aa', marginRight: 12 }}>数据来源</span>
            <Radio.Group
              value={dataSource}
              onChange={(e) => {
                setDataSource(e.target.value)
                setLocalFile(null)
                setPlatformId(null)
              }}
            >
              <Radio.Button value="platform">平台共享数据</Radio.Button>
              <Radio.Button value="local">本地上传</Radio.Button>
            </Radio.Group>
          </div>
          <Space wrap align="center">
            <span style={{ color: '#a1a1aa' }}>规则模板</span>
            <Select
              value={ruleTemplate}
              onChange={setRuleTemplate}
              style={{ width: 200 }}
              options={[{ value: 'default_v1', label: '航后检查单 (default_v1)' }]}
            />
            <span style={{ color: '#a1a1aa', marginLeft: 16 }}>网络配置版本</span>
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
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                loading={uploading}
                disabled={!platformId}
                onClick={runPlatform}
              >
                使用平台数据开始分析
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
                <Button
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  loading={uploading}
                  disabled={!localFile}
                  onClick={runLocal}
                >
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
          直接读取原始报文，无需先完成端口解析。分析在后台执行；开始分析后会进入任务详情页。
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
          scroll={{ x: 800 }}
        />
      </Card>
    </div>
  )
}

export default StandaloneFmsEventPage
