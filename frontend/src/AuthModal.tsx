import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { Alert, Button, Form, Input, Modal } from 'antd';
import { useState } from 'react';


import type { AuthSession } from './types';

interface AuthModalProps {
  open: boolean;
  onCancel: () => void;
  onSuccess: (session: AuthSession) => void;
}

interface AuthFormValues {
  username: string;
  password: string;
  email?: string;
}

export function AuthModal({
  open,
  onCancel,
  onSuccess,
}: AuthModalProps) {
  const [registering, setRegistering] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(values: AuthFormValues) {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/v1/auth/${registering ? 'register' : 'login'}`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.message ?? '请检查输入后重试');
      onSuccess(data as AuthSession);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '登录失败');
    } finally { setBusy(false); }
  }

  return (
    <Modal
      open={open}
      title={null}
      footer={null}
      width={420}
      onCancel={onCancel}
      destroyOnHidden
      centered
    >
      <div className="auth-modal__header">
        <h2>欢迎来到安心保</h2>
        <p>登录后可使用智能顾问服务</p>
      </div>
      <Form<AuthFormValues>
        layout="vertical"
        initialValues={{ username: '', password: '' }}
        onFinish={submit}
        requiredMark={false}
      >
        <Form.Item
          label="用户名"
          name="username"
          rules={[{ required: true, message: '请输入用户名' }]}
        >
          <Input prefix={<UserOutlined />} size="large" />
        </Form.Item>
        <Form.Item
          label="密码"
          name="password"
          rules={[{ required: true, min: 6, message: '密码至少需要 6 位' }]}
        >
          <Input.Password prefix={<LockOutlined />} size="large" />
        </Form.Item>
        {registering ? <Form.Item name="email" label="邮箱" rules={[{ required: true, type: 'email' }]}><Input /></Form.Item> : null}
        {error ? <Alert type="error" message={error} /> : null}
        <Button className="auth-submit" htmlType="submit" loading={busy}>{registering ? '注册并登录' : '登录'}</Button>
        <Button type="link" onClick={() => { setRegistering(!registering); setError(null); }}>{registering ? '已有账号，去登录' : '注册新账号'}</Button>
      </Form>
    </Modal>
  );
}
