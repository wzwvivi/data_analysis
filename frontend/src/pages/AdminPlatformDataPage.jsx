import React, { useState, useEffect, useCallback } from 'react'
import {
  Card, Upload, Button, Table, message, Modal, Form, DatePicker, Input, Space, Tag, Popconfirm, Progress,
} from 'antd'
import { UploadOutlined, EditOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { sharedTsnApi } from '../services/api'

function AdminPlatformDataPage() {
  const [list, setList] = useState([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [editRow, setEditRow] = useState(null)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await sharedTsnApi.list()
      setList(res.data || [])
    } catch {
      message.error('加载平台数据列表失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const handleUpload = async (file) => {
    const fd = new FormData()
    fd.append('file', file)
    setUploading(true)
    setUploadProgress(0)
    try {
      await sharedTsnApi.upload(fd, (e) => {
        if (e.total) setUploadProgress(Math.round((e.loaded * 100) / e.total))
      })
      message.success('已上传到平台共享库（超过保留期的文件会在启动或下次上传时自动清理）')
      load()
    } catch (e) {
      message.error(e.response?.data?.detail || '上传失败')
    } finally {
      setUploading(false)
      setUploadProgress(0)
    }
    return false
  }

  const openEdit = (record) => {
    setEditRow(record)
    form.setFieldsValue({
      experiment_date: record.experiment_date ? dayjs(record.experiment_date) : null,
      experiment_label: record.experiment_label || '',
    })
  }

  const submitEdit = async () => {
    try {
      const v = await form.validateFields()
      await sharedTsnApi.update(editRow.id, {
        experiment_date: v.experiment_date ? v.experiment_date.format('YYYY-MM-DD') : null,
        experiment_label: v.experiment_label || null,
      })
      message.success('已保存')
      setEditRow(null)
      load()
    } catch (e) {
      if (e?.errorFields) return
      message.error(e.response?.data?.detail || '保存失败')
    }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    { title: '文件名', dataIndex: 'original_filename', ellipsis: true },
    {
      title: '实验日期',
      dataIndex: 'experiment_date',
      width: 120,
      render: (t) => t || <Tag color="default">未填写</Tag>,
    },
    {
      title: '实验说明',
      dataIndex: 'experiment_label',
      ellipsis: true,
      render: (t) => t || '—',
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      width: 180,
      render: (t) => (t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '—'),
    },
    {
      title: '操作',
      key: 'op',
      width: 160,
      render: (_, r) => (
        <Space>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>
            编辑
          </Button>
          <Popconfirm title="确定删除该条平台数据？" onConfirm={async () => {
            try {
              await sharedTsnApi.remove(r.id)
              message.success('已删除')
              load()
            } catch (e) {
              message.error(e.response?.data?.detail || '删除失败')
            }
          }}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div className="fade-in">
      <Card
        title="平台共享 TSN 数据"
        extra={
          <Space>
            <Tag color="blue">管理员上传，保留近 2 天</Tag>
            <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
              刷新
            </Button>
          </Space>
        }
        style={{ marginBottom: 24 }}
      >
        <p style={{ color: '#a1a1aa', marginBottom: 16 }}>
          上传的抓包将出现在「上传解析」「事件分析」「TSN 异常检查」中的「平台数据」选项，供所有登录用户使用。
        </p>
        <Upload beforeUpload={handleUpload} showUploadList={false} accept=".pcap,.pcapng,.cap">
          <Button type="primary" icon={<UploadOutlined />} loading={uploading}>
            {uploading ? `上传中 ${uploadProgress}%` : '上传 TSN 抓包到平台'}
          </Button>
        </Upload>
        {uploading && uploadProgress > 0 && (
          <Progress percent={uploadProgress} status="active" style={{ marginTop: 12, maxWidth: 400 }} />
        )}
      </Card>

      <Card title="当前平台数据">
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={list}
          pagination={false}
          scroll={{ x: 900 }}
        />
      </Card>

      <Modal
        title="编辑实验信息"
        open={!!editRow}
        onCancel={() => setEditRow(null)}
        onOk={submitEdit}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="experiment_date" label="实验日期">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="experiment_label" label="实验说明 / 名称">
            <Input.TextArea rows={3} placeholder="例如：某日滑行试验" maxLength={500} showCount />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default AdminPlatformDataPage
