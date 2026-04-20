import React, { useEffect, useMemo, useState } from 'react'
import {
  Card,
  Input,
  Button,
  Space,
  Tag,
  Select,
  Form,
  Modal,
  Row,
  Col,
  Empty,
  Popconfirm,
  Typography,
  InputNumber,
  Table,
  Alert,
  Radio,
  Tooltip,
  message,
} from 'antd'
import {
  PlusOutlined,
  DeleteOutlined,
  SearchOutlined,
  EditOutlined,
  ArrowLeftOutlined,
  EyeOutlined,
  SaveOutlined,
  CheckOutlined,
} from '@ant-design/icons'

const { Text } = Typography

/**
 * ARINC 429 Label 可视化编辑器（完全对齐桌面 generator 的位图编辑体验）
 *
 * Props:
 *   - value: spec_json 对象 {protocol_meta, labels: [...]}
 *   - onChange(next): 每次改动后透传新 spec_json
 *   - readOnly: 不允许编辑
 *
 * 布局（与桌面一致）：
 *   - 顶部：协议元信息
 *   - 左列：Label 卡片列表 + 搜索 + 新增
 *   - 右列：
 *     - Label 基本信息表单
 *     - 32-bit 位图：左右两个竖向表格（Bit 1-16 / Bit 17-32）
 *       · Bit 1-8  Label 位（由八进制值推出 0/1，只读）
 *       · Bit 9-29 可编辑区（单击任一行进入统一编辑 Modal）
 *       · Bit 30-31 SSM 状态位（固定）
 *       · Bit 32   奇校验位（固定）
 *     - 字段定义汇总表：位号｜类型｜名称｜删除
 */

const DIRECTIONS = [
  { value: 'input', label: '输入（input）' },
  { value: 'output', label: '输出（output）' },
]

const SSM_TYPES = [
  { value: 'bnr', label: 'BNR' },
  { value: 'discrete', label: 'Discrete' },
  { value: 'bcd', label: 'BCD' },
]


function cloneDeep(obj) {
  return JSON.parse(JSON.stringify(obj || null))
}

function octToDec(oct) {
  if (!oct) return null
  const s = String(oct).trim()
  if (!/^[0-7]+$/.test(s)) return null
  return parseInt(s, 8)
}

function normalizeLabel(l) {
  return {
    label_oct: String(l?.label_oct || '').trim(),
    label_dec: l?.label_dec ?? octToDec(l?.label_oct),
    name: l?.name || '',
    direction: l?.direction || '',
    sources: Array.isArray(l?.sources) ? l.sources : [],
    sdi: l?.sdi ?? null,
    ssm_type: l?.ssm_type || 'bnr',
    data_type: l?.data_type || '',
    unit: l?.unit || '',
    range_desc: l?.range_desc || '',
    resolution: l?.resolution ?? null,
    reserved_bits: l?.reserved_bits || '',
    notes: l?.notes || '',
    discrete_bits: { ...(l?.discrete_bits || {}) },
    special_fields: Array.isArray(l?.special_fields) ? l.special_fields.map((s) => ({ ...s })) : [],
    bnr_fields: Array.isArray(l?.bnr_fields) ? l.bnr_fields.map((b) => ({ ...b })) : [],
  }
}


// ════════════════════════ 位图数据模型 ════════════════════════


/** 返回每个 Bit(9-29) 当前的语义信息（用于位图渲染 + 编辑初始化） */
function buildBitModel(label) {
  const model = {}
  for (let i = 9; i <= 29; i += 1) {
    model[i] = { type: 'reserved' }
  }
  if (!label) return model

  // single bit
  for (const [k, desc] of Object.entries(label.discrete_bits || {})) {
    const bitNum = parseInt(k, 10)
    if (!isNaN(bitNum) && bitNum >= 9 && bitNum <= 29) {
      model[bitNum] = {
        type: 'single',
        name: String(desc || '').split(':')[0].trim() || '单bit',
        fullDesc: String(desc || ''),
      }
    }
  }

  // multi-bit enum (special_fields)
  ;(label.special_fields || []).forEach((sf, idx) => {
    if (!sf?.bits || sf.bits.length !== 2) return
    const [a, b] = sf.bits
    const lo = Math.min(a, b)
    const hi = Math.max(a, b)
    const nBits = hi - lo + 1
    let valuesStr = ''
    if (sf.values && Object.keys(sf.values).length > 0) {
      valuesStr = Object.entries(sf.values)
        .map(([k, v]) => {
          const numK = parseInt(k, 10)
          if (!isNaN(numK)) return `${numK.toString(2).padStart(nBits, '0')}=${v}`
          return `${k}=${v}`
        })
        .join(', ')
    }
    for (let i = lo; i <= hi; i += 1) {
      if (i >= 9 && i <= 29) {
        model[i] = {
          type: sf.type === 'uint' ? 'bnr' : 'multi',
          name: sf.name || '枚举字段',
          fullDesc:
            sf.type === 'uint'
              ? `${sf.name || '枚举'} (Bit ${lo}-${hi}, 分辨率: 1)`
              : `${sf.name || '枚举'}${valuesStr ? `: ${valuesStr}` : ''}`,
          range: [lo, hi],
          fieldIndex: idx,
          kindHint: sf.type === 'uint' ? 'uint' : 'enum',
        }
      }
    }
  })

  // BNR fields
  ;(label.bnr_fields || []).forEach((bf, idx) => {
    if (bf?.data_bits && bf.data_bits.length === 2) {
      const [a, b] = bf.data_bits
      const lo = Math.min(a, b)
      const hi = Math.max(a, b)
      for (let i = lo; i <= hi; i += 1) {
        if (i >= 9 && i <= 29) {
          const resText = bf.resolution != null && bf.resolution !== '' ? bf.resolution : 'N/A'
          model[i] = {
            type: 'bnr',
            name: bf.name || '数值',
            fullDesc: `${bf.name || '数值'} (Bit ${lo}-${hi}, 分辨率: ${resText}${bf.unit || ''})`,
            range: [lo, hi],
            fieldIndex: idx,
          }
        }
      }
    }
    if (bf?.sign_bit && bf.sign_bit >= 9 && bf.sign_bit <= 29) {
      model[bf.sign_bit] = {
        type: 'sign',
        name: bf.name || '符号位',
        fullDesc: `${bf.name || '数值'} 符号位`,
        fieldIndex: idx,
      }
    }
  })

  return model
}


