import { DownOutlined, UpOutlined } from '@ant-design/icons';
import { Button } from 'antd';

type Props = {
  title: string;
  contentId: string;
  expanded: boolean;
  onToggle: () => void;
};

export default function DataCardToggle({ title, contentId, expanded, onToggle }: Props) {
  const action = expanded ? '收起' : '展开';
  return <Button size="small" icon={expanded ? <UpOutlined /> : <DownOutlined />}
    aria-label={action + title} aria-expanded={expanded} aria-controls={contentId} onClick={onToggle}>
    {action}
  </Button>;
}
