import React, { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card, Upload, Button, Select, Form, message, Space, Tag, Row, Col, Alert, Divider, Table, Progress, Radio,
} from 'antd'
import {
  InboxOutlined, CloudUploadOutlined, ApiOutlined, DesktopOutlined, SettingOutlined
} from '@ant-design/icons'
import { parseApi, protocolApi, sharedTsnApi } from '../services/api'

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

  // { deviceName: parserProfileId }
  const [deviceParserMap, setDeviceParserMap] = useState({})

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

  useEffect(() => {
    if (selectedVersion) {
      loadDevices(selectedVersion)
    } else {
      setDevices([])
      setSelectedDevices([])
      setDeviceParserMap({})
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
    setDeviceParserMap({})
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
    const newMap = {}
    selected.forEach(name => {
      if (deviceParserMap[name] !== undefined) {
        newMap[name] = deviceParserMap[name]
      } else {
        const dev = devices.find(d => d.device_name === name)
        if (dev?.available_parsers?.length === 1) {
          newMap[name] = dev.available_parsers[0].id
        } else if (dev?.available_parsers?.length > 1) {
          // ATG 依赖场景：默认取第一个可用解析器，减少手动选择
          newMap[name] = dev.available_parsers[0].id
        }
      }
    })
    setDeviceParserMap(newMap)
  }

  const handleParserChange = (deviceName, parserId) => {
    setDeviceParserMap(prev => ({ ...prev, [deviceName]: parserId }))
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

  const atgRequiredFamilies = ['irs', 'rtk', 'fcc']
  const atgFamilyCoverage = useMemo(() => {
    const m = {}
    atgRequiredFamilies.forEach(f => {
      m[f] = selectedFamilies.has(f)
    })
    return m
  }, [selectedFamilies])

  const allDevicesConfigured = useMemo(() => {
    return selectedDevices.length > 0 &&
      selectedDevices.every(name => deviceParserMap[name] != null)
  }, [selectedDevices, deviceParserMap])

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
      message.warning('请为每个选中的设备选择解析协议版本')
      return
    }

    setUploading(true)
    const formData = new FormData()
    if (dataSource === 'local') {
      formData.append('file', fileList[0])
    } else {
      formData.append('shared_tsn_id', String(platformFileId))
    }
    formData.append('device_parser_map', JSON.stringify(deviceParserMap))

    if (selectedVersion) {
      formData.append('protocol_version_id', selectedVersion)
    }
    if (selectedDevices.length > 0) {
      formData.append('selected_devices', selectedDevices.join(','))
    }
    if (selectedPorts.length > 0) {
      formData.append('selected_ports', selectedPorts.join(','))
    }

    try {
      const onProg = (progressEvent) => {
        if (progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total)
          setUploadProgress(percent)
        }
      }
      const res =
        dataSource === 'local'
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
          <DesktopOutlined style={{ color: '#f59e0b' }} />
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
              <Tag color={hasSelectedATG && atgRequiredFamilies.includes(family) ? 'gold' : 'blue'}>
                {FAMILY_LABELS[family] || family}
              </Tag>
              {hasSelectedATG && atgRequiredFamilies.includes(family) && (
                <Tag color="magenta">ATG依赖</Tag>
              )}
            </Space>
          )
          : <Tag color="default">未识别</Tag>
      ),
    },
    {
      title: '解析协议版本',
      key: 'parser_version',
      width: 280,
      render: (_, record) => {
        const parsers = record.available_parsers || []
        if (parsers.length === 0) {
          return <Tag color="red">暂无可用解析器</Tag>
        }
        return (
          <Select
            placeholder="选择版本"
            style={{ width: '100%' }}
            value={deviceParserMap[record.device_name]}
            onChange={(val) => handleParserChange(record.device_name, val)}
            size="small"
          >
            {parsers.map(p => (
              <Option key={p.id} value={p.id}>
                {p.version ? `${p.name} - ${p.version}` : p.name}
              </Option>
            ))}
          </Select>
        )
      },
    },
    {
      title: '端口',
      dataIndex: 'ports',
      key: 'ports',
      render: (ports) => (
        <span style={{ color: '#8b949e', fontSize: 12 }}>
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
              <Space>
                <CloudUploadOutlined style={{ color: '#d29922' }} />
                <span>上传TSN数据包</span>
              </Space>
            }
          >
            <div style={{ marginBottom: 16 }}>
              <span style={{ color: '#8b949e', marginRight: 12 }}>数据来源</span>
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
                <div style={{ color: '#8b949e', marginBottom: 8 }}>选择管理员上传的平台数据（近 2 天内有效）</div>
                <Select
                  placeholder="选择一条平台数据"
                  style={{ width: '100%' }}
                  value={platformFileId}
                  onChange={setPlatformFileId}
                  allowClear
                  showSearch
                  optionFilterProp="label"
                  options={sharedList.map((s) => ({
                    value: s.id,
                    label: `#${s.id} ${s.original_filename}${s.experiment_label ? ` — ${s.experiment_label}` : ''}${s.experiment_date ? ` (${s.experiment_date})` : ''}`,
                  }))}
                />
                {sharedList.length === 0 && (
                  <Alert type="info" showIcon style={{ marginTop: 12 }} message="暂无平台数据，请管理员在「系统配置 → 平台共享数据」中上传" />
                )}
              </div>
            ) : (
              <Dragger {...uploadProps} style={{ marginBottom: 24 }}>
                <p className="ant-upload-drag-icon">
                  <InboxOutlined style={{ color: '#d29922', fontSize: 48 }} />
                </p>
                <p className="ant-upload-text" style={{ color: '#c9d1d9' }}>
                  点击或拖拽文件到此区域上传
                </p>
                <p className="ant-upload-hint" style={{ color: '#8b949e' }}>
                  支持 .pcapng, .pcap, .cap 格式的网络抓包文件
                </p>
              </Dragger>
            )}

            <Form form={form} layout="vertical">
              {/* 1. TSN网络配置 */}
              <Form.Item
                label={
                  <Space>
                    <ApiOutlined style={{ color: '#58a6ff' }} />
                    <span>TSN网络配置</span>
                    <Tag color="blue">必选</Tag>
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
                        <ApiOutlined style={{ color: '#58a6ff' }} />
                        <span style={{ fontWeight: 500 }}>{v.protocol_name}</span>
                        <Tag color="cyan">{v.version}</Tag>
                        <span style={{ color: '#8b949e', fontSize: 12 }}>
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
                      <div style={{ color: '#8b949e', fontSize: 12 }}>
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
                      <DesktopOutlined style={{ color: '#f59e0b' }} />
                      <span>选择设备</span>
                      <Tag color="orange">必选</Tag>
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
                          <DesktopOutlined style={{ color: '#f59e0b' }} />
                          <span style={{ fontWeight: 500 }}>{device.device_name}</span>
                          <Tag color="orange">{device.port_count} 端口</Tag>
                          {device.protocol_family && (
                            <Tag color="blue">{FAMILY_LABELS[device.protocol_family] || device.protocol_family}</Tag>
                          )}
                          <Tag color="green">{formatDirectionLabel(device.direction)}</Tag>
                        </Space>
                      </Option>
                    ))}
                  </Select>
                  {selectedDevices.length > 0 && (
                    <div style={{ color: '#8b949e', fontSize: 12, marginTop: 4 }}>
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
                      <span style={{ color: '#8b949e' }}>请同时关注并配置：</span>
                      <Tag color={atgFamilyCoverage.irs ? 'green' : 'red'}>IRS {atgFamilyCoverage.irs ? '已覆盖' : '未覆盖'}</Tag>
                      <Tag color={atgFamilyCoverage.rtk ? 'green' : 'red'}>RTK {atgFamilyCoverage.rtk ? '已覆盖' : '未覆盖'}</Tag>
                      <Tag color={atgFamilyCoverage.fcc ? 'green' : 'red'}>FCC {atgFamilyCoverage.fcc ? '已覆盖' : '未覆盖'}</Tag>
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
                        <SettingOutlined style={{ color: '#3fb950' }} />
                        <span>设备解析版本配置</span>
                        <Tag color="green">为每个设备选择解析协议版本</Tag>
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
                        const pid = deviceParserMap[dev.device_name]
                        const parser = dev.available_parsers?.find(p => p.id === pid)
                        return (
                          <div key={dev.device_name}>
                            <Tag color="orange">{dev.device_name}</Tag>
                            →
                            <Tag color="green">{parser ? [parser.name, parser.version].filter(Boolean).join(' ') : `ID:${pid}`}</Tag>
                            <span style={{ color: '#8b949e', fontSize: 12 }}>
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
            <div style={{ color: '#8b949e', lineHeight: 2 }}>
              <p><strong style={{ color: '#c9d1d9' }}>1. 准备数据</strong></p>
              <p>上传从TSN网络抓取的 .pcapng 文件</p>

              <p style={{ marginTop: 16 }}><strong style={{ color: '#58a6ff' }}>2. 选择网络配置</strong></p>
              <p>选择TSN网络配置版本，定义端口和字段偏移位置</p>

              <p style={{ marginTop: 16 }}><strong style={{ color: '#d29922' }}>3. 选择设备</strong></p>
              <p>选择要解析的目标设备</p>

              <p style={{ marginTop: 16 }}><strong style={{ color: '#3fb950' }}>4. 配置解析版本</strong></p>
              <p>为每个设备选择对应的解析协议版本。系统会自动匹配协议类型，只显示适用的版本。</p>

              <p style={{ marginTop: 16 }}><strong style={{ color: '#c9d1d9' }}>5. 开始解析</strong></p>
              <p>系统将按设备分配端口和解析器，精确解码每个设备的数据</p>
            </div>
          </Card>

          {netVersions.length === 0 && !loading && (
            <Card title="提示" style={{ marginTop: 16 }}>
              <div style={{ color: '#f59e0b' }}>
                <p>暂无可用网络配置</p>
                <p style={{ fontSize: 12, color: '#8b949e' }}>
                  当前系统固定使用 TSN ICD v6.0.1，请联系管理员检查内置配置是否加载成功。
                </p>
              </div>
            </Card>
          )}

          <Card title="解析流程" style={{ marginTop: 16 }}>
            <div style={{ color: '#8b949e', fontSize: 13, lineHeight: 2 }}>
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
                <Tag color="blue" style={{ margin: 0, marginRight: 8 }}>网络配置</Tag>
                <span>定位端口和偏移</span>
              </div>
              <div style={{ borderLeft: '2px solid #30363d', height: 16, marginLeft: 12 }} />
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
                <Tag color="orange" style={{ margin: 0, marginRight: 8 }}>设备选择</Tag>
                <span>筛选目标设备端口</span>
              </div>
              <div style={{ borderLeft: '2px solid #30363d', height: 16, marginLeft: 12 }} />
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
                <Tag color="green" style={{ margin: 0, marginRight: 8 }}>版本配置</Tag>
                <span>逐设备指定协议版本</span>
              </div>
              <div style={{ borderLeft: '2px solid #30363d', height: 16, marginLeft: 12 }} />
              <div style={{ display: 'flex', alignItems: 'center' }}>
                <Tag color="purple" style={{ margin: 0, marginRight: 8 }}>输出结果</Tag>
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
