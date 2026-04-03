import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ConfigProvider 
      locale={zhCN}
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: '#58a6ff',
          colorBgBase: '#0d1117',
          colorBgContainer: '#161b22',
          colorBgElevated: '#21262d',
          colorBorder: '#30363d',
          colorBorderSecondary: '#30363d',
          colorText: '#c9d1d9',
          colorTextSecondary: '#8b949e',
          colorSuccess: '#3fb950',
          colorWarning: '#d29922',
          colorError: '#f85149',
          colorInfo: '#58a6ff',
          fontFamily: "'Noto Sans SC', 'Microsoft YaHei', -apple-system, BlinkMacSystemFont, sans-serif",
          borderRadius: 8,
          controlHeight: 36,
        },
        components: {
          Card: {
            colorBgContainer: '#161b22',
            colorBorderSecondary: '#30363d',
          },
          Table: {
            colorBgContainer: '#161b22',
            headerBg: '#21262d',
            headerColor: '#c9d1d9',
            rowHoverBg: '#21262d',
            borderColor: '#30363d',
          },
          Menu: {
            itemBg: 'transparent',
            itemSelectedBg: 'rgba(88, 166, 255, 0.15)',
            itemSelectedColor: '#58a6ff',
            itemHoverBg: '#21262d',
            itemColor: '#c9d1d9',
            groupTitleColor: '#8b949e',
            groupTitleFontSize: 12,
          },
          Button: {
            colorPrimary: '#21262d',
            colorPrimaryHover: '#30363d',
            colorPrimaryActive: '#30363d',
            primaryColor: '#c9d1d9',
            borderColorDisabled: '#30363d',
          },
          Select: {
            colorBgContainer: '#161b22',
            colorBorder: '#30363d',
            optionSelectedBg: 'rgba(88, 166, 255, 0.15)',
            optionActiveBg: '#21262d',
          }
        }
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>,
)