function TypeBadge({ kind }) {
  const meta = {
    parity: { color: '#475569', text: '校验位' },
    ssm: { color: '#b45309', text: 'SSM' },
    label: { color: '#0369a1', text: 'Label' },
    reserved: { color: '#4b5563', text: '预留' },
    single: { color: '#166534', text: '单bit' },
    multi: { color: '#6b21a8', text: '枚举' },
    bnr: { color: '#1d4ed8', text: '数值' },
    sign: { color: '#7c2d12', text: '符号位' },
  }[kind] || { color: '#4b5563', text: '-' }
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '1px 8px',
        borderRadius: 3,
        fontSize: 11,
        color: '#f1f5f9',
        background: meta.color,
        fontWeight: 500,
        whiteSpace: 'nowrap',
      }}
    >
      {meta.text}
    </span>
  )
}


// 把 Bit 号 → {typeKind, description, clickable} (与桌面 getBitRowInfo 对齐)
function getBitRowInfo(bitNum, bitModel, labelOct) {
  if (bitNum === 32) {
    return { kind: 'parity', description: 'P - 奇校验位（自动计算）', clickable: false }
  }
  if (bitNum >= 30) {
    return { kind: 'ssm', description: '状态矩阵位（协议定义）', clickable: false }
  }
  if (bitNum <= 8) {
    // Label 位：8-bitNum 作为索引
    let desc = '值 = ?'
    if (labelOct && /^[0-7]+$/.test(labelOct)) {
      const labelDec = parseInt(labelOct, 8)
      if (!isNaN(labelDec) && labelDec >= 0 && labelDec <= 255) {
        const bin = labelDec.toString(2).padStart(8, '0')
        const idx = 8 - bitNum
        const v = bin[idx] || '0'
        desc = `值 = ${v}`
      }
    }
    return { kind: 'label', description: desc, clickable: false }
  }
  const info = bitModel[bitNum] || { type: 'reserved' }
  if (info.type === 'single') {
    return { kind: 'single', description: info.fullDesc || info.name, clickable: true, info }
  }
  if (info.type === 'multi') {
    return { kind: 'multi', description: info.fullDesc, clickable: true, info }
  }
  if (info.type === 'bnr') {
    return { kind: 'bnr', description: info.fullDesc, clickable: true, info }
  }
  if (info.type === 'sign') {
    return { kind: 'sign', description: info.fullDesc, clickable: true, info }
  }
  return { kind: 'reserved', description: '点击添加定义', clickable: true, info }
}


