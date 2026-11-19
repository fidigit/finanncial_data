import { useState } from 'react';
import { Alert, App, Button, Card, Descriptions, Modal, Space, Table, Upload } from 'antd';
import { UploadOutlined } from '@ant-design/icons';

type Status = { is_paid: boolean | null };
type Change = { sheet: string; owner: string; quarter: string; order_no: string; before: Status; after: Status };
type Preview = { suffix: string; filename: string; total: number; changed_count: number; rows: Change[] };
type RefundResult = { orders: number; matched: number; added: number; sales: number; market: number };
const show = (value: boolean | null) => value == null ? '待确认' : value ? '是' : '否';

async function uploadFile<T>(endpoint: string, file: File, type: string): Promise<T> {
  const response = await fetch(endpoint + '?' + new URLSearchParams({ filename: file.name }), {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': type, 'X-Requested-With': 'BD-Workbench' }, body: file,
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(result.detail || '导入失败，请检查文件格式和内容');
  return result as T;
}

export default function BonusImport() {
  const { message } = App.useApp();
  const [busy, setBusy] = useState(false), [file, setFile] = useState<File>();
  const [preview, setPreview] = useState<Preview>(), [error, setError] = useState('');
  const submit = (file: File, preview: boolean) => uploadFile<Preview>(
    '/api/bonus-import/all' + (preview ? '/preview' : ''), file,
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  );
  return <>
    <Upload accept=".xlsx" showUploadList={false} disabled={busy} beforeUpload={async selected => {
      if (!selected.name.toLowerCase().endsWith('.xlsx') || selected.size > 10 * 1024 * 1024) {
        message.error('请选择 10MB 以内的系统导出 XLSX 文件'); return Upload.LIST_IGNORE;
      }
      setBusy(true); setError('');
      try { const result = await submit(selected, true); setFile(selected); setPreview(result); }
      catch (e) { message.error((e as Error).message); }
      finally { setBusy(false); }
      return Upload.LIST_IGNORE;
    }}><Button aria-label="导入发放结果" icon={<UploadOutlined />} loading={busy}>导入发放结果</Button></Upload>
    <Modal title="奖金发放状态导入预览" width={820} open={!!preview} closable={!busy} maskClosable={!busy}
      confirmLoading={busy} okText="确认导入"
      onCancel={() => { if (!busy) { setPreview(undefined); setFile(undefined); setError(''); } }}
      onOk={async () => {
        if (!file) return;
        setBusy(true); setError('');
        try {
          const result = await submit(file, false);
          message.success('导入成功，已更新 ' + result.changed_count + ' 条记录');
          setPreview(undefined); setFile(undefined);
          window.dispatchEvent(new Event('bonus-rules-changed'));
        } catch (e) { setError((e as Error).message); }
        finally { setBusy(false); }
      }}>
      <Alert type="info" showIcon title="只回写各表的发放状态" description="请使用当前账号最后一次导出的文件。确认导入时会再次校验，整批成功后才保存。" />
      {error && <Alert style={{ marginTop: 12 }} type="error" showIcon title={error} />}
      <Descriptions style={{ marginTop: 16, marginBottom: 16 }} column={2} items={[
        { key: 'file', label: '文件', children: preview?.filename, span: 2 },
        { key: 'version', label: '导出版本', children: preview?.suffix },
        { key: 'count', label: '记录', children: '共 ' + (preview?.total || 0) + ' 条，' + (preview?.changed_count || 0) + ' 条将变更' },
      ]} />
      <Table<Change> size="small" rowKey={(_, i) => String(i)} pagination={false} dataSource={preview?.rows || []}
        scroll={{ y: 330 }} locale={{ emptyText: '没有状态变化，确认后此版本会标记为已导入' }} columns={[
          { title: '工作表', dataIndex: 'sheet' }, { title: 'BD 姓名', dataIndex: 'owner' },
          { title: '季度', dataIndex: 'quarter' }, { title: '订单号／会议日期', dataIndex: 'order_no' },
          { title: '发放状态', render: (_, row) => show(row.before.is_paid) + ' → ' + show(row.after.is_paid) },
        ]} />
      {(preview?.changed_count || 0) > 50 && <p className="subtext">仅预览前 50 条，确认后提交全部变更。</p>}
    </Modal>
  </>;
}

export function RefundImportButton() {
  const { message, modal } = App.useApp();
  const [busy, setBusy] = useState(false);
  return <Upload accept=".csv,.xlsx" showUploadList={false} disabled={busy} beforeUpload={async selected => {
    const name = selected.name.toLowerCase();
    const csv = name.endsWith('.csv');
    if ((!csv && !name.endsWith('.xlsx')) || selected.size > 10 * 1024 * 1024) {
      message.error('请选择 10MB 以内的退款订单 CSV 或 XLSX 文件');
      return Upload.LIST_IGNORE;
    }
    setBusy(true);
    try {
      const result = await uploadFile<RefundResult>('/api/bonus-refunds', selected,
        csv ? 'text/csv' : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
      window.dispatchEvent(new Event('bonus-rules-changed'));
      modal.info({
        title: '退款订单匹配结果',
        content: '共 ' + result.orders + ' 个订单号，命中 ' + result.matched + ' 个（销售 ' +
          result.sales + ' 行，市场 ' + result.market + ' 行），新增退款标记 ' + result.added + ' 个。',
      });
    } catch (e) { message.error((e as Error).message); }
    finally { setBusy(false); }
    return Upload.LIST_IGNORE;
  }}><Button icon={<UploadOutlined />} loading={busy}>导入退款订单</Button></Upload>;
}


export function BonusImportWorkspace({ canImportRefunds }: { canImportRefunds: boolean }) {
  return <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
    <Card title="奖金发放状态回传">
      <BonusImport />
      <p className="subtext">在首页导出统一奖金明细，修改发放状态，再上传最后一次导出的 XLSX。</p>
    </Card>
    {canImportRefunds && <Card title="退款订单导入">
      <RefundImportButton />
      <p className="subtext">上传含「订单号」列的 CSV 或 XLSX，同时匹配销售和市场记录。</p>
    </Card>}
  </Space>;
}
