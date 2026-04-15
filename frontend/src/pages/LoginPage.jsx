import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Form, Input, Button, Typography, message } from 'antd'
import { DatabaseOutlined, LockOutlined, UserOutlined } from '@ant-design/icons'
import { useAuth } from '../context/AuthContext'

const { Title, Text } = Typography

function LoginPage() {
  const navigate = useNavigate()
  const { login, user, ready } = useAuth()
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (ready && user) {
      navigate('/upload', { replace: true })
    }
  }, [ready, user, navigate])

  const onFinish = async (values) => {
    setLoading(true)
    try {
      await login(values.username, values.password)
      message.success('登录成功')
      navigate('/upload', { replace: true })
    } catch (e) {
      message.error(e.response?.data?.detail || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  if (!ready) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#8b949e' }}>
        加载中…
      </div>
    )
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #0d1117 0%, #161b22 50%, #21262d 100%)',
        padding: 24,
      }}
    >
      <Card style={{ width: 400, background: '#161b22', borderColor: '#30363d' }}>
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <DatabaseOutlined style={{ fontSize: 40, color: '#58a6ff' }} />
          <Title level={3} style={{ color: '#c9d1d9', marginTop: 12, marginBottom: 8 }}>
            网络数据处理
          </Title>
          <Text type="secondary">请使用管理员或普通用户账号登录</Text>
        </div>
        <Form layout="vertical" onFinish={onFinish} requiredMark={false}>
          <Form.Item
            name="username"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input prefix={<UserOutlined />} placeholder="用户名" size="large" autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="password"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="密码"
              size="large"
              autoComplete="current-password"
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" loading={loading} block size="large">
              登录
            </Button>
          </Form.Item>
        </Form>
        <Text type="secondary" style={{ display: 'block', marginTop: 16, fontSize: 12 }}>
          首次部署默认账号见服务端日志或环境变量 INIT_ADMIN_* / INIT_USER_*
        </Text>
      </Card>
    </div>
  )
}

export default LoginPage