function BitTable({ bits, label, bitModel, readOnly, onClickBit }) {
  const labelOct = label?.label_oct || ''
  return (
    <table
      style={{
        width: '100%',
        borderCollapse: 'collapse',
        fontSize: 12,
        background: 'rgba(24,24,27,0.6)',
      }}
    >
      <thead>
        <tr style={{ background: 'rgba(39,39,42,0.9)', color: '#e4e4e7' }}>
          <th style={{ padding: '6px 8px', textAlign: 'center', width: 52, borderBottom: '1px solid #3f3f46' }}>位</th>
          <th style={{ padding: '6px 8px', textAlign: 'center', width: 78, borderBottom: '1px solid #3f3f46' }}>类型</th>
          <th style={{ padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid #3f3f46' }}>说明</th>
        </tr>
      </thead>
      <tbody>
        {bits.map((b) => {
          const row = getBitRowInfo(b, bitModel, labelOct)
          const fixed = !row.clickable
          const canClick = row.clickable && !readOnly
          return (
            <tr
              key={b}
              onClick={canClick ? () => onClickBit(b) : undefined}
              style={{
                cursor: canClick ? 'pointer' : 'default',
                background: fixed ? 'rgba(39,39,42,0.4)' : 'transparent',
                transition: 'background 0.2s',
              }}
              onMouseEnter={(e) => {
                if (canClick) e.currentTarget.style.background = 'rgba(99,102,241,0.15)'
              }}
              onMouseLeave={(e) => {
                if (canClick) e.currentTarget.style.background = 'transparent'
              }}
            >
              <td
                style={{
                  padding: '5px 8px',
                  textAlign: 'center',
                  color: '#a1a1aa',
                  fontFamily: 'Menlo, monospace',
                  borderBottom: '1px solid rgba(63,63,70,0.5)',
                }}
              >
                {b}
              </td>
              <td
                style={{
                  padding: '5px 8px',
                  textAlign: 'center',
                  borderBottom: '1px solid rgba(63,63,70,0.5)',
                }}
              >
                <TypeBadge kind={row.kind} />
              </td>
              <td
                style={{
                  padding: '5px 10px',
                  color: row.kind === 'reserved' ? '#71717a' : '#e4e4e7',
                  borderBottom: '1px solid rgba(63,63,70,0.5)',
                  fontStyle: row.kind === 'reserved' ? 'italic' : 'normal',
                }}
              >
                {row.description}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}


function BitMap({ label, bitModel, readOnly, onClickBit }) {
  const left = Array.from({ length: 16 }, (_, i) => i + 1)
  const right = Array.from({ length: 16 }, (_, i) => i + 17)
  return (
    <Space direction="vertical" size={10} style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        style={{ padding: '4px 10px' }}
        message={
          <Text style={{ fontSize: 12 }}>
            Bit 1-8 由 Label 八进制自动填充；Bit 30-31 为 SSM 固定；Bit 32 为奇校验位（自动）。
            点击 Bit 9-29 的任一行可添加/修改/删除字段定义。
          </Text>
        }
      />
      <Row gutter={12}>
        <Col xs={24} md={12}>
          <div style={{ padding: '6px 10px', background: 'rgba(39,39,42,0.9)', color: '#a78bfa', fontWeight: 600, fontSize: 12 }}>
            Bit 1 – 16
          </div>
          <BitTable bits={left} label={label} bitModel={bitModel} readOnly={readOnly} onClickBit={onClickBit} />
        </Col>
        <Col xs={24} md={12}>
          <div style={{ padding: '6px 10px', background: 'rgba(39,39,42,0.9)', color: '#a78bfa', fontWeight: 600, fontSize: 12 }}>
            Bit 17 – 32
          </div>
          <BitTable bits={right} label={label} bitModel={bitModel} readOnly={readOnly} onClickBit={onClickBit} />
        </Col>
      </Row>
      <Space wrap size={8}>
        <TypeBadge kind="label" /> <Text type="secondary" style={{ fontSize: 11 }}>Label ID</Text>
        <TypeBadge kind="single" /> <Text type="secondary" style={{ fontSize: 11 }}>单 bit</Text>
        <TypeBadge kind="multi" /> <Text type="secondary" style={{ fontSize: 11 }}>枚举</Text>
        <TypeBadge kind="bnr" /> <Text type="secondary" style={{ fontSize: 11 }}>数值 (BNR/BCD)</Text>
        <TypeBadge kind="sign" /> <Text type="secondary" style={{ fontSize: 11 }}>符号位</Text>
        <TypeBadge kind="ssm" /> <Text type="secondary" style={{ fontSize: 11 }}>SSM 固定</Text>
        <TypeBadge kind="parity" /> <Text type="secondary" style={{ fontSize: 11 }}>校验位</Text>
        <TypeBadge kind="reserved" /> <Text type="secondary" style={{ fontSize: 11 }}>预留</Text>
      </Space>
    </Space>
  )
}


// ════════════════════════ 统一 Bit 编辑 Modal ════════════════════════


/**
 * 模仿桌面 bitEditModal：
 * - 顶部显示当前 Bit 范围 + 当前状态
 * - Segmented 切换类型：预留 / 单bit / 多bit枚举 / 数值(BNR)
 * - 每种类型显示对应表单
 * - Save：先清掉当前 bit 覆盖的旧字段（包括跨位的多bit/BNR/符号位），再写入新字段
 * - Delete：删掉当前 bit 所在字段
 */
function BitEditModal({ open, bitNum, label, onCancel, onSave, onDelete }) {
  const [form] = Form.useForm()
  const [type, setType] = useState('reserved')

  const currentStatus = useMemo(() => {
    if (!label || !bitNum) return { status: '预留', initialType: 'reserved' }
    const dbits = label.discrete_bits || {}
    if (dbits[bitNum]) {
      const [nm] = String(dbits[bitNum]).split(':')
      return { status: `单bit: ${nm.trim() || '已定义'}`, initialType: 'single' }
    }
    for (const sf of label.special_fields || []) {
      if (sf?.bits && bitNum >= sf.bits[0] && bitNum <= sf.bits[1]) {
        return { status: `枚举: ${sf.name} (Bit ${sf.bits[0]}-${sf.bits[1]})`, initialType: 'multi' }
      }
    }
    for (const bf of label.bnr_fields || []) {
      if (bf?.data_bits && bitNum >= bf.data_bits[0] && bitNum <= bf.data_bits[1]) {
        return { status: `数值: ${bf.name} (Bit ${bf.data_bits[0]}-${bf.data_bits[1]})`, initialType: 'bnr' }
      }
      if (bf?.sign_bit === bitNum) {
        return { status: `符号位: ${bf.name}`, initialType: 'bnr' }
      }
    }
    return { status: '预留', initialType: 'reserved' }
  }, [label, bitNum])

  useEffect(() => {
    if (!open || !bitNum) return
    const { initialType } = currentStatus
    setType(initialType)
    // 初始化对应表单的值
    form.resetFields()
    if (initialType === 'single') {
      const desc = (label?.discrete_bits || {})[bitNum] || ''
      const parts = String(desc).split(':')
      form.setFieldsValue({
        single_name: parts[0]?.trim() || '',
        single_desc: parts.slice(1).join(':').trim(),
      })
    } else if (initialType === 'multi') {
      const sf = (label?.special_fields || []).find(
        (x) => x?.bits && bitNum >= x.bits[0] && bitNum <= x.bits[1],
      )
      if (sf) {
        const [lo, hi] = sf.bits
        const nBits = hi - lo + 1
        const vstr = Object.entries(sf.values || {})
          .map(([k, v]) => {
            const numK = parseInt(k, 10)
            if (!isNaN(numK)) return `${numK.toString(2).padStart(nBits, '0')}=${v}`
            return `${k}=${v}`
          })
          .join(', ')
        form.setFieldsValue({
          multi_name: sf.name || '',
          multi_bit_lo: lo,
          multi_bit_hi: hi,
          multi_values: vstr,
        })
      } else {
        form.setFieldsValue({ multi_bit_lo: bitNum, multi_bit_hi: bitNum })
      }
    } else if (initialType === 'bnr') {
      const bf = (label?.bnr_fields || []).find(
        (x) =>
          (x?.data_bits && bitNum >= x.data_bits[0] && bitNum <= x.data_bits[1]) ||
          x?.sign_bit === bitNum,
      )
      if (bf) {
        form.setFieldsValue({
          bnr_name: bf.name || '',
          bnr_bit_lo: bf.data_bits?.[0] ?? bitNum,
          bnr_bit_hi: bf.data_bits?.[1] ?? bitNum,
          bnr_encoding: bf.encoding || 'bnr',
          bnr_sign_bit: bf.sign_bit ?? undefined,
          bnr_resolution: bf.resolution ?? undefined,
          bnr_unit: bf.unit || '',
        })
      } else {
        form.setFieldsValue({
          bnr_bit_lo: bitNum,
          bnr_bit_hi: bitNum,
          bnr_encoding: 'bnr',
        })
      }
    }
  }, [open, bitNum, label, form, currentStatus])

  const handleOk = async () => {
    if (type === 'reserved') {
      onSave({ type: 'reserved', bitNum })
      return
    }
    try {
      const vals = await form.validateFields()
      onSave({ type, bitNum, values: vals })
    } catch {
      /* keep open */
    }
  }

  const typeOptions = [
    { value: 'reserved', label: '预留' },
    { value: 'single', label: '单 bit' },
    { value: 'multi', label: '多 bit 枚举' },
    { value: 'bnr', label: '数值 (BNR/BCD)' },
  ]

  const canDelete = currentStatus.initialType !== 'reserved'

  return (
    <Modal
      title={
        <Space>
          <span>{`编辑 Bit ${bitNum || ''}`}</span>
          <Text type="secondary" style={{ fontSize: 12 }}>
            当前：{currentStatus.status}
          </Text>
        </Space>
      }
      open={open}
      onCancel={onCancel}
      width={640}
      destroyOnClose
      footer={[
        <Button key="cancel" onClick={onCancel}>取消</Button>,
        canDelete ? (
          <Popconfirm key="del" title="确定删除此字段定义？" okButtonProps={{ danger: true }} onConfirm={() => onDelete(bitNum)} okText="删除" cancelText="取消">
            <Button danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        ) : null,
        <Button key="ok" type="primary" onClick={handleOk}>确定</Button>,
      ].filter(Boolean)}
    >
      <Radio.Group
        value={type}
        onChange={(e) => setType(e.target.value)}
        optionType="button"
        buttonStyle="solid"
        options={typeOptions}
        style={{ marginBottom: 16 }}
      />

      {type === 'reserved' && (
        <Alert type="info" showIcon message={`确认后，Bit ${bitNum} 将标记为预留（清除当前定义）`} />
      )}

      {type === 'single' && (
        <Form form={form} layout="vertical">
          <Form.Item name="single_name" label="字段名称" rules={[{ required: true, message: '请输入字段名' }]}>
            <Input placeholder="如：脚蹬状态" />
          </Form.Item>
          <Form.Item name="single_desc" label="含义说明">
            <Input placeholder="如：1=解除, 0=正常" />
          </Form.Item>
          <Alert
            type="info"
            showIcon
            style={{ padding: '4px 10px', fontSize: 12 }}
            message={`保存后写入 discrete_bits[${bitNum}] = "字段名: 含义说明"`}
          />
        </Form>
      )}

      {type === 'multi' && (
        <Form form={form} layout="vertical">
          <Form.Item name="multi_name" label="字段名称" rules={[{ required: true, message: '请输入字段名' }]}>
            <Input placeholder="如：牵引状态" />
          </Form.Item>
          <Form.Item label="位范围" required>
            <Space>
              <span>Bit</span>
              <Form.Item name="multi_bit_lo" noStyle rules={[{ required: true }]}>
                <InputNumber min={9} max={29} />
              </Form.Item>
              <span>-</span>
              <Form.Item name="multi_bit_hi" noStyle rules={[{ required: true }]}>
                <InputNumber min={9} max={29} />
              </Form.Item>
            </Space>
          </Form.Item>
          <Form.Item
            name="multi_values"
            label="枚举值定义（二进制=含义，逗号分隔）"
            tooltip="如 00=无效, 01=有效, 10=故障, 11=正常"
          >
            <Input placeholder="00=无效, 01=有效, 10=故障, 11=正常" />
          </Form.Item>
        </Form>
      )}

      {type === 'bnr' && (
        <Form form={form} layout="vertical">
          <Form.Item name="bnr_name" label="字段名称" rules={[{ required: true, message: '请输入字段名' }]}>
            <Input placeholder="如：转弯角度" />
          </Form.Item>
          <Form.Item label="数据位范围" required>
            <Space>
              <span>Bit</span>
              <Form.Item name="bnr_bit_lo" noStyle rules={[{ required: true }]}>
                <InputNumber min={9} max={29} />
              </Form.Item>
              <span>-</span>
              <Form.Item name="bnr_bit_hi" noStyle rules={[{ required: true }]}>
                <InputNumber min={9} max={29} />
              </Form.Item>
            </Space>
          </Form.Item>
          <Form.Item name="bnr_encoding" label="编码类型" initialValue="bnr">
            <Select
              options={[
                { value: 'bnr', label: 'BNR (二进制数值)' },
                { value: 'bcd', label: 'BCD (十进制编码)' },
              ]}
            />
          </Form.Item>
          <Form.Item name="bnr_sign_bit" label="符号位（可选，有符号数填写 9-29）">
            <InputNumber min={9} max={29} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="bnr_resolution" label="分辨率（可选）">
            <InputNumber step={0.000001} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="bnr_unit" label="单位">
            <Input placeholder="如：°" />
          </Form.Item>
        </Form>
      )}
    </Modal>
  )
}


// ════════════════════════ 字段汇总表 ════════════════════════


function FieldsSummary({ label, onClickField, onDelete, readOnly }) {
  const rows = []
  Object.entries(label?.discrete_bits || {}).forEach(([k, v]) => {
    const bit = parseInt(k, 10)
    rows.push({
      key: `single-${bit}`,
      range: `Bit ${bit}`,
      firstBit: bit,
      kind: 'single',
      kindLabel: '单bit',
      name: String(v || '').split(':')[0].trim() || '(未命名)',
    })
  })
  ;(label?.special_fields || []).forEach((sf, idx) => {
    const [lo, hi] = sf.bits || [0, 0]
    rows.push({
      key: `multi-${idx}`,
      range: `Bit ${lo}-${hi}`,
      firstBit: lo,
      kind: 'multi',
      kindLabel: '枚举',
      name: sf.name || '(未命名)',
    })
  })
  ;(label?.bnr_fields || []).forEach((bf, idx) => {
    const [lo, hi] = bf.data_bits || [0, 0]
    const isBcd = bf.encoding === 'bcd'
    const name = `${bf.name || '(未命名)'}${isBcd ? (bf.unit ? ` (${bf.unit})` : '') : ` (${bf.resolution ?? 'N/A'}${bf.unit || ''})`}`
    rows.push({
      key: `bnr-${idx}`,
      range: `Bit ${lo}-${hi}`,
      firstBit: lo,
      kind: isBcd ? 'bnr' : 'bnr',
      kindLabel: isBcd ? 'BCD' : 'BNR',
      name,
    })
  })
  rows.sort((a, b) => (a.firstBit || 0) - (b.firstBit || 0))

  if (rows.length === 0) {
    return <Empty description="暂无字段定义；点击上方位图 Bit 9-29 添加" image={Empty.PRESENTED_IMAGE_SIMPLE} />
  }

  return (
    <Table
      size="small"
      pagination={false}
      rowKey="key"
      dataSource={rows}
      onRow={(r) => ({
        onClick: () => onClickField(r.firstBit),
        style: { cursor: 'pointer' },
      })}
      columns={[
        { title: '位号', dataIndex: 'range', width: 120, render: (v) => <Tag color="purple">{v}</Tag> },
        {
          title: '类型',
          dataIndex: 'kind',
          width: 84,
          render: (_, r) => <TypeBadge kind={r.kind === 'bnr' ? 'bnr' : r.kind} />,
        },
        { title: '名称', dataIndex: 'name' },
        !readOnly && {
          title: '操作',
          key: 'op',
          width: 64,
          render: (_, r) => (
            <Popconfirm
              title="删除此字段？"
              okButtonProps={{ danger: true }}
              onConfirm={(e) => {
                e?.stopPropagation?.()
                onDelete(r.firstBit)
              }}
              onCancel={(e) => e?.stopPropagation?.()}
              okText="删除"
              cancelText="取消"
            >
              <Button
                size="small"
                danger
                icon={<DeleteOutlined />}
                onClick={(e) => e.stopPropagation()}
              />
            </Popconfirm>
          ),
        },
      ].filter(Boolean)}
    />
  )
}


// ════════════════════════ 工具函数：删/改/冲突 ════════════════════════


function deleteFieldAtBit(label, bitNum) {
  // 返回新的 label（不修改原对象）
  const next = cloneDeep(label)
  const dbits = next.discrete_bits || {}
  if (dbits[bitNum] != null) {
    delete dbits[bitNum]
    next.discrete_bits = dbits
    return next
  }
  const sfs = next.special_fields || []
  for (let i = sfs.length - 1; i >= 0; i -= 1) {
    const sf = sfs[i]
    if (sf?.bits && bitNum >= sf.bits[0] && bitNum <= sf.bits[1]) {
      sfs.splice(i, 1)
      next.special_fields = sfs
      return next
    }
  }
  const bfs = next.bnr_fields || []
  for (let i = bfs.length - 1; i >= 0; i -= 1) {
    const bf = bfs[i]
    const inRange =
      bf?.data_bits && bitNum >= bf.data_bits[0] && bitNum <= bf.data_bits[1]
    if (inRange || bf?.sign_bit === bitNum) {
      bfs.splice(i, 1)
      next.bnr_fields = bfs
      return next
    }
  }
  return next
}


function clearRangeInLabel(label, lo, hi) {
  let cur = label
  for (let b = lo; b <= hi; b += 1) {
    cur = deleteFieldAtBit(cur, b)
  }
  return cur
}


function parseMultiValues(str, nBits) {
  const out = {}
  if (!str) return out
  String(str)
    .split(/[,，]/)
    .forEach((pair) => {
      const parts = pair.split(/[=＝]/)
      if (parts.length < 2) return
      const key = parts[0].trim()
      const value = parts.slice(1).join('=').trim()
      if (!key || !value) return
      if (/^[01]+$/.test(key)) {
        out[parseInt(key, 2)] = value
      } else {
        const n = parseInt(key, 10)
        if (!isNaN(n)) out[n] = value
      }
    })
  return out
}


// ════════════════════════ 主组件 ════════════════════════


function LabelCard({ item, onClick, readOnly }) {
  const discreteCount = Object.keys(item.discrete_bits || {}).length
  const specialCount = (item.special_fields || []).length
  const bnrCount = (item.bnr_fields || []).length
  const empty = discreteCount === 0 && specialCount === 0 && bnrCount === 0
  const handleClick = (e) => {
    e.preventDefault()
    e.stopPropagation()
    onClick?.()
  }
  return (
    <div
      onClick={handleClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick?.()
        }
      }}
      style={{
        height: '100%',
        cursor: 'pointer',
        borderRadius: 8,
        border: '1px solid rgba(63,63,70,0.6)',
        background: 'rgba(24,24,27,0.6)',
        padding: '10px 12px',
        transition: 'all 0.18s ease',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = '#a78bfa'
        e.currentTarget.style.boxShadow = '0 0 0 2px rgba(139,92,246,0.18)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'rgba(63,63,70,0.6)'
        e.currentTarget.style.boxShadow = 'none'
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <Space size={8}>
          <Tag color="purple" style={{ margin: 0, fontFamily: 'Menlo, monospace', fontSize: 13 }}>
            {item.label_oct || '???'}
          </Tag>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {item.direction || '-'}
          </Text>
        </Space>
        {readOnly ? <Tag icon={<EyeOutlined />} color="default">查看</Tag> : <Tag icon={<EditOutlined />} color="blue">编辑</Tag>}
      </div>
      <div style={{ fontSize: 13, color: '#e4e4e7', marginBottom: 8, fontWeight: 500, minHeight: 18 }}>
        {item.name || '未命名'}
      </div>
      <Space size={4} wrap>
        {discreteCount > 0 && <Tag color="green" style={{ margin: 0 }}>离散位: {discreteCount}</Tag>}
        {specialCount > 0 && <Tag color="purple" style={{ margin: 0 }}>特殊字段: {specialCount}</Tag>}
        {bnrCount > 0 && <Tag color="blue" style={{ margin: 0 }}>BNR: {bnrCount}</Tag>}
        {empty && <Tag style={{ margin: 0 }} color="default">无字段定义</Tag>}
      </Space>
    </div>
  )
}


export default function Arinc429SpecEditor({
  value,
  onChange,
  readOnly,
  /**
   * 视图切换通知：'list' = 卡片列表；'detail' = 单 Label 详情
   * 父页可据此隐藏/显示外层 UI（草稿头、元信息、其它 Tabs 等）
   */
  onViewModeChange,
  /**
   * 点击详情页的「保存 Label」按钮时调用。返回 Promise 表示正在写库。
   * 调用成功后组件会自动退回列表视图。若未传入，则「保存 Label」只是返回列表。
   */
  onSaveLabel,
  saveLabelLoading,
}) {
  const [meta, setMeta] = useState(value?.protocol_meta || {})
  const [labels, setLabels] = useState((value?.labels || []).map(normalizeLabel))
  const [selectedOct, setSelectedOct] = useState(null)
  const [keyword, setKeyword] = useState('')
  const [newLabelModal, setNewLabelModal] = useState(false)
  const [bitEdit, setBitEdit] = useState({ open: false, bitNum: null })
  /** 进入详情视图时抓取的快照，用于"放弃并返回" */
  const [labelSnapshot, setLabelSnapshot] = useState(null)

  useEffect(() => {
    setMeta(value?.protocol_meta || {})
    const ls = (value?.labels || []).map(normalizeLabel)
    setLabels(ls)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  useEffect(() => {
    onViewModeChange?.(selectedOct ? 'detail' : 'list')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedOct])

  const enterLabelDetail = (oct) => {
    const hit = labels.find((l) => l.label_oct === oct)
    setLabelSnapshot(hit ? cloneDeep(hit) : null)
    setSelectedOct(oct)
  }

  const selected = useMemo(
    () => labels.find((l) => l.label_oct === selectedOct) || null,
    [labels, selectedOct],
  )

  const bitModel = useMemo(() => buildBitModel(selected), [selected])

  const emit = (nextLabels, nextMeta = meta) => {
    onChange?.({ ...value, protocol_meta: nextMeta, labels: nextLabels })
  }

  const updateMeta = (patch) => {
    const next = { ...meta, ...patch }
    setMeta(next)
    emit(labels, next)
  }

  const updateSelected = (patch) => {
    if (!selected) return
    const next = labels.map((l) => (l.label_oct === selected.label_oct ? { ...l, ...patch } : l))
    setLabels(next)
    emit(next)
  }

  const replaceSelected = (nextLabel) => {
    const next = labels.map((l) => (l.label_oct === selected.label_oct ? normalizeLabel(nextLabel) : l))
    setLabels(next)
    emit(next)
  }

  const filteredLabels = useMemo(() => {
    const kw = (keyword || '').toLowerCase()
    if (!kw) return labels
    return labels.filter(
      (l) =>
        (l.label_oct || '').toLowerCase().includes(kw) ||
        (l.name || '').toLowerCase().includes(kw),
    )
  }, [labels, keyword])

  // ── Label CRUD ──
  const addLabel = (row) => {
    const oct = String(row.label_oct || '').trim()
    if (!oct || !/^[0-7]+$/.test(oct)) {
      Modal.error({ title: '非法 label_oct', content: '请输入 1-3 位八进制数字 (0-7)' })
      return
    }
    if (labels.some((l) => l.label_oct === oct)) {
      Modal.error({ title: 'label_oct 已存在', content: oct })
      return
    }
    const newItem = normalizeLabel({
      label_oct: oct,
      name: row.name || '',
      direction: row.direction || 'input',
      ssm_type: row.ssm_type || 'bnr',
    })
    const next = [...labels, newItem].sort((a, b) => (a.label_dec ?? 999) - (b.label_dec ?? 999))
    setLabels(next)
    emit(next)
    setNewLabelModal(false)
    // 新增后立即进入详情视图，并以新建项作为快照
    setLabelSnapshot(cloneDeep(newItem))
    setSelectedOct(oct)
  }

  const deleteLabel = () => {
    if (!selected) return
    const next = labels.filter((l) => l.label_oct !== selected.label_oct)
    setLabels(next)
    setLabelSnapshot(null)
    setSelectedOct(null)
    emit(next)
  }

  // ── Bit 编辑：统一入口 ──
  const openBitEditor = (bitNum) => {
    if (!selected || readOnly) return
    if (bitNum < 9 || bitNum > 29) {
      message.warning('只能编辑 Bit 9-29')
      return
    }
    setBitEdit({ open: true, bitNum })
  }

  const handleBitSave = ({ type, bitNum, values }) => {
    if (!selected) return
    let next = cloneDeep(selected)
    // 先删掉当前 bit 现有字段
    next = deleteFieldAtBit(next, bitNum)

    if (type === 'reserved') {
      replaceSelected(next)
      setBitEdit({ open: false, bitNum: null })
      return
    }

    if (type === 'single') {
      const name = (values.single_name || '').trim()
      const desc = (values.single_desc || '').trim()
      next.discrete_bits = next.discrete_bits || {}
      next.discrete_bits[bitNum] = desc ? `${name}: ${desc}` : name
    } else if (type === 'multi') {
      const name = (values.multi_name || '').trim()
      const lo = Number(values.multi_bit_lo)
      const hi = Number(values.multi_bit_hi)
      if (lo > hi || lo < 9 || hi > 29) {
        message.error('位范围必须在 9..29 且起始≤结束')
        return
      }
      // 清掉新范围内所有字段，避免重叠
      next = clearRangeInLabel(next, lo, hi)
      const vmap = parseMultiValues(values.multi_values, hi - lo + 1)
      next.special_fields = next.special_fields || []
      next.special_fields.push({ name, bits: [lo, hi], type: 'enum', values: vmap })
    } else if (type === 'bnr') {
      const name = (values.bnr_name || '').trim()
      const lo = Number(values.bnr_bit_lo)
      const hi = Number(values.bnr_bit_hi)
      if (lo > hi || lo < 9 || hi > 29) {
        message.error('数据位范围必须在 9..29 且起始≤结束')
        return
      }
      next = clearRangeInLabel(next, lo, hi)
      const signBit = values.bnr_sign_bit ? Number(values.bnr_sign_bit) : null
      if (signBit) next = deleteFieldAtBit(next, signBit)
      next.bnr_fields = next.bnr_fields || []
      next.bnr_fields.push({
        name,
        data_bits: [lo, hi],
        encoding: values.bnr_encoding || 'bnr',
        sign_bit: signBit || null,
        resolution: values.bnr_resolution ?? null,
        unit: values.bnr_unit || '',
      })
    }

    replaceSelected(next)
    setBitEdit({ open: false, bitNum: null })
  }

  const handleBitDelete = (bitNum) => {
    if (!selected) return
    const next = deleteFieldAtBit(selected, bitNum)
    replaceSelected(next)
    setBitEdit({ open: false, bitNum: null })
  }

  const isLabelDirty = useMemo(() => {
    if (!selected || !labelSnapshot) return false
    return JSON.stringify(selected) !== JSON.stringify(labelSnapshot)
  }, [selected, labelSnapshot])

  const handleSaveLabel = async () => {
    if (!onSaveLabel) {
      setLabelSnapshot(null)
      setSelectedOct(null)
      return
    }
    try {
      await onSaveLabel()
      setLabelSnapshot(null)
      setSelectedOct(null)
    } catch {
      /* 保存失败时保持在详情页，让父页面提示错误 */
    }
  }

  const handleAbandonAndBack = () => {
    // 回滚当前编辑中的 label 到进入详情时的快照，再回列表
    if (labelSnapshot && selected) {
      const next = labels.map((l) => (l.label_oct === selected.label_oct ? normalizeLabel(labelSnapshot) : l))
      setLabels(next)
      emit(next)
    }
    setLabelSnapshot(null)
    setSelectedOct(null)
  }

  // ── UI ──
  // 用 selectedOct 作为"是否进入详情页"的判据：null → 卡片列表，非 null → 详情页
  const mode = selectedOct ? 'detail' : 'list'

  return (
    <div>
      {/* 协议元信息：仅在列表视图显示；详情视图专注编辑 Label 本身 */}
      {mode === 'list' && (
        <Card size="small" title="协议元信息" style={{ marginBottom: 12 }}>
          <Row gutter={12}>
            <Col span={10}>
              <Text type="secondary" style={{ fontSize: 12 }}>协议名 (meta.name)</Text>
              <Input
                size="small"
                disabled={readOnly}
                value={meta.name || ''}
                onChange={(e) => updateMeta({ name: e.target.value })}
                style={{ marginTop: 4 }}
              />
            </Col>
            <Col span={8}>
              <Text type="secondary" style={{ fontSize: 12 }}>描述</Text>
              <Input
                size="small"
                disabled={readOnly}
                value={meta.description || ''}
                onChange={(e) => updateMeta({ description: e.target.value })}
                style={{ marginTop: 4 }}
              />
            </Col>
            <Col span={6}>
              <Alert
                type="info"
                showIcon
                style={{ padding: '4px 8px' }}
                message={<Text style={{ fontSize: 12 }}>版本号在审批通过后自动升级（V1.0 → V2.0）</Text>}
              />
            </Col>
          </Row>
        </Card>
      )}

      {mode === 'list' ? (
        <Card
          size="small"
          title={
            <Space>
              <span>Labels</span>
              <Tag>{labels.length}</Tag>
              {readOnly && <Tag color="default" icon={<EyeOutlined />}>只读模式</Tag>}
            </Space>
          }
          extra={
            <Space>
              <Input
                size="small"
                prefix={<SearchOutlined />}
                placeholder="搜索 八进制 / 名称"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                allowClear
                style={{ width: 220 }}
              />
              {!readOnly && (
                <Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => setNewLabelModal(true)}>
                  添加 Label
                </Button>
              )}
            </Space>
          }
        >
          {filteredLabels.length === 0 ? (
            <Empty
              description={
                labels.length === 0
                  ? (readOnly ? '该设备暂无协议定义' : '暂无 Label，点击「添加 Label」创建')
                  : '未找到匹配的 Label'
              }
            />
          ) : (
            <Row gutter={[12, 12]}>
              {filteredLabels.map((it) => (
                <Col key={it.label_oct} xs={24} sm={12} md={8} lg={6} xxl={4}>
                  <LabelCard
                    item={it}
                    readOnly={readOnly}
                    onClick={() => enterLabelDetail(it.label_oct)}
                  />
                </Col>
              ))}
            </Row>
          )}
        </Card>
      ) : (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {/* 详情页头部：返回按钮 + 当前 Label 标识 + 操作 */}
          <Card
            size="small"
            bodyStyle={{ padding: '10px 12px' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
              <Space size={12} wrap>
                {readOnly ? (
                  <Button icon={<ArrowLeftOutlined />} onClick={() => setSelectedOct(null)}>
                    返回 Label 列表
                  </Button>
                ) : isLabelDirty ? (
                  <Popconfirm
                    title="放弃本次 Label 修改？"
                    description="返回后此 Label 将回滚到进入时的状态。"
                    okText="放弃"
                    cancelText="继续编辑"
                    okButtonProps={{ danger: true }}
                    onConfirm={handleAbandonAndBack}
                  >
                    <Button icon={<ArrowLeftOutlined />}>放弃并返回</Button>
                  </Popconfirm>
                ) : (
                  <Button icon={<ArrowLeftOutlined />} onClick={handleAbandonAndBack}>
                    返回 Label 列表
                  </Button>
                )}
                <Tag color="purple" style={{ fontSize: 13, padding: '2px 10px', fontFamily: 'Menlo, monospace' }}>
                  {selected?.label_oct}
                </Tag>
                <Text strong style={{ fontSize: 15 }}>{selected?.name || '(未命名)'}</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>dec = {selected?.label_dec ?? '-'}</Text>
                {readOnly ? (
                  <Tag icon={<EyeOutlined />} color="default">只读</Tag>
                ) : isLabelDirty ? (
                  <Tag color="gold">本 Label 未保存</Tag>
                ) : (
                  <Tag color="green">本 Label 已同步</Tag>
                )}
              </Space>
              {!readOnly && (
                <Space size={8}>
                  <Popconfirm
                    title="删除此 Label？"
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true }}
                    onConfirm={deleteLabel}
                  >
                    <Button danger icon={<DeleteOutlined />}>删除 Label</Button>
                  </Popconfirm>
                  <Button
                    type="primary"
                    icon={onSaveLabel ? <SaveOutlined /> : <CheckOutlined />}
                    loading={!!saveLabelLoading}
                    onClick={handleSaveLabel}
                  >
                    {onSaveLabel ? '保存 Label 并返回' : '完成编辑'}
                  </Button>
                </Space>
              )}
            </div>
          </Card>

          {!selected ? (
            <Card><Empty description="该 Label 不存在，返回列表" /></Card>
          ) : (
            <>
              <Card size="small" title="基本信息">
                <Row gutter={12}>
                  <Col span={8}>
                    <Text type="secondary" style={{ fontSize: 12 }}>名称</Text>
                    <Input size="small" disabled={readOnly} value={selected.name} onChange={(e) => updateSelected({ name: e.target.value })} style={{ marginTop: 4 }} />
                  </Col>
                  <Col span={6}>
                    <Text type="secondary" style={{ fontSize: 12 }}>方向</Text>
                    <Select
                      size="small"
                      disabled={readOnly}
                      value={selected.direction}
                      onChange={(v) => updateSelected({ direction: v })}
                      options={DIRECTIONS}
                      style={{ width: '100%', marginTop: 4 }}
                      allowClear
                    />
                  </Col>
                  <Col span={5}>
                    <Text type="secondary" style={{ fontSize: 12 }}>SSM 类型</Text>
                    <Select size="small" disabled={readOnly} value={selected.ssm_type} onChange={(v) => updateSelected({ ssm_type: v })} options={SSM_TYPES} style={{ width: '100%', marginTop: 4 }} />
                  </Col>
                  <Col span={5}>
                    <Text type="secondary" style={{ fontSize: 12 }}>单位</Text>
                    <Input size="small" disabled={readOnly} value={selected.unit} onChange={(e) => updateSelected({ unit: e.target.value })} style={{ marginTop: 4 }} />
                  </Col>
                  <Col span={8} style={{ marginTop: 8 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>数据类型</Text>
                    <Input size="small" disabled={readOnly} value={selected.data_type} onChange={(e) => updateSelected({ data_type: e.target.value })} style={{ marginTop: 4 }} />
                  </Col>
                  <Col span={8} style={{ marginTop: 8 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>来源 (sources, 逗号分隔)</Text>
                    <Input
                      size="small"
                      disabled={readOnly}
                      value={(selected.sources || []).join(', ')}
                      onChange={(e) => updateSelected({ sources: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })}
                      style={{ marginTop: 4 }}
                    />
                  </Col>
                  <Col span={8} style={{ marginTop: 8 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>range_desc</Text>
                    <Input size="small" disabled={readOnly} value={selected.range_desc} onChange={(e) => updateSelected({ range_desc: e.target.value })} style={{ marginTop: 4 }} />
                  </Col>
                  <Col span={24} style={{ marginTop: 8 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>备注</Text>
                    <Input.TextArea
                      size="small"
                      disabled={readOnly}
                      value={selected.notes}
                      onChange={(e) => updateSelected({ notes: e.target.value })}
                      rows={2}
                      style={{ marginTop: 4 }}
                    />
                  </Col>
                </Row>
              </Card>

              <Card
                size="small"
                title={
                  readOnly
                    ? '32-bit 位图（只读查看）'
                    : '32-bit 位图（点击 Bit 9-29 添加/编辑/删除字段）'
                }
              >
                <BitMap label={selected} bitModel={bitModel} readOnly={readOnly} onClickBit={openBitEditor} />
              </Card>

              <Card size="small" title={readOnly ? '字段定义（只读）' : '字段定义（可点击行编辑）'}>
                <FieldsSummary
                  label={selected}
                  readOnly={readOnly}
                  onClickField={openBitEditor}
                  onDelete={(bitNum) => {
                    const next = deleteFieldAtBit(selected, bitNum)
                    replaceSelected(next)
                  }}
                />
              </Card>
            </>
          )}
        </Space>
      )}

      <NewLabelModal
        open={newLabelModal}
        onCancel={() => setNewLabelModal(false)}
        onOk={addLabel}
      />
      <BitEditModal
        open={bitEdit.open}
        bitNum={bitEdit.bitNum}
        label={selected}
        onCancel={() => setBitEdit({ open: false, bitNum: null })}
        onSave={handleBitSave}
        onDelete={handleBitDelete}
      />
    </div>
  )
}


function NewLabelModal({ open, onCancel, onOk }) {
  const [form] = Form.useForm()
  useEffect(() => { if (open) form.resetFields() }, [open, form])
  return (
    <Modal
      title="新增 Label"
      open={open}
      onCancel={onCancel}
      onOk={() => form.validateFields().then(onOk).catch(() => {})}
      okText="添加"
      cancelText="取消"
      destroyOnClose
    >
      <Form form={form} layout="vertical">
        <Form.Item name="label_oct" label="Label (八进制, 0-7 数字)" rules={[{ required: true, pattern: /^[0-7]+$/, message: '请输入合法八进制' }]}>
          <Input placeholder="如 076" />
        </Form.Item>
        <Form.Item name="name" label="名称" rules={[{ required: true }]}>
          <Input placeholder="如 GNSS_Altitude" />
        </Form.Item>
        <Form.Item name="direction" label="方向">
          <Select options={DIRECTIONS} allowClear />
        </Form.Item>
        <Form.Item name="ssm_type" label="SSM 类型" initialValue="bnr">
          <Select options={SSM_TYPES} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
