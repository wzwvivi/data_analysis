import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import 'leaflet/dist/leaflet.css'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ConfigProvider 
      locale={zhCN}
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: '#8b5cf6',
          colorBgBase: '#121217',
          colorBgContainer: 'rgba(29, 29, 36, 0.62)',
          colorBgElevated: '#1d1d24',
          colorBorder: 'rgba(70, 70, 82, 0.45)',
          colorBorderSecondary: 'rgba(70, 70, 82, 0.45)',
          colorText: '#c7c7cf',
          colorTextSecondary: '#9393a1',
          colorSuccess: '#5fd068',
          colorWarning: '#d4a843',
          colorError: '#f05050',
          colorInfo: '#8b5cf6',
          fontFamily: "'Inter', 'Noto Sans SC', 'Microsoft YaHei', -apple-system, BlinkMacSystemFont, sans-serif",
          borderRadius: 12,
          controlHeight: 38,
        },
        components: {
          Card: {
            colorBgContainer: 'rgba(29, 29, 36, 0.62)',
            colorBorderSecondary: 'rgba(70, 70, 82, 0.45)',
          },
          Table: {
            colorBgContainer: 'rgba(29, 29, 36, 0.62)',
            headerBg: 'rgba(29, 29, 36, 0.8)',
            headerColor: '#9393a1',
            rowHoverBg: 'rgba(139, 92, 246, 0.04)',
            borderColor: 'rgba(47, 47, 57, 0.5)',
          },
          Menu: {
            itemBg: 'transparent',
            itemSelectedBg: 'rgba(139, 92, 246, 0.09)',
            itemSelectedColor: '#a78bfa',
            itemHoverBg: 'rgba(29, 29, 36, 0.8)',
            itemColor: '#c7c7cf',
            groupTitleColor: '#7d7d8d',
            groupTitleFontSize: 10,
          },
          Button: {
            colorPrimary: '#5b21b6',
            colorPrimaryHover: '#6d28d9',
            colorPrimaryActive: '#5b21b6',
            primaryColor: '#c4b5fd',
            borderColorDisabled: '#27272a',
            defaultBg: 'rgba(29, 29, 36, 0.85)',
            defaultColor: '#c7c7cf',
            defaultBorderColor: 'rgba(109, 40, 217, 0.3)',
            defaultHoverBg: 'rgba(76, 29, 149, 0.22)',
            defaultHoverColor: '#d4d4d8',
            defaultHoverBorderColor: 'rgba(139, 92, 246, 0.45)',
            defaultActiveBg: 'rgba(76, 29, 149, 0.35)',
            defaultActiveBorderColor: 'rgba(139, 92, 246, 0.6)',
            defaultActiveColor: '#d4d4d8',
          },
          Select: {
            colorBgContainer: 'rgba(29, 29, 36, 0.62)',
            colorBorder: 'rgba(70, 70, 82, 0.45)',
            optionSelectedBg: 'rgba(139, 92, 246, 0.12)',
            optionActiveBg: 'rgba(29, 29, 36, 0.8)',
          }
        }
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>,
)
