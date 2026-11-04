export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch('/api' + path, { ...init, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'BD-Workbench', ...init.headers } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && path !== '/login') window.dispatchEvent(new Event('session-expired'));
    throw new Error(typeof body.detail === 'string' ? body.detail : '配置不完整或格式不正确，请检查必填项');
  }
  return body as T;
}
export type User = { id: number; username: string; name: string; role: 'superadmin' | 'admin' | 'bd'; theme: string; demo: boolean; active?: boolean };
export type Bonus = { id: number; order_no: string; customer: string; service: string; owner: string; period: string; basis: string; accrued: string; paid: string; unpaid: string; shared: boolean; issue: string; status: string; rule_version: string; source: string };
export const themes = [
  { key: 'blue', name: '经典蓝', primary: '#1677FF', bg: '#F5F7FA', nav: '#001529' },
  { key: 'green', name: '清新绿', primary: '#16803D', bg: '#F4F8F5', nav: '#123126' },
  { key: 'purple', name: '雅致紫', primary: '#722ED1', bg: '#F7F5FA', nav: '#261B3A' },
  { key: 'cyan', name: '湖水青', primary: '#087F8C', bg: '#F3F8F9', nav: '#12343B' },
  { key: 'amber', name: '暖琥珀', primary: '#9A6200', bg: '#FAF8F3', nav: '#352A1B' },
];
export const money = (value: string | number) => Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
