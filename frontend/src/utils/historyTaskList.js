/** 与独立任务列表 listTasks 调用的 page / pageSize 一致 */
export const HISTORY_TASK_LIST_PAGE = 1
export const HISTORY_TASK_LIST_PAGE_SIZE = 50

export function sortTasksByCreatedAtAsc(tasks) {
  if (!tasks?.length) return []
  return [...tasks].sort((a, b) => {
    const ta = a.created_at ? new Date(a.created_at).getTime() : 0
    const tb = b.created_at ? new Date(b.created_at).getTime() : 0
    if (ta !== tb) return ta - tb
    return (a.id ?? 0) - (b.id ?? 0)
  })
}

/**
 * 历史表按「创建时间升序」展示时，第 index 行（0=本页最旧）的全局任务编号。
 * 与后端 total、倒序分页拉取、本页 n 条一致（total 为库内总条数）。
 */
export function taskNoForHistoryRow(total, page, pageSize, rowCount, indexAsc) {
  if (total < 1 || rowCount < 1) return null
  return total - (page - 1) * pageSize - (rowCount - 1) + indexAsc
}
