import { useState } from 'react';
import { Alert, App, Button, Card, Descriptions, Modal, Select, Space, Table, Upload } from 'antd';
import { UploadOutlined } from '@ant-design/icons';

type Kind='sales'|'market';
type Change={owner:string;quarter:string;order_no:string;before:{is_paid:boolean|null;is_refunded:boolean|null};after:{is_paid:boolean|null;is_refunded:boolean|null}};
type Preview={suffix:string;filename:string;total:number;changed_count:number;rows:Change[]};
const show=(value:boolean|null)=>value==null?'待确认':value?'是':'否';
async function send(kind:Kind,file:File,preview:boolean){
  const response=await fetch(`/api/bonus-import/${kind}${preview?'/preview':''}?`+new URLSearchParams({filename:file.name}),{
    method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','X-Requested-With':'BD-Workbench'},body:file,
  });
  const result=await response.json().catch(()=>({}));
  if(!response.ok)throw Error(result.detail||'导入失败，请检查文件版本和内容');
  return result as Preview;
}
export default function BonusImport({kind,onSaved}:{kind:Kind;onSaved?:()=>void}){
  const {message}=App.useApp();
  const [busy,setBusy]=useState(false),[file,setFile]=useState<File>(),[preview,setPreview]=useState<Preview>(),[error,setError]=useState('');
  return <>
    <Upload accept=".xlsx" showUploadList={false} disabled={busy} beforeUpload={async selected=>{
      if(!selected.name.toLowerCase().endsWith('.xlsx')||selected.size>10*1024*1024){message.error('请选择10MB以内的系统导出XLSX文件');return Upload.LIST_IGNORE;}
      setBusy(true);setError('');
      try{const result=await send(kind,selected,true);setFile(selected);setPreview(result);}catch(e){message.error((e as Error).message);}finally{setBusy(false);}
      return Upload.LIST_IGNORE;
    }}><Button aria-label={`导入${kind==='sales'?'销售':'市场'}奖金XLSX`} icon={<UploadOutlined/>} loading={busy}>导入 XLSX</Button></Upload>
    <Modal title="奖金状态导入预览" width={820} open={!!preview} closable={!busy} maskClosable={!busy} confirmLoading={busy} okText="确认导入" onCancel={()=>{if(!busy){setPreview(undefined);setFile(undefined);setError('');}}} onOk={async()=>{
      if(!file)return;setBusy(true);setError('');
      try{const result=await send(kind,file,false);message.success(`导入成功，已更新${result.changed_count}条记录`);setPreview(undefined);setFile(undefined);window.dispatchEvent(new Event('bonus-rules-changed'));onSaved?.();}catch(e){setError((e as Error).message);}finally{setBusy(false);}
    }}>
      <Alert type="info" showIcon title="仅回写是否发放、是否退款" description="文件必须来自当前账号最后一次导出；A–P及S列不得修改。确认导入时会再次校验，整批成功后才保存。"/>
      {error&&<Alert style={{marginTop:12}} type="error" showIcon title={error}/>}
      <Descriptions style={{marginTop:16,marginBottom:16}} column={2} items={[
        {key:'file',label:'文件',children:preview?.filename,span:2},{key:'version',label:'导出版本',children:preview?.suffix},
        {key:'count',label:'记录',children:`共${preview?.total||0}条，${preview?.changed_count||0}条将变更`},
      ]}/>
      <Table<Change> size="small" rowKey={(_,i)=>String(i)} pagination={false} dataSource={preview?.rows||[]} scroll={{y:330}} locale={{emptyText:'没有状态变化，确认后此版本会标记为已导入'}} columns={[
        {title:'BD姓名',dataIndex:'owner'},{title:'季度',dataIndex:'quarter'},{title:'订单号',dataIndex:'order_no'},
        {title:'是否发放',render:(_,r)=>`${show(r.before.is_paid)} → ${show(r.after.is_paid)}`},
        {title:'是否退款',render:(_,r)=>`${show(r.before.is_refunded)} → ${show(r.after.is_refunded)}`},
      ]}/>
      {(preview?.changed_count||0)>50&&<p className="subtext">仅预览前50条变更，确认后提交全部{preview?.changed_count}条。</p>}
    </Modal>
  </>;
}
export function BonusImportWorkspace(){
  const [kind,setKind]=useState<Kind>('sales');
  return <Card title="销售／市场奖金状态回传"><Space wrap style={{marginBottom:18}}><Select aria-label="导入奖金表类型" value={kind} onChange={setKind} style={{width:170}} options={[{value:'sales',label:'销售奖金表'},{value:'market',label:'市场奖金表'}]}/><BonusImport key={kind} kind={kind}/></Space><Alert showIcon type="info" title="先在首页导出，修改状态后回传" description="只接受当前账号最近一次导出的销售或市场奖金XLSX。文件名和文件内版本必须一致，只能将是否发放、是否退款修改为是、否、待确认；其他列保持原样。会议奖金表不参与此流程。"/></Card>;
}
