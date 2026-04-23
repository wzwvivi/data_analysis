import React, { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card, Upload, Button, Select, Form, message, Space, Tag, Row, Col, Alert, Divider, Table, Progress, Radio,
} from 'antd'
import {
  InboxOutlined, CloudUploadOutlined, ApiOutlined, DesktopOutlined, SettingOutlined,
} from '@ant-design/icons'
import { parseApi, protocolApi, sharedTsnApi, deviceProtocolApi } from '../services/api'
import { isParseCompatibleSharedItem } from '../utils/sharedPlatform'

const { Dragger } = Upload
const { Option } = Select

const FAMILY_LABELS = {
  irs: 'IRS 惯导协议',
  xpdr: 'S模式应答机协议',
  rtk: 'RTK 协议',
  fcc: 'FCC 飞控协议',
  atg: 'ATG 协议',
  fms: '飞管 FMS 协议',
  adc: '大气数据 ADC 协议',
  ra: '无线电高度表 RA 协议',
  turn: '前轮转弯系统协议',
  brake: '机轮刹车系统协议',
  bms800v: '800V 动力电池 BMS',
  bms270v: '270V&28V 动力电池 BMS',
  mcu: 'MCU 电推电驱 CAN',
  bpcu_empc: 'BPCU/EMPC 配电系统 CAN',
}

const DIRECTION_LABELS = {
  uplink: '上行数据',
  downlink: '下行数据',
  network: '网络交互数据',
}

const formatDirectionLabel = (direction) => {
  if (!direction) return '上行数据'
  const parts = String(direction).split('/').map(s => s.trim()).filter(Boolean)
  const mapped = parts.map(p => DIRECTION_LABELS[p] || p)
  return mapped.join('/')
}

const ATG_DEPENDENCY_SLOTS = [
  { key: 'FCC1', keywords: ['FCC1', '飞控1'], family: 'fcc' },
  { key: 'FCC2', keywords: ['FCC2', '飞控2'], family: 'fcc' },
  { key: 'FCC3', keywords: ['FCC3', '飞控3'], family: 'fcc' },
  { key: 'RTK1', keywords: ['RTK1', 'GPS1', '地基接收机1'], family: 'rtk' },
  { key: 'RTK2', keywords: ['RTK2', 'GPS2', '地基接收机2'], family: 'rtk' },
  { key: 'IRS1', keywords: ['IRS1', '惯导1'], family: 'irs' },
  { key: 'IRS2', keywords: ['IRS2', '惯导2'], family: 'irs' },
  { key: 'IRS3', keywords: ['IRS3', '惯导3'], family: 'irs' },
]

