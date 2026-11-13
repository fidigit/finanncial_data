import { useEffect, useRef, useState } from 'react';
import { Button, Pagination, Table } from 'antd';
import type { TableProps } from 'antd';
import type { ColumnsType } from 'antd/es/table';

const widths: Record<string, number> = {
  '季度': 58, 'BD姓名': 60, '付款公司': 138, '付款时间': 80, '所购服务': 104,
  '首购/续费': 54, '订单金额': 82, '是否计发提成': 64, '共享订单': 72,
  '分摊比例': 58, '奖金计算基数': 82, '市场渠道': 72, '转介绍': 76,
  '累计营收': 76, '适用提点（分段提点）': 80, '奖金': 82, '是否发放': 56,
  '是否退款': 56, '备注': 126, '姓名': 60, '会议时间': 82, '会议类型': 82,
  '会议举办地点': 120, '参会企业数': 62, '参会人数': 60, '好友通过率（≥90%）': 82,
  '六重报名数': 66, '意向线索企业数（≥5）': 88, '是否达标': 58, '会议奖金': 82,
  '特殊情况备注': 140, '会后联系': 125, '还否发放奖金': 66, '操作': 58,
};

export default function BonusTableView<T extends object>({ columns, pagination, ...props }: TableProps<T>) {
  const host = useRef<HTMLDivElement>(null);
  const [available, setAvailable] = useState(0);
  const [full, setFull] = useState(false);
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setAvailable(element.clientWidth));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!full) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setFull(false); };
    window.addEventListener('keydown', escape);
    return () => { document.body.style.overflow = previous; window.removeEventListener('keydown', escape); };
  }, [full]);
  let minimum = 0;
  function compact(items: ColumnsType<T>): ColumnsType<T> {
    return items.map(column => {
      if ('children' in column) return { ...column, fixed: undefined, children: compact(column.children) };
      const width = widths[String(column.title)] || widths[String(column.key)] || 85;
      minimum += width;
      return { ...column, width, fixed: undefined, ellipsis: false, align: 'center' };
    });
  }
  const fitted = compact(columns || []);
  const scale = available ? Math.min(1, available / minimum) : 1;
  return <section className={`bonus-fit-section${full ? ' bonus-fit-fullscreen' : ''}`} aria-label="全列奖金表">
    <div className="bonus-fit-toolbar"><Button onClick={() => setFull(v => !v)}>{full ? '退出全屏（Esc）' : '全屏查看'}</Button></div>
    <div className="bonus-fit-host" ref={host}><div className="bonus-fit-content" style={{ width: available ? Math.max(available, minimum) : minimum, zoom: scale }}>
      <Table<T> {...props} columns={fitted} tableLayout="fixed" pagination={false} scroll={undefined} expandable={undefined} />
    </div></div>
    {pagination !== false && pagination && <Pagination {...pagination} className="bonus-fit-pagination" />}
  </section>;
}

export async function downloadBonus(kind: string, query: Record<string, string | number>) {
  const params = new URLSearchParams(Object.entries(query).filter(([key]) => !['page', 'page_size'].includes(key)).map(([key, value]) => [key, String(value)]));
  const response = await fetch(`/api/bonus-export/${kind}?${params}`, { credentials: 'same-origin' });
  if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.detail || '导出失败，请重新登录后重试'); }
  const disposition=response.headers.get('Content-Disposition')||'';
  const encoded=disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const filename=kind==='meetings'?undefined:encoded?decodeURIComponent(encoded):disposition.match(/filename="([^"]+)"/i)?.[1];
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a'); link.href = url; link.download = filename || `${({ sales: '销售奖金表', market: '市场奖金表', meetings: '会议奖金明细' } as Record<string,string>)[kind]}.xlsx`; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
