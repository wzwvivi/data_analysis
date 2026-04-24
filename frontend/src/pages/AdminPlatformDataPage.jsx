import React, { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Card, Upload, Button, Table, message, Modal, Form, DatePicker, Input, Space, Tag, Popconfirm, Progress,
  Select, Collapse, Typography,
} from 'antd'
import { UploadOutlined, EditOutlined, DeleteOutlined, ReloadOutlined, PlusOutlined, DatabaseOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { sharedTsnApi, configurationApi } from '../services/api'
import AppPageHeader from '../components/AppPageHeader'

const { Text } = Typography

function AdminPlatformDataPage() {
  const [tree, setTree] = useState([])
  const [flatList, setFlatList] = useState([])
  const [kindOptions, setKindOptions] = useState([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [transcodeActive, setTranscodeActive] = useState(false)
  const [transcodeProgress, setTranscodeProgress] = useState(0)

  const [sortieModalOpen, setSortieModalOpen] = useState(false)
  const [sortieEdit, setSortieEdit] = useState(null)
  const [sortieForm] = Form.useForm()

  const [editFileRow, setEditFileRow] = useState(null)
  const [fileForm] = Form.useForm()

  const [uploadSortieId, setUploadSortieId] = useState(null)
  const [uploadKind, setUploadKind] = useState(null)

  const [acOptions, setAcOptions] = useState([])
  const [swOptions, setSwOptions] = useState([])

  const loadConfigOptions = useCallback(async () => {
    try {
      const [acRes, swRes] = await Promise.all([
        configurationApi.listAircraftConfigs(),
        configurationApi.listSoftwareConfigs(),
      ])
      setAcOptions(acRes.data || [])
      setSwOptions(swRes.data || [])
    } catch {
      // 静默失败：未配置构型时不影响其余操作
    }
  }, [])

  useEffect(() => {
    loadConfigOptions()
  }, [loadConfigOptions])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [treeRes, flatRes, kindsRes] = await Promise.all([
        sharedTsnApi.listSorties(),
        sharedTsnApi.list(),
        sharedTsnApi.assetKinds(),
      ])
      setTree(treeRes.data || [])
      setFlatList(flatRes.data || [])
      setKindOptions(kindsRes.data?.items || [])
    } catch {
      message.error('加载平台数据失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const selectableSorties = useMemo(
    () => tree.filter((s) => s.id > 0),
    [tree],
  )

  const uploadAccept = useMemo(() => {
    const k = kindOptions.find((x) => x.key === uploadKind)
    if (!k?.extensions?.length) {
      return '.pcap,.pcapng,.cap,.mp4,.mov,.mkv,.avi,.m4v,.ts,.webm'
    }
    return k.extensions.map((e) => `.${e}`).join(',')
  }, [uploadKind, kindOptions])

  const handleUpload = async (file) => {
    if (!uploadSortieId) {
      message.warning('请先选择试验架次')
      return false
    }
    if (!uploadKind) {
      message.warning('请选择本次上传的数据类型')
      return false
    }
    const fd = new FormData()
    fd.append('file', file)
    fd.append('sortie_id', String(uploadSortieId))
    fd.append('asset_type', uploadKind)
    setUploading(true)
    setUploadProgress(0)
    setTranscodeActive(false)
    setTranscodeProgress(0)
    try {
      const res = await sharedTsnApi.upload(fd, (e) => {
        if (e.total) setUploadProgress(Math.round((e.loaded * 100) / e.total))
      })
      const msg = res.data?.message || '已上传到平台共享库'
      const vj = res.data?.video_job
      const fid = res.data?.id

      if (vj?.status === 'transcoding' && fid != null) {
        message.success(msg)
        setTranscodeActive(true)
        setTranscodeProgress(vj.progress ?? 8)
        load()
        message.loading({ content: '视频正在服务端转码（H.265→H.264）…', key: 'video-transcode', duration: 0 })
        try {
          let finished = false
          let ticks = 0
          const maxTicks = 900
          while (!finished && ticks < maxTicks) {
            ticks += 1
            await new Promise((r) => setTimeout(r, 1100))
            let jr
            try {
              jr = await sharedTsnApi.videoJob(fid)
            } catch {
              message.destroy('video-transcode')
              message.warning('轮询转码状态失败，请稍后刷新列表查看是否已完成')
              finished = true
              break
            }
            const st = jr.data?.status
            const p = jr.data?.progress ?? 0
            setTranscodeProgress(Number.isFinite(p) ? Math.min(100, Math.max(0, p)) : 0)
            if (st === 'ready') {
              message.destroy('video-transcode')
              message.success('视频转码完成，工作台可正常播放')
              finished = true
            } else if (st === 'failed') {
              message.destroy('video-transcode')
              message.error(jr.data?.error || '视频转码失败')
              finished = true
            }
          }
          if (!finished && ticks >= maxTicks) {
            message.destroy('video-transcode')
            message.warning('长时间未收到完成状态，请稍后手动刷新列表')
          }
        } finally {
          message.destroy('video-transcode')
          setTranscodeActive(false)
          setTranscodeProgress(0)
          load()
        }
      } else if (vj?.status === 'failed' && vj?.error) {
        message.warning(`${msg}`)
        load()
      } else {
        message.success(msg)
        load()
      }
    } catch (e) {
      const d = e.response?.data?.detail
      message.error(typeof d === 'string' ? d : d ? JSON.stringify(d) : '上传失败')
    } finally {
      setUploading(false)
      setUploadProgress(0)
    }
    return false
  }

  const openCreateSortie = () => {
    setSortieEdit(null)
    sortieForm.resetFields()
    loadConfigOptions()
    setSortieModalOpen(true)
  }

  const openEditSortie = (sortie) => {
    if (!sortie?.id || sortie.id <= 0) return
    setSortieEdit(sortie)
    loadConfigOptions()
    sortieForm.setFieldsValue({
      sortie_label: sortie.sortie_label,
      experiment_date: sortie.experiment_date ? dayjs(sortie.experiment_date) : null,
      remarks: sortie.remarks || '',
      aircraft_configuration_id: sortie.aircraft_configuration_id ?? sortie.aircraft_configuration?.id ?? null,
      software_configuration_id: sortie.software_configuration_id ?? sortie.software_configuration?.id ?? null,
    })
    setSortieModalOpen(true)
  }

  const submitSortie = async () => {
    try {
      const v = await sortieForm.validateFields()
      const payload = {
        sortie_label: v.sortie_label?.trim(),
        experiment_date: v.experiment_date ? v.experiment_date.format('YYYY-MM-DD') : null,
        remarks: v.remarks || null,
        aircraft_configuration_id: v.aircraft_configuration_id ?? null,
        software_configuration_id: v.software_configuration_id ?? null,
      }
      if (sortieEdit?.id) {
        await sharedTsnApi.updateSortie(sortieEdit.id, payload)
        message.success('架次信息已更新')
      } else {
        const r = await sharedTsnApi.createSortie(payload)
        const newId = r.data?.id
        if (newId != null) {
          setUploadSortieId(newId)
        }
        message.success('已新建试验架次，已自动选为当前上传架次')
      }
      setSortieModalOpen(false)
      load()
    } catch (e) {
      if (e?.errorFields) return
      message.error(e.response?.data?.detail || '保存失败')
    }
  }

  const openEditFile = (record) => {
    setEditFileRow(record)
    fileForm.setFieldsValue({
      experiment_date: record.experiment_date ? dayjs(record.experiment_date) : null,
      experiment_label: record.experiment_label || '',
    })
  }

  const submitEditFile = async () => {
    try {
      const v = await fileForm.validateFields()
      await sharedTsnApi.update(editFileRow.id, {
        experiment_date: v.experiment_date ? v.experiment_date.format('YYYY-MM-DD') : null,
        experiment_label: v.experiment_label || null,
      })
      message.success('已保存')
      setEditFileRow(null)
      load()
    } catch (e) {
      if (e?.errorFields) return
      message.error(e.response?.data?.detail || '保存失败')
    }
  }

  const fileColumns = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    { title: '文件名', dataIndex: 'original_filename', ellipsis: true },
    {
      title: '数据类型',
      key: 'kind',
      width: 180,
      render: (_, r) => r.asset_label || <Tag>未标注</Tag>,
    },
    {
      title: '试验日期(旧字段)',
      dataIndex: 'experiment_date',
      width: 120,
      render: (t) => t || <Tag color="default">—</Tag>,
    },
    {
      title: '说明(旧字段)',
      dataIndex: 'experiment_label',
      ellipsis: true,
      render: (t) => t || '—',
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      width: 170,
      render: (t) => (t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '—'),
    },
    {
      title: '操作',
      key: 'op',
      width: 160,
      render: (_, r) => (
        <Space>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEditFile(r)}>
            编辑
          </Button>
          <Popconfirm
            title="确定删除该文件？"
            onConfirm={async () => {
              try {
                await sharedTsnApi.remove(r.id)
                message.success('已删除')
                load()
              } catch (e) {
                message.error(e.response?.data?.detail || '删除失败')
              }
            }}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div className="app-page-shell fade-in">
      <div className="app-page-shell-inner">
        <AppPageHeader
          icon={<DatabaseOutlined />}
          eyebrow="数据管理"
          title="平台共享试验数据"
          subtitle="一次完整试验可包含 TSN 交换机 1/2 抓包、地面网联记录、飞控记录器数据，以及各机位视频。请先新建架次，再按数据类型分别上传；解析 / 分析功能仅可选用 PCAP 类数据源。"
          tags={[
            { text: '按试验架次分类' },
            { text: '保留近 20 天', tone: 'neutral' },
          ]}
          actions={
            <Space>
              <Button type="primary" icon={<PlusOutlined />} onClick={openCreateSortie}>
                新建试验架次
              </Button>
              <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
                刷新
              </Button>
            </Space>
          }
        />

      <div className="app-page-body">
      <Card title="上传到指定架次">
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Space wrap align="center">
              <span style={{ color: '#a1a1aa' }}>试验架次</span>
              <Select
                placeholder="选择架次"
                style={{ minWidth: 260 }}
                value={uploadSortieId}
                onChange={setUploadSortieId}
                options={selectableSorties.map((s) => ({
                  value: s.id,
                  label: `${s.sortie_label}${s.experiment_date ? ` (${s.experiment_date})` : ''}`,
                }))}
                allowClear
              />
              <span style={{ color: '#a1a1aa' }}>数据类型</span>
              <Select
                placeholder="选择本次上传的数据种类"
                style={{ minWidth: 280 }}
                value={uploadKind}
                onChange={setUploadKind}
                options={kindOptions.map((k) => ({
                  value: k.key,
                  label: `${k.label}（${k.extensions?.map((e) => `.${e}`).join('、') || ''}）`,
                }))}
                allowClear
                showSearch
                optionFilterProp="label"
              />
            </Space>
            <Upload beforeUpload={handleUpload} showUploadList={false} accept={uploadAccept}>
              <Button type="primary" icon={<UploadOutlined />} loading={uploading} disabled={!uploadSortieId || !uploadKind}>
                {uploading ? `上传中 ${uploadProgress}%` : '选择文件并上传'}
              </Button>
            </Upload>
            {uploading && (
              <div style={{ marginTop: 8 }}>
                <Text type="secondary" style={{ display: 'block', marginBottom: 4 }}>上传到服务器</Text>
                <Progress percent={uploadProgress} status="active" style={{ maxWidth: 400 }} />
              </div>
            )}
            {transcodeActive && (
              <div style={{ marginTop: 8 }}>
                <Text type="secondary" style={{ display: 'block', marginBottom: 4 }}>
                  视频转码（H.265→H.264，完成后即可在浏览器播放）
                </Text>
                <Progress percent={transcodeProgress} status="active" style={{ maxWidth: 400 }} />
              </div>
            )}
          </Space>
      </Card>

      <Card title="按试验架次浏览" loading={loading}>
        <Collapse
          bordered={false}
          defaultActiveKey={tree.map((s) => String(s.id))}
          items={tree.map((s) => ({
            key: String(s.id),
            label: (
              <Space wrap>
                <strong style={{ color: '#e4e4e7' }}>{s.sortie_label}</strong>
                {s.experiment_date && <Tag>{s.experiment_date}</Tag>}
                {s.aircraft_configuration?.name && (
                  <Tag color="geekblue">
                    飞机构型：{s.aircraft_configuration.name}
                    {s.aircraft_configuration.version ? ` · ${s.aircraft_configuration.version}` : ''}
                  </Tag>
                )}
                {s.software_configuration?.name && (
                  <Tag color="purple">
                    软件构型：{s.software_configuration.name}
                  </Tag>
                )}
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {s.files?.length || 0} 个文件
                </Text>
              </Space>
            ),
            extra: s.id > 0 ? (
              <div role="presentation" onClick={(e) => e.stopPropagation()}>
                <Space>
                  <Button type="link" size="small" onClick={() => openEditSortie(s)}>编辑架次</Button>
                  <Popconfirm
                    title="删除整个架次及其下所有文件？"
                    onConfirm={async () => {
                      try {
                        await sharedTsnApi.deleteSortie(s.id)
                        message.success('已删除架次')
                        load()
                      } catch (e) {
                        message.error(e.response?.data?.detail || '删除失败')
                      }
                    }}
                  >
                    <Button type="link" size="small" danger>删除架次</Button>
                  </Popconfirm>
                </Space>
              </div>
            ) : null,
            children: (
              <div>
                {s.remarks && (
                  <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>{s.remarks}</Text>
                )}
                <Table
                  rowKey="id"
                  size="small"
                  columns={fileColumns}
                  dataSource={s.files || []}
                  pagination={false}
                  scroll={{ x: 960 }}
                  locale={{ emptyText: '该架次下暂无文件' }}
                />
              </div>
            ),
          }))}
        />
        {!loading && tree.length === 0 && (
          <Text type="secondary">暂无架次数据</Text>
        )}
      </Card>

      <Card title="全部文件（扁平列表）" style={{ marginTop: 24 }}>
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 70 },
            { title: '文件名', dataIndex: 'original_filename', ellipsis: true },
            {
              title: '数据类型',
              key: 'kind',
              width: 180,
              render: (_, r) => r.asset_label || <Tag>未标注</Tag>,
            },
            {
              title: '试验架次',
              key: 'sortie',
              width: 200,
              ellipsis: true,
              render: (_, r) => r.sortie_label || '—',
            },
            {
              title: '试验日期(旧字段)',
              dataIndex: 'experiment_date',
              width: 120,
              render: (t) => t || <Tag color="default">—</Tag>,
            },
            {
              title: '说明(旧字段)',
              dataIndex: 'experiment_label',
              ellipsis: true,
              render: (t) => t || '—',
            },
            {
              title: '上传时间',
              dataIndex: 'created_at',
              width: 170,
              render: (t) => (t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '—'),
            },
            fileColumns[fileColumns.length - 1],
          ]}
          dataSource={flatList}
          pagination={{ pageSize: 15 }}
          scroll={{ x: 1100 }}
        />
      </Card>
      </div>
      </div>

      <Modal
        title={sortieEdit ? '编辑试验架次' : '新建试验架次'}
        open={sortieModalOpen}
        onCancel={() => setSortieModalOpen(false)}
        onOk={submitSortie}
        destroyOnClose
      >
        <Form form={sortieForm} layout="vertical">
          <Form.Item name="sortie_label" label="架次名称 / 编号" rules={[{ required: true, message: '请填写架次名称' }]}>
            <Input placeholder="例如：2026-04-18 滑行试验 #01" maxLength={300} showCount />
          </Form.Item>
          <Form.Item name="experiment_date" label="试验日期">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="aircraft_configuration_id"
            label="飞机构型（决定 TSN / 设备协议版本）"
            rules={[{ required: true, message: '请选择飞机构型' }]}
          >
            <Select
              placeholder={acOptions.length === 0 ? '暂无可用构型，请先到「构型管理」创建' : '选择飞机构型'}
              allowClear
              showSearch
              optionFilterProp="label"
              options={acOptions.map((it) => ({
                value: it.id,
                label: `${it.name}${it.version ? ` · ${it.version}` : ''}${it.tsn_protocol_label ? ` · TSN ${it.tsn_protocol_label}` : ''}`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="software_configuration_id"
            label="软件构型（决定各设备软件版本号）"
            rules={[{ required: true, message: '请选择软件构型' }]}
          >
            <Select
              placeholder={swOptions.length === 0 ? '暂无可用构型，请先到「构型管理」导入 Excel' : '选择软件构型'}
              allowClear
              showSearch
              optionFilterProp="label"
              options={swOptions.map((it) => ({
                value: it.id,
                label: `${it.name}${it.snapshot_date ? ` · ${it.snapshot_date}` : ''}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="remarks" label="备注">
            <Input.TextArea rows={3} placeholder="可选：科目、场地、试验目的等" maxLength={2000} showCount />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="编辑文件附加信息（兼容旧字段）"
        open={!!editFileRow}
        onCancel={() => setEditFileRow(null)}
        onOk={submitEditFile}
        destroyOnClose
      >
        <Form form={fileForm} layout="vertical">
          <Form.Item name="experiment_date" label="试验日期（旧字段）">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="experiment_label" label="说明（旧字段）">
            <Input.TextArea rows={3} maxLength={500} showCount />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default AdminPlatformDataPage