function UploadPage() {
  const navigate = useNavigate()
  const [form] = Form.useForm()

  const [netVersions, setNetVersions] = useState([])
  const [selectedVersion, setSelectedVersion] = useState(null)
  const [selectedVersionInfo, setSelectedVersionInfo] = useState(null)

  const [devices, setDevices] = useState([])
  const [selectedDevices, setSelectedDevices] = useState([])
  const [devicesLoading, setDevicesLoading] = useState(false)

  // Phase 7：上传页只保留"协议版本"这一个选择。
  // 用户选了设备 → 按设备的 parser_family 自动联带出该 family 的 Available 版本列表；
  // 每个 family 默认选最新；用户可以改；提交时只发 device_protocol_version_map。
  const [deviceProtocolVersionMap, setDeviceProtocolVersionMap] = useState({})
  // { parser_family: [ {id, device_name, version_name, activated_at, has_bundle, parser_key, ...}, ... ] }
  const [availableDeviceVersionsByFamily, setAvailableDeviceVersionsByFamily] = useState({})
  const [deviceVersionsLoading, setDeviceVersionsLoading] = useState(false)

  const [fileList, setFileList] = useState([])
  const [dataSource, setDataSource] = useState('platform') // platform 优先；local | platform
  const [sharedList, setSharedList] = useState([])
  const [platformFileId, setPlatformFileId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)

  useEffect(() => {
    loadVersions()
  }, [])

  const loadSharedTsn = async () => {
    try {
      const res = await sharedTsnApi.list()
      setSharedList(res.data || [])
    } catch {
      setSharedList([])
    }
  }

  useEffect(() => {
    loadSharedTsn()
  }, [])

  const parseSharedList = useMemo(
    () => sharedList.filter(isParseCompatibleSharedItem),
    [sharedList],
  )

  useEffect(() => {
    if (selectedVersion) {
      loadDevices(selectedVersion)
    } else {
      setDevices([])
      setSelectedDevices([])
      setDeviceProtocolVersionMap({})
    }
  }, [selectedVersion])

  const loadVersions = async () => {
    setLoading(true)
    try {
      const res = await protocolApi.listVersions()
      setNetVersions(res.data.items || [])
    } catch (err) {
      message.error('加载网络配置失败')
    } finally {
      setLoading(false)
    }
  }

  const loadDevices = async (versionId) => {
    setDevicesLoading(true)
    try {
      const res = await protocolApi.getDevices(versionId)
      setDevices(res.data.items || [])
    } catch (err) {
      message.error('加载设备列表失败')
      setDevices([])
    } finally {
      setDevicesLoading(false)
    }
  }

  const handleVersionChange = (versionId) => {
    setSelectedVersion(versionId)
    const version = netVersions.find(v => v.id === versionId)
    setSelectedVersionInfo(version)
    setSelectedDevices([])
    setDeviceProtocolVersionMap({})
  }

  const handleDeviceChange = (deviceNames) => {
    const selected = [...deviceNames]
    const hasAtg = selected.some(name => {
      const d = devices.find(x => x.device_name === name)
      return d?.protocol_family === 'atg'
    })

    if (hasAtg) {
      ATG_DEPENDENCY_SLOTS.forEach(slot => {
        const found = devices.find(d => {
          const n = (d.device_name || '').toUpperCase()
          return slot.keywords.some(k => n.includes(k.toUpperCase()))
        })
        if (found && !selected.includes(found.device_name)) {
          selected.push(found.device_name)
        }
      })
    }

    setSelectedDevices(selected)
  }

  const selectedPorts = useMemo(() => {
    if (!selectedDevices.length) return []
    const ports = new Set()
    selectedDevices.forEach(deviceName => {
      const device = devices.find(d => d.device_name === deviceName)
      if (device) device.ports.forEach(p => ports.add(p))
    })
    return Array.from(ports).sort((a, b) => a - b)
  }, [selectedDevices, devices])

  const hasSelectedATG = useMemo(
    () => selectedDevices.some(name => {
      const d = devices.find(x => x.device_name === name)
      return d?.protocol_family === 'atg'
    }),
    [selectedDevices, devices]
  )

  const selectedFamilies = useMemo(() => {
    const s = new Set()
    selectedDevices.forEach(name => {
      const d = devices.find(x => x.device_name === name)
      if (d?.protocol_family) s.add(d.protocol_family)
    })
    return s
  }, [selectedDevices, devices])

  // 按需拉取每个已选 parser_family 的 Available 设备协议版本，默认选最新
  useEffect(() => {
    const families = Array.from(selectedFamilies)
    if (families.length === 0) {
      setAvailableDeviceVersionsByFamily({})
      setDeviceProtocolVersionMap({})
      return
    }

    let cancelled = false
    const needed = families.filter(f => !(f in availableDeviceVersionsByFamily))
    if (needed.length === 0) {
      // 清理已废弃 family 的映射
      setDeviceProtocolVersionMap(prev => {
        const next = {}
        families.forEach(f => { if (prev[f] != null) next[f] = prev[f] })
        return next
      })
      return
    }

    setDeviceVersionsLoading(true)
    Promise.all(
      needed.map(f =>
        deviceProtocolApi.listAvailableVersions({ parserFamily: f })
          .then(res => [f, res.data?.items || []])
          .catch(() => [f, []])
      )
    ).then(results => {
      if (cancelled) return
      setAvailableDeviceVersionsByFamily(prev => {
        const next = { ...prev }
        results.forEach(([f, items]) => { next[f] = items })
        return next
      })
      setDeviceProtocolVersionMap(prev => {
        const next = { ...prev }
        results.forEach(([f, items]) => {
          if (next[f] == null && items.length > 0) {
            next[f] = items[0].id  // activated_at DESC 排序，第 0 个是最新
          }
        })
        // 清理已废弃 family
        Object.keys(next).forEach(k => {
          if (!families.includes(k)) delete next[k]
        })
        return next
      })
    }).finally(() => {
      if (!cancelled) setDeviceVersionsLoading(false)
    })
    return () => { cancelled = true }
  }, [selectedFamilies, availableDeviceVersionsByFamily])

  const handleDeviceProtocolVersionChange = (parserFamily, versionId) => {
    setDeviceProtocolVersionMap(prev => ({ ...prev, [parserFamily]: versionId }))
  }

  const atgRequiredFamilies = ['irs', 'rtk', 'fcc']
  const atgFamilyCoverage = useMemo(() => {
    const m = {}
    atgRequiredFamilies.forEach(f => {
      m[f] = selectedFamilies.has(f)
    })
    return m
  }, [selectedFamilies])

  // 每个选中的设备对应的 parser_family 是否都已绑定到一个 version
  // 同时，该 family 必须有至少一个 Available 版本（否则该行会 disable）
  const allDevicesConfigured = useMemo(() => {
    if (selectedDevices.length === 0) return false
    for (const name of selectedDevices) {
      const dev = devices.find(x => x.device_name === name)
      const fam = dev?.protocol_family
      if (!fam) return false
      if (deviceProtocolVersionMap[fam] == null) return false
    }
    return true
  }, [selectedDevices, devices, deviceProtocolVersionMap])

  // 整行要不要 disable：没有 Available 版本的 family（含 protocol_family 为空）
  const isDeviceRowDisabled = (dev) => {
    const fam = dev?.protocol_family
    if (!fam) return true
    const items = availableDeviceVersionsByFamily[fam] || []
    return items.length === 0
  }

  const handleUpload = async () => {
    if (dataSource === 'local' && fileList.length === 0) {
      message.warning('请先选择文件')
      return
    }
    if (dataSource === 'platform' && !platformFileId) {
      message.warning('请选择平台共享数据')
      return
    }
    if (!allDevicesConfigured) {
      message.warning('请为每个选中的设备选择协议版本（或先到「设备协议管理」激活一个）')
      return
    }

    setUploading(true)
    const formData = new FormData()
    if (dataSource === 'local') {
      formData.append('file', fileList[0])
    } else {
      formData.append('shared_tsn_id', String(platformFileId))
    }
    // Phase 7：只发 device_protocol_version_map（按 family 分组），后端根据
    // version.parser_key 反查 Python 实现；不再前端挑 parser。
    if (Object.keys(deviceProtocolVersionMap).length > 0) {
      formData.append(
        'device_protocol_version_map',
        JSON.stringify(deviceProtocolVersionMap),
      )
    }
    if (selectedVersion) formData.append('protocol_version_id', selectedVersion)
    if (selectedDevices.length > 0) formData.append('selected_devices', selectedDevices.join(','))
    if (selectedPorts.length > 0) formData.append('selected_ports', selectedPorts.join(','))

    try {
      const onProg = (progressEvent) => {
        if (progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total)
          setUploadProgress(percent)
        }
      }
      const res = dataSource === 'local'
        ? await parseApi.upload(formData, onProg)
        : await parseApi.uploadFromShared(formData, onProg)
      message.success('解析任务已创建')
      navigate(`/tasks/${res.data.task_id}`)
    } catch (err) {
      message.error(err.response?.data?.detail || '提交失败')
    } finally {
      setUploading(false)
      setUploadProgress(0)
    }
  }

  const uploadProps = {
    name: 'file',
    multiple: false,
    accept: '.pcapng,.pcap,.cap',
    fileList,
    beforeUpload: (file) => {
      const maxSize = 5 * 1024 * 1024 * 1024
      if (file.size > maxSize) {
        message.error(`文件大小超过限制（最大 5GB），当前文件: ${(file.size / 1024 / 1024 / 1024).toFixed(2)}GB`)
        return false
      }
      setFileList([file])
      return false
    },
    onRemove: () => {
      setFileList([])
      setUploadProgress(0)
    },
  }

  const deviceConfigColumns = [
    {
      title: '设备名称',
      dataIndex: 'device_name',
      key: 'device_name',
      render: (name) => (
        <Space>
          <DesktopOutlined style={{ color: '#d4a843' }} />
          <span style={{ fontWeight: 500 }}>{name}</span>
        </Space>
      ),
    },
    {
      title: '协议类型',
      dataIndex: 'protocol_family',
      key: 'protocol_family',
      width: 160,
      render: (family) => (
        family
          ? (
            <Space size={4}>
              <Tag style={{ background: hasSelectedATG && atgRequiredFamilies.includes(family) ? 'rgba(212, 168, 67, 0.15)' : 'rgba(139, 92, 246, 0.15)', borderColor: hasSelectedATG && atgRequiredFamilies.includes(family) ? '#d4a843' : 'rgba(139, 92, 246, 0.4)', color: hasSelectedATG && atgRequiredFamilies.includes(family) ? '#d4a843' : '#a78bfa' }}>
                {FAMILY_LABELS[family] || family}
              </Tag>
              {hasSelectedATG && atgRequiredFamilies.includes(family) && (
                <Tag style={{ background: 'rgba(240, 80, 80, 0.15)', borderColor: '#f05050', color: '#f05050' }}>ATG依赖</Tag>
              )}
            </Space>
          )
          : <Tag style={{ background: 'rgba(161, 161, 170, 0.1)', borderColor: '#52525b', color: '#a1a1aa' }}>未识别</Tag>
      ),
    },
    {
      title: '协议版本',
      key: 'protocol_version',
      width: 320,
      render: (_, record) => {
        const fam = record.protocol_family
        if (!fam) {
          return (
            <Tag style={{ background: 'rgba(240, 80, 80, 0.15)', borderColor: '#f05050', color: '#f05050' }}>
              未识别协议
            </Tag>
          )
        }
        const items = availableDeviceVersionsByFamily[fam] || []
        if (items.length === 0) {
          return (
            <Tag style={{ background: 'rgba(240, 80, 80, 0.15)', borderColor: '#f05050', color: '#f05050' }}>
              {deviceVersionsLoading ? '加载中…' : '无 Available 版本，请先激活'}
            </Tag>
          )
        }
        const currentId = deviceProtocolVersionMap[fam]
        const latestId = items[0]?.id
        return (
          <Space size={6} wrap>
            <Select
              placeholder="选择版本"
              style={{ width: 240 }}
              value={currentId}
              onChange={(val) => handleDeviceProtocolVersionChange(fam, val)}
              size="small"
              loading={deviceVersionsLoading}
              options={items.map(v => ({
                value: v.id,
                label: `${v.version_name}${v.has_bundle ? '' : ' · bundle 缺失'}`,
                title: v.parser_key ? `parser_key=${v.parser_key}` : undefined,
              }))}
            />
            {currentId && currentId === latestId && (
              <Tag style={{ background: 'rgba(95, 208, 104, 0.15)', borderColor: '#5fd068', color: '#5fd068' }}>
                最新
              </Tag>
            )}
          </Space>
        )
      },
    },
    {
      title: '端口',
      dataIndex: 'ports',
      key: 'ports',
      render: (ports) => (
        <span style={{ color: '#a1a1aa', fontSize: 12 }}>
          {ports?.length || 0} 个
        </span>
      ),
    },
  ]

  const selectedDeviceRows = useMemo(() => {
    return devices.filter(d => selectedDevices.includes(d.device_name))
  }, [devices, selectedDevices])

  return (
    <div className="fade-in">
      <Row gutter={24}>
        <Col span={16}>
          <Card
            title={
              <div>
                <Space align="center" size={10}>
                  <CloudUploadOutlined style={{ color: '#a78bfa', fontSize: 18 }} />
                  <span>
                    <span style={{ color: '#f4f4f5', fontWeight: 650, letterSpacing: '0.01em' }}>上传 TSN 数据包</span>
                  </span>
                </Space>
              </div>
            }
          >
            <div style={{ marginBottom: 16 }}>
              <span style={{ color: '#a1a1aa', marginRight: 12 }}>数据来源</span>
              <Radio.Group
                value={dataSource}
                onChange={(e) => {
                  setDataSource(e.target.value)
                  setFileList([])
                  setPlatformFileId(null)
                }}
              >
                <Radio.Button value="platform">平台共享数据</Radio.Button>
                <Radio.Button value="local">本地上传</Radio.Button>
              </Radio.Group>
            </div>

            {dataSource === 'platform' ? (
              <div style={{ marginBottom: 24 }}>
                <div style={{ color: '#a1a1aa', marginBottom: 8 }}>选择管理员上传的平台数据（近 2 天内有效）</div>
                <Select
                  placeholder="选择一条平台数据"
                  style={{ width: '100%' }}
                  value={platformFileId}
                  onChange={setPlatformFileId}
                  allowClear
                  showSearch
                  optionFilterProp="label"
                  options={parseSharedList.map((s) => ({
                    value: s.id,
                    label: `#${s.id} ${s.original_filename}${s.asset_label ? ` · ${s.asset_label}` : ''}${s.sortie_label ? ` · ${s.sortie_label}` : ''}`,
                  }))}
                />
                {parseSharedList.length === 0 && (
                  <Alert
                    type="info"
                    showIcon
                    style={{ marginTop: 12 }}
                    message="暂无可用于解析的 PCAP 类平台数据（需选择 TSN 交换机 / 网联 / 飞控记录器等类型）；视频仅归档不上屏"
                  />
                )}
              </div>
            ) : (
              <Dragger {...uploadProps} style={{ marginBottom: 24 }}>
                <p className="ant-upload-drag-icon">
                  <InboxOutlined style={{ color: '#d4a843', fontSize: 48 }} />
                </p>
                <p className="ant-upload-text" style={{ color: '#e4e4e7' }}>
                  点击或拖拽文件到此区域上传
                </p>
                <p className="ant-upload-hint" style={{ color: '#a1a1aa' }}>
                  支持 .pcapng, .pcap, .cap 格式的网络抓包文件
                </p>
              </Dragger>
            )}

            <Form form={form} layout="vertical">
              {/* 1. TSN网络配置 */}
              <Form.Item
                label={
                  <Space>
                    <ApiOutlined style={{ color: '#8b5cf6' }} />
                    <span style={{ fontWeight: 600, color: '#f4f4f5' }}>TSN网络配置</span>
                    <Tag style={{ background: 'rgba(139, 92, 246, 0.15)', borderColor: 'rgba(139, 92, 246, 0.4)', color: '#a78bfa' }}>必选</Tag>
                  </Space>
                }
                required
              >
                <Select
                  placeholder="请选择TSN网络配置版本"
                  onChange={handleVersionChange}
                  loading={loading}
                  style={{ width: '100%' }}
                  size="large"
                  value={selectedVersion}
                  allowClear
                  onClear={() => {
                    setSelectedVersion(null)
                    setSelectedVersionInfo(null)
                    setDevices([])
                    setSelectedDevices([])
                    setDeviceParserMap({})
                  }}
                >
                  {netVersions.map(v => (
                    <Option key={v.id} value={v.id}>
                      <Space>
                        <ApiOutlined style={{ color: '#8b5cf6' }} />
                        <span style={{ fontWeight: 500 }}>{v.protocol_name}</span>
                        <Tag style={{ background: 'rgba(161, 161, 170, 0.1)', borderColor: '#52525b', color: '#a1a1aa' }}>{v.version}</Tag>
                        <span style={{ color: '#a1a1aa', fontSize: 12 }}>
                          ({v.port_count} 个端口)
                        </span>
                      </Space>
                    </Option>
                  ))}
                </Select>
              </Form.Item>

              {selectedVersionInfo && (
                <Alert
                  type="info"
                  showIcon
                  icon={<ApiOutlined />}
                  style={{ marginBottom: 16 }}
                  message={
                    <Space direction="vertical" size={4}>
                      <div>
                        <strong>网络配置：</strong>{selectedVersionInfo.protocol_name} - {selectedVersionInfo.version}
                      </div>
                      <div style={{ color: '#a1a1aa', fontSize: 12 }}>
                        {selectedVersionInfo.port_count} 个端口定义
                        {selectedVersionInfo.source_file && ` | 来源: ${selectedVersionInfo.source_file}`}
                      </div>
                    </Space>
                  }
                />
              )}

              {/* 2. 选择设备 */}
              {selectedVersion && devices.length > 0 && (
                <Form.Item
                  label={
                    <Space>
                      <DesktopOutlined style={{ color: '#d4a843' }} />
                      <span>选择设备</span>
                      <Tag style={{ background: 'rgba(212, 168, 67, 0.12)', borderColor: '#d4a843', color: '#d4a843' }}>必选</Tag>
                    </Space>
                  }
                  required
                >
                  <Select
                    mode="multiple"
                    placeholder="选择要解析的设备"
                    onChange={handleDeviceChange}
                    loading={devicesLoading}
                    style={{ width: '100%' }}
                    size="large"
                    value={selectedDevices}
                    allowClear
                    maxTagCount={3}
                    maxTagPlaceholder={(omittedValues) => `+${omittedValues.length} 更多`}
                  >
                    {devices.map(device => (
                      <Option key={device.device_name} value={device.device_name}>
                        <Space>
                          <DesktopOutlined style={{ color: '#d4a843' }} />
                          <span style={{ fontWeight: 500 }}>{device.device_name}</span>
                          <Tag style={{ background: 'rgba(212, 168, 67, 0.12)', borderColor: '#d4a843', color: '#d4a843' }}>{device.port_count} 端口</Tag>
                          {device.protocol_family && (
                            <Tag style={{ background: 'rgba(139, 92, 246, 0.12)', borderColor: 'rgba(139, 92, 246, 0.35)', color: '#a78bfa' }}>{FAMILY_LABELS[device.protocol_family] || device.protocol_family}</Tag>
                          )}
                          <Tag style={{ background: 'rgba(95, 208, 104, 0.12)', borderColor: '#5fd068', color: '#5fd068' }}>{formatDirectionLabel(device.direction)}</Tag>
                        </Space>
                      </Option>
                    ))}
                  </Select>
                  {selectedDevices.length > 0 && (
                    <div style={{ color: '#a1a1aa', fontSize: 12, marginTop: 4 }}>
                      已选 {selectedDevices.length} 个设备，共 {selectedPorts.length} 个端口
                    </div>
                  )}
                </Form.Item>
              )}

              {hasSelectedATG && (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 16 }}
                  message="ATG 数据核对依赖协议"
                  description={
                    <Space wrap>
                      <span style={{ color: '#a1a1aa' }}>请同时关注并配置：</span>
                      <Tag style={{ background: atgFamilyCoverage.irs ? 'rgba(95, 208, 104, 0.15)' : 'rgba(240, 80, 80, 0.15)', borderColor: atgFamilyCoverage.irs ? '#5fd068' : '#f05050', color: atgFamilyCoverage.irs ? '#5fd068' : '#f05050' }}>IRS {atgFamilyCoverage.irs ? '已覆盖' : '未覆盖'}</Tag>
                      <Tag style={{ background: atgFamilyCoverage.rtk ? 'rgba(95, 208, 104, 0.15)' : 'rgba(240, 80, 80, 0.15)', borderColor: atgFamilyCoverage.rtk ? '#5fd068' : '#f05050', color: atgFamilyCoverage.rtk ? '#5fd068' : '#f05050' }}>RTK {atgFamilyCoverage.rtk ? '已覆盖' : '未覆盖'}</Tag>
                      <Tag style={{ background: atgFamilyCoverage.fcc ? 'rgba(95, 208, 104, 0.15)' : 'rgba(240, 80, 80, 0.15)', borderColor: atgFamilyCoverage.fcc ? '#5fd068' : '#f05050', color: atgFamilyCoverage.fcc ? '#5fd068' : '#f05050' }}>FCC {atgFamilyCoverage.fcc ? '已覆盖' : '未覆盖'}</Tag>
                    </Space>
                  }
                />
              )}

              {/* 3. 设备协议版本配置 */}
              {selectedDeviceRows.length > 0 && (
                <>
                  <Divider style={{ margin: '8px 0 16px' }} />
                  <Form.Item
                    label={
                      <Space>
                        <SettingOutlined style={{ color: '#5fd068' }} />
                        <span>设备解析版本配置</span>
                        <Tag style={{ background: 'rgba(95, 208, 104, 0.15)', borderColor: '#5fd068', color: '#5fd068' }}>为每个设备选择解析协议版本</Tag>
                      </Space>
                    }
                    required
                  >
                    <Table
                      dataSource={selectedDeviceRows}
                      columns={deviceConfigColumns}
                      rowKey="device_name"
                      pagination={false}
                      size="small"
                      style={{ marginBottom: 8 }}
                      rowClassName={(record) => (isDeviceRowDisabled?.(record) ? 'row-disabled' : '')}
                    />
                  </Form.Item>
                </>
              )}

              {/* 解析摘要 */}
              {allDevicesConfigured && (
                <Alert
                  type="success"
                  showIcon
                  style={{ marginBottom: 16 }}
                  message={
                    <Space direction="vertical" size={4}>
                      <div><strong>解析计划</strong></div>
                      {selectedDeviceRows.map(dev => {
                        const fam = dev.protocol_family
                        const versionId = fam ? deviceProtocolVersionMap[fam] : null
                        const items = fam ? (availableDeviceVersionsByFamily[fam] || []) : []
                        const ver = items.find(v => v.id === versionId)
                        return (
                          <div key={dev.device_name}>
                            <Tag style={{ background: 'rgba(212, 168, 67, 0.15)', borderColor: '#d4a843', color: '#d4a843' }}>{dev.device_name}</Tag>
                            →
                            <Tag style={{ background: 'rgba(95, 208, 104, 0.15)', borderColor: '#5fd068', color: '#5fd068' }}>
                              {ver
                                ? `${FAMILY_LABELS[fam] || fam} · ${ver.version_name}`
                                : `版本 #${versionId}`}
                            </Tag>
                            <span style={{ color: '#a1a1aa', fontSize: 12 }}>
                              ({dev.ports?.length || 0} 个端口)
                            </span>
                          </div>
                        )
                      })}
                    </Space>
                  }
                />
              )}

              <Form.Item style={{ marginTop: 16 }}>
                {uploading && dataSource === 'local' && uploadProgress > 0 && (
                  <Progress
                    percent={uploadProgress}
                    status="active"
                    style={{ marginBottom: 16 }}
                  />
                )}
                <Button
                  type="primary"
                  size="large"
                  icon={<CloudUploadOutlined />}
                  onClick={handleUpload}
                  loading={uploading}
                  disabled={
                    !allDevicesConfigured
                    || (dataSource === 'local' && fileList.length === 0)
                    || (dataSource === 'platform' && !platformFileId)
                  }
                  block
                >
                  {uploading
                    ? (dataSource === 'platform' ? '提交中...' : `上传中 ${uploadProgress}%`)
                    : '开始解析'}
                </Button>
              </Form.Item>
            </Form>
          </Card>
        </Col>

        <Col span={8}>
          <Card title="使用说明">
            <div style={{ color: '#a1a1aa', lineHeight: 2, fontSize: 13 }}>
              <p><strong style={{ color: '#d4d4d8' }}>1. 准备数据</strong></p>
              <p>上传从TSN网络抓取的 .pcapng 文件</p>

              <p style={{ marginTop: 16 }}><strong style={{ color: '#a78bfa' }}>2. 选择网络配置</strong></p>
              <p>选择TSN网络配置版本，定义端口和字段偏移位置</p>

              <p style={{ marginTop: 16 }}><strong style={{ color: '#d4a843' }}>3. 选择设备</strong></p>
              <p>选择要解析的目标设备</p>

              <p style={{ marginTop: 16 }}><strong style={{ color: '#5fd068' }}>4. 配置解析版本</strong></p>
              <p>为每个设备选择对应的解析协议版本。系统会自动匹配协议类型，只显示适用的版本。</p>

              <p style={{ marginTop: 16 }}><strong style={{ color: '#d4d4d8' }}>5. 开始解析</strong></p>
              <p>系统将按设备分配端口和解析器，精确解码每个设备的数据</p>
            </div>
          </Card>

          {netVersions.length === 0 && !loading && (
            <Card title="提示" style={{ marginTop: 16 }}>
              <div style={{ color: '#d4a843' }}>
                <p>暂无可用网络配置</p>
                <p style={{ fontSize: 12, color: '#a1a1aa' }}>
                  当前系统固定使用 TSN ICD v6.0.1，请联系管理员检查内置配置是否加载成功。
                </p>
              </div>
            </Card>
          )}

          <Card title="解析流程" style={{ marginTop: 16 }}>
            <div style={{ color: '#a1a1aa', fontSize: 13, lineHeight: 2 }}>
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
                <Tag style={{ background: 'rgba(139, 92, 246, 0.15)', borderColor: 'rgba(139, 92, 246, 0.4)', color: '#a78bfa', margin: 0, marginRight: 8 }}>网络配置</Tag>
                <span>定位端口和偏移</span>
              </div>
              <div style={{ borderLeft: '2px solid rgba(139, 92, 246, 0.3)', height: 16, marginLeft: 12 }} />
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
                <Tag style={{ background: 'rgba(212, 168, 67, 0.15)', borderColor: '#d4a843', color: '#d4a843', margin: 0, marginRight: 8 }}>设备选择</Tag>
                <span>筛选目标设备端口</span>
              </div>
              <div style={{ borderLeft: '2px solid rgba(139, 92, 246, 0.2)', height: 16, marginLeft: 12 }} />
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
                <Tag style={{ background: 'rgba(95, 208, 104, 0.15)', borderColor: '#5fd068', color: '#5fd068', margin: 0, marginRight: 8 }}>版本配置</Tag>
                <span>逐设备指定协议版本</span>
              </div>
              <div style={{ borderLeft: '2px solid rgba(139, 92, 246, 0.15)', height: 16, marginLeft: 12 }} />
              <div style={{ display: 'flex', alignItems: 'center' }}>
                <Tag style={{ background: 'rgba(139, 92, 246, 0.15)', borderColor: 'rgba(139, 92, 246, 0.4)', color: '#a78bfa', margin: 0, marginRight: 8 }}>输出结果</Tag>
                <span>按设备/端口分组</span>
              </div>
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default UploadPage
