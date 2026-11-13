import { useEffect, useState } from 'react';
import { Alert, App, Button, Empty, Modal, Space, Table, Tag } from 'antd';
import { DatabaseOutlined } from '@ant-design/icons';
import { api } from './api';
import SalesSourceEditor from './SalesSourceEditor';
import type { EditorKind } from './SalesSourceEditor';
export { SalesHeaderConfiguration } from './SalesFixedHeader';
export type SalesContext = { owner:string; quarter:string; record_key:string };
type Source = { kind:string; title:string; sheet:string; columns:string[]; rows:Record<string,unknown>[]; note:string; active?:boolean };
const sources = [ ['splits','拆分订单表'], ['targets','奖金汇总表'], ['services','奖金方案'], ['orders','C 订单号'], ['segmentation','Z 是否适用分段计算'], ['constants','公共常数'] ];

export function SalesSourceEntries({onlyServices=false}:{onlyServices?:boolean}) {
  const {modal}=App.useApp();
  const [dirty,setDirty]=useState(false),[editorBusy,setEditorBusy]=useState(false);
  const [kind, setKind] = useState('');
  const [data, setData] = useState<Source>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!kind || ['targets','services','constants'].includes(kind)) { setData(undefined); setError(''); setLoading(false); return; }
    let active = true; setLoading(true); setData(undefined); setError('');
    api<Source>('/sales-workspace/sources/' + kind).then(result => { if (active) setData(result); }).catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [kind]);
  const editor=['targets','services','constants'].includes(kind);
  const close=()=>{if(editorBusy)return; if(dirty)modal.confirm({title:'放弃尚未保存的修改？',okText:'放弃并关闭',cancelText:'继续编辑',onOk:()=>{setDirty(false);setKind('');}});else setKind('');};
  return <>
    <Space size={4} wrap className="sales-source-entries">{sources.filter(([key])=>!onlyServices||key==='services').map(([key, title]) => <Button key={key} size="small" icon={<DatabaseOutlined />} onClick={() => {setDirty(false);setKind(key);}}>{title}</Button>)}</Space>
    <Modal title={editor?sources.find(x=>x[0]===kind)?.[1]:data?.title || sources.find(x => x[0] === kind)?.[1]} open={!!kind} onCancel={close} closable={!editorBusy} maskClosable={!editorBusy} keyboard={!editorBusy} footer={<Space>{!editor&&<Tag>原表样例 · 只读预览</Tag>}<Button disabled={editorBusy} onClick={close}>关闭</Button></Space>} width="80vw" style={{ top: '10vh', paddingBottom: 0 }} classNames={{ wrapper: 'sales-source-modal-wrap', container: 'sales-source-modal', mask: 'sales-source-mask' }}>
      {editor?<SalesSourceEditor key={kind} kind={kind as EditorKind} onDirtyChange={setDirty} onBusyChange={setEditorBusy}/>:<>
      <p className="subtext">{data?.note || '正在读取原表样例…'}</p>
      {data && <p>来源：{data.sheet} <Tag>{data.rows.length} 条{data.active ? "生效配置" : "样例"}</Tag></p>}
      {kind === 'constants' && <Alert type="info" title="紫色齿轮设置全局公共参数，保存后适用于全部BD和全部季度。" />}
      {error && <Alert type="error" title={error} />}
      <Table size="small" bordered loading={loading} rowKey={(_, i) => String(i)} columns={(data?.columns || []).map(name => ({ title: name, dataIndex: name, render: (v: unknown) => v == null || v === '' ? <span className="subtext">空白（未指定）</span> : String(v) }))} dataSource={data?.rows || []} scroll={{ x: 'max-content' }} pagination={{ pageSize: 10, showSizeChanger: false }} locale={{ emptyText: <Empty description="暂无可见原表样例" /> }} />
      </>}
    </Modal>
  </>;
}
