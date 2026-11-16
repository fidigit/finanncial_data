import { useEffect, useState } from 'react';
import { Alert, Button, Input, Space, Table, Tag } from 'antd';
import { api } from './api';

type OrderData={columns:string[]; rows:Record<string,string|number>[]; total:number; sheet:string};

export default function OrderSourceTable(){
  const [data,setData]=useState<OrderData>(),[page,setPage]=useState(1),[size,setSize]=useState(20);
  const [search,setSearch]=useState(''),[revision,setRevision]=useState(0),[loading,setLoading]=useState(false),[error,setError]=useState('');
  useEffect(()=>{
    let active=true;setLoading(true);setError('');setData(undefined);
    api<OrderData>(`/sales-workspace/sources/orders?page=${page}&page_size=${size}&search=${encodeURIComponent(search)}`)
      .then(next=>{if(active)setData(next);}).catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[page,size,search,revision]);
  return <div aria-label="后台订单数据">
    <Space wrap style={{marginBottom:16}}>
      <Input.Search aria-label="搜索后台订单" placeholder="订单号、BD或所购服务" allowClear onSearch={value=>{setSearch(value);setPage(1);}} style={{width:300}}/>
      <Button onClick={()=>setRevision(v=>v+1)} loading={loading}>重新读取</Button>
      {data&&<Tag>共 {data.total} 条 · {data.sheet}</Tag>}
    </Space>
    {error&&<Alert type="error" title={error}/>}
    <Table size="small" bordered loading={loading} rowKey="row_id" dataSource={data?.rows||[]}
      columns={(data?.columns||[]).map(name=>({title:name,dataIndex:name,align:'center' as const,render:(v:unknown)=>v==null||v===''?'—':String(v)}))}
      scroll={{x:'max-content'}} pagination={{current:page,pageSize:size,total:data?.total||0,showSizeChanger:true,pageSizeOptions:[20,50,100,200],onChange:(next,nextSize)=>{setPage(nextSize===size?next:1);setSize(nextSize);}}}/>
  </div>;
}
