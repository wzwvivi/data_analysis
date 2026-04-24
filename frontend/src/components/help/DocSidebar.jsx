import React, { useMemo } from 'react'
import { Menu } from 'antd'

function DocSidebar({ groups, currentKey, onSelect }) {
  const items = useMemo(() => {
    return groups.map((group) => ({
      key: `group:${group.key}`,
      type: 'group',
      label: group.title,
      children: group.docs.map((doc) => ({
        key: doc.key,
        label: doc.title,
      })),
    }))
  }, [groups])

  return (
    <Menu
      mode="inline"
      selectedKeys={currentKey ? [currentKey] : []}
      items={items}
      onClick={({ key }) => onSelect(key)}
      style={{ background: 'transparent', border: 'none' }}
    />
  )
}

export default DocSidebar
