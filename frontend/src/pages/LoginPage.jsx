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
      navigate('/dashboard', { replace: true })
    }
  }, [ready, user, navigate])

  const onFinish = async (values) => {
    setLoading(true)
    try {
      await login(values.username, values.password)
      message.success('登录成功')
      navigate('/dashboard', { replace: true })
    } catch (e) {
      message.error(e.response?.data?.detail || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  if (!ready) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#71717a' }}>
        <div style={{
          width: 28,
          height: 28,
          border: '2px solid rgba(63, 63, 70, 0.5)',
          borderTopColor: '#8b5cf6',
          borderRadius: '50%',
          animation: 'spin 0.8s linear infinite',
          marginRight: 12,
        }} />
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
        background: '#0f0f12',
        padding: 24,
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Ambient glow blob */}
      <div
        style={{
          position: 'absolute',
          top: '20%',
          left: '50%',
          transform: 'translateX(-50%)',
          width: '600px',
          height: '600px',
          background: 'radial-gradient(circle, rgba(139, 92, 246, 0.12) 0%, transparent 70%)',
          filter: 'blur(80px)',
          pointerEvents: 'none',
        }}
      />
      {/* Secondary glow */}
      <div
        style={{
          position: 'absolute',
          bottom: '10%',
          right: '20%',
          width: '400px',
          height: '400px',
          background: 'radial-gradient(circle, rgba(124, 58, 237, 0.08) 0%, transparent 70%)',
          filter: 'blur(60px)',
          pointerEvents: 'none',
        }}
      />
      <Card 
        style={{ 
          width: 420, 
          background: 'rgba(24, 24, 27, 0.7)',
          backdropFilter: 'blur(24px)',
          WebkitBackdropFilter: 'blur(24px)',
          borderColor: 'rgba(63, 63, 70, 0.6)',
          boxShadow: '0 25px 50px rgba(0, 0, 0, 0.4), 0 0 80px rgba(139, 92, 246, 0.08)',
          position: 'relative',
          zIndex: 1,
          borderRadius: 16,
        }}
      >
        <div style={{ textAlign: 'center', marginBottom: 36 }}>
          <div style={{
            width: 56,
            height: 56,
            borderRadius: 16,
            background: 'linear-gradient(135deg, #7c3aed 0%, #8b5cf6 100%)',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 0 32px rgba(139, 92, 246, 0.35)',
            marginBottom: 20,
          }}>
            <DatabaseOutlined style={{ fontSize: 28, color: '#e4e4e7' }} />
          </div>
          <div className="pill-badge" style={{ marginBottom: 14 }}>
            DATA PROCESSING PLATFORM
          </div>
          <Title level={3} style={{ 
            color: '#e4e4e7', 
            marginTop: 0, 
            marginBottom: 8, 
            fontWeight: 700,
            letterSpacing: '-0.02em',
          }}>
            <span className="gradient-text-purple">网络数据</span>
            <span style={{ color: '#e4e4e7' }}>处理</span>
          </Title>
          <Text style={{ color: '#71717a', fontSize: 13 }}>请使用管理员或普通用户账号登录</Text>
        </div>
        <Form layout="vertical" onFinish={onFinish} requiredMark={false}>
          <Form.Item
            name="username"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input 
              prefix={<UserOutlined style={{ color: '#52525b' }} />} 
              placeholder="用户名" 
              size="large" 
              autoComplete="username"
              style={{
                background: 'rgba(9, 9, 11, 0.6)',
                borderColor: 'rgba(63, 63, 70, 0.5)',
                borderRadius: 10,
                height: 44,
              }}
            />
          </Form.Item>
          <Form.Item
            name="password"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password
              prefix={<LockOutlined style={{ color: '#52525b' }} />}
              placeholder="密码"
              size="large"
              autoComplete="current-password"
              style={{
                background: 'rgba(9, 9, 11, 0.6)',
                borderColor: 'rgba(63, 63, 70, 0.5)',
                borderRadius: 10,
                height: 44,
              }}
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0, marginTop: 28 }}>
            <Button 
              type="default"
              className="btn-ghost-purple"
              htmlType="submit" 
              loading={loading} 
              block 
              size="large"
              style={{
                height: 46,
                fontSize: 14,
              }}
            >
              登录
            </Button>
          </Form.Item>
        </Form>
        <Text style={{ display: 'block', marginTop: 24, fontSize: 11, color: '#52525b', textAlign: 'center' }}>
          首次部署默认账号见服务端日志或环境变量 INIT_ADMIN_* / INIT_USER_*
        </Text>
      </Card>
    </div>
  )
}

export default LoginPage
