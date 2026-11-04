import { useState } from 'react';
import { Alert, App, Form, Input, Modal } from 'antd';
import { api } from './api';

export default function ChangePasswordModal({ open, onClose, onChanged }: { open: boolean; onClose: () => void; onChanged: () => void }) {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const { message } = App.useApp();
  return <Modal title="修改密码" open={open} onCancel={() => { form.resetFields(); onClose(); }} okText="保存新密码" confirmLoading={saving} maskClosable={!saving} closable={!saving} cancelButtonProps={{ disabled: saving }} onOk={async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      const result = await api('/me/password', { method: 'PUT', body: JSON.stringify(values) });
      form.resetFields(); onClose(); onChanged(); message.success(result.message);
    } catch (e) { if (e instanceof Error) message.error(e.message); } finally { setSaving(false); }
  }}>
    <Alert type="info" showIcon title="修改成功后，所有设备需重新登录" description="请先验证当前密码，新密码至少8位。" />
    <Form form={form} layout="vertical">
      <Form.Item label="当前密码" name="current_password" rules={[{ required: true, message: '请输入当前密码' }]}><Input.Password autoComplete="current-password" maxLength={256} /></Form.Item>
      <Form.Item label="新密码" name="new_password" rules={[{ required: true, message: '请输入新密码' }, { min: 8, message: '新密码至少8位' }, { max: 128, message: '新密码最多128位' }]}><Input.Password autoComplete="new-password" maxLength={128} /></Form.Item>
      <Form.Item label="确认新密码" name="confirm_password" dependencies={['new_password']} rules={[{ required: true, message: '请再次输入新密码' }, ({ getFieldValue }) => ({ validator(_, value) { return !value || value === getFieldValue('new_password') ? Promise.resolve() : Promise.reject(new Error('两次新密码输入不一致')); } })]}><Input.Password autoComplete="new-password" maxLength={128} /></Form.Item>
    </Form>
  </Modal>;
}
