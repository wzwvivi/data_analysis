import React, { useEffect } from 'react'
import { Modal, Form, Input, InputNumber, Button, Space, Tabs } from 'antd'
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import BitMapDisplay from './BitMapDisplay'

const emptyLabel = () => ({
  label_oct: '',
  name: '',
  direction: '',
  data_type: '',
  unit: '',
  range: '',
  resolution: undefined,
  reserved_bits: '',
  notes: '',
  sources: [],
  discrete_bits: {},
  special_fields: [],
  bnr_fields: [],
})

export default function LabelEditModal({ open, onCancel, onOk, initial }) {
  const [form] = Form.useForm()
  const watched = Form.useWatch([], form)

  useEffect(() => {
    if (!open) return
    const base = initial ? { ...emptyLabel(), ...initial } : emptyLabel()
    if (!Array.isArray(base.sources)) base.sources = []
    if (!base.discrete_bits || typeof base.discrete_bits !== 'object') base.discrete_bits = {}
    if (!Array.isArray(base.special_fields)) base.special_fields = []
    if (!Array.isArray(base.bnr_fields)) base.bnr_fields = []
    const bnrForForm = (base.bnr_fields || []).map((f) => ({
      ...f,
      data_bits:
        Array.isArray(f.data_bits) && f.data_bits.length >= 2
          ? `${f.data_bits[0]},${f.data_bits[1]}`
          : f.data_bits,
    }))
    const specForForm = (base.special_fields || []).map((f) => ({
      ...f,
      bits: Array.isArray(f.bits) && f.bits.length >= 2 ? `${f.bits[0]},${f.bits[1]}` : f.bits,
      values:
        f.values && typeof f.values === 'object' ? JSON.stringify(f.values) : f.values || '',
    }))
    form.setFieldsValue({
      ...base,
      bnr_fields: bnrForForm,
      special_fields: specForForm,
      sources_text: (base.sources || []).join(', '),
      discrete_entries: Object.entries(base.discrete_bits || {}).map(([bit, desc]) => ({ bit, desc })),
    })
  }, [open, initial, form])

  const buildPayload = async () => {
    const v = await form.validateFields()
    const sources = (v.sources_text || '')
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean)
    const disc = {}
    ;(v.discrete_entries || []).forEach((row) => {
      if (row?.bit) disc[String(row.bit).trim()] = row.desc || ''
    })
    const parseTwoInts = (x) => {
      if (Array.isArray(x) && x.length >= 2) return [Number(x[0]), Number(x[1])]
      if (typeof x === 'string') {
        const parts = x.split(/[,，]/).map((s) => parseInt(s.trim(), 10))
        if (parts.length >= 2 && !Number.isNaN(parts[0]) && !Number.isNaN(parts[1])) return [parts[0], parts[1]]
      }
      return null
    }
    const bnr_fields = (v.bnr_fields || []).map((f) => {
      const db = parseTwoInts(f.data_bits)
      return {
        name: f.name || '',
        data_bits: db || [11, 29],
        resolution: f.resolution,
        unit: f.unit || '',
        sign_bit: f.sign_bit,
      }
    })
    const special_fields = (v.special_fields || []).map((f) => {
      const bits = parseTwoInts(f.bits)
      let values = f.values
      if (typeof values === 'string' && values.trim()) {
        try {
          values = JSON.parse(values)
        } catch {
          values = {}
        }
      }
      return {
        name: f.name || '',
        bits: bits || [20, 23],
        type: f.type || 'enum',
        values: values && typeof values === 'object' ? values : undefined,
      }
    })
    return {
      label_oct: v.label_oct || '',
      name: v.name || '',
      direction: v.direction || '',
      data_type: v.data_type || '',
      unit: v.unit || '',
      range: v.range || '',
      resolution: v.resolution,
      reserved_bits: v.reserved_bits || '',
      notes: v.notes || '',
      sources,
      discrete_bits: disc,
      special_fields,
      bnr_fields,
    }
  }

  const handleOk = async () => {
    try {
      const payload = await buildPayload()
      onOk(payload)
    } catch {
      /* validate */
    }
  }

  const previewLabel = watched
    ? {
        bnr_fields: watched.bnr_fields || [],
        discrete_bits: (watched.discrete_entries || []).reduce((acc, row) => {
          if (row?.bit) acc[String(row.bit).trim()] = row.desc || ''
          return acc
        }, {}),
        special_fields: watched.special_fields || [],
      }
    : {}

  return (
    <Modal
      title={initial ? '编辑 Label' : '新增 Label'}
      open={open}
      onCancel={onCancel}
      onOk={handleOk}
      width={720}
      destroyOnClose
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Tabs
          items={[
            {
              key: 'basic',
              label: '基本信息',
              children: (
                <>
                  <Form.Item name="label_oct" label="Label (八进制)" rules={[{ required: true, message: '必填' }]}>
                    <Input placeholder="如 310" />
                  </Form.Item>
                  <Form.Item name="name" label="名称" rules={[{ required: true, message: '必填' }]}>
                    <Input />
                  </Form.Item>
                  <Form.Item name="direction" label="方向">
                    <Input placeholder="发送/接收" />
                  </Form.Item>
                  <Form.Item name="data_type" label="数据类型">
                    <Input placeholder="BNR / DIS / …" />
                  </Form.Item>
                  <Form.Item name="unit" label="单位">
                    <Input />
                  </Form.Item>
                  <Form.Item name="range" label="量程/范围">
                    <Input />
                  </Form.Item>
                  <Form.Item name="resolution" label="分辨率">
                    <InputNumber style={{ width: '100%' }} step={0.0001} />
                  </Form.Item>
                  <Form.Item name="reserved_bits" label="保留位说明">
                    <Input />
                  </Form.Item>
                  <Form.Item name="sources_text" label="源 (逗号分隔)">
                    <Input placeholder="LRU1, LRU2" />
                  </Form.Item>
                  <Form.Item name="notes" label="备注">
                    <Input.TextArea rows={2} />
                  </Form.Item>
                </>
              ),
            },
            {
              key: 'bnr',
              label: 'BNR 字段',
              children: (
                <Form.List name="bnr_fields">
                  {(fields, { add, remove }) => (
                    <>
                      {fields.map(({ key, name, ...rest }) => (
                        <Space key={key} align="baseline" wrap style={{ display: 'flex', marginBottom: 8 }}>
                          <Form.Item {...rest} name={[name, 'name']} label="名称">
                            <Input placeholder="字段名" />
                          </Form.Item>
                          <Form.Item {...rest} name={[name, 'data_bits']} label="数据位 [起,止]">
                            <Input placeholder="11,29" />
                          </Form.Item>
                          <Form.Item {...rest} name={[name, 'resolution']} label="分辨率">
                            <InputNumber step={0.0001} />
                          </Form.Item>
                          <Form.Item {...rest} name={[name, 'unit']} label="单位">
                            <Input />
                          </Form.Item>
                          <MinusCircleOutlined onClick={() => remove(name)} />
                        </Space>
                      ))}
                      <Button type="dashed" onClick={() => add({ name: '', data_bits: '11,29' })} icon={<PlusOutlined />}>
                        添加 BNR 字段
                      </Button>
                    </>
                  )}
                </Form.List>
              ),
            },
            {
              key: 'disc',
              label: '离散位',
              children: (
                <Form.List name="discrete_entries">
                  {(fields, { add, remove }) => (
                    <>
                      {fields.map(({ key, name, ...rest }) => (
                        <Space key={key} align="baseline" style={{ display: 'flex', marginBottom: 8 }}>
                          <Form.Item {...rest} name={[name, 'bit']} label="位号">
                            <Input placeholder="15" />
                          </Form.Item>
                          <Form.Item {...rest} name={[name, 'desc']} label="描述 (0=…,1=…)">
                            <Input style={{ width: 280 }} />
                          </Form.Item>
                          <MinusCircleOutlined onClick={() => remove(name)} />
                        </Space>
                      ))}
                      <Button type="dashed" onClick={() => add({ bit: '', desc: '' })} icon={<PlusOutlined />}>
                        添加离散位
                      </Button>
                    </>
                  )}
                </Form.List>
              ),
            },
            {
              key: 'special',
              label: '特殊字段',
              children: (
                <Form.List name="special_fields">
                  {(fields, { add, remove }) => (
                    <>
                      {fields.map(({ key, name, ...rest }) => (
                        <Space key={key} align="baseline" wrap style={{ display: 'flex', marginBottom: 8 }}>
                          <Form.Item {...rest} name={[name, 'name']} label="名称">
                            <Input />
                          </Form.Item>
                          <Form.Item {...rest} name={[name, 'bits']} label="位 [起,止]">
                            <Input placeholder="20,23" />
                          </Form.Item>
                          <Form.Item {...rest} name={[name, 'type']} label="类型">
                            <Input placeholder="enum / uint" />
                          </Form.Item>
                          <Form.Item {...rest} name={[name, 'values']} label="枚举 (可选 JSON)">
                            <Input placeholder='{"0":"A","1":"B"}' />
                          </Form.Item>
                          <MinusCircleOutlined onClick={() => remove(name)} />
                        </Space>
                      ))}
                      <Button type="dashed" onClick={() => add({ name: '', bits: '20,23', type: 'enum' })} icon={<PlusOutlined />}>
                        添加特殊字段
                      </Button>
                    </>
                  )}
                </Form.List>
              ),
            },
            {
              key: 'bitmap',
              label: '位图',
              children: <BitMapDisplay label={previewLabel} />,
            },
          ]}
        />
      </Form>
    </Modal>
  )
}
