import * as React from 'react';
import { Stack } from '@fluentui/react/lib/Stack';
import { Text } from '@fluentui/react/lib/Text';
import { Spinner, SpinnerSize } from '@fluentui/react/lib/Spinner';
import { MessageBar, MessageBarType } from '@fluentui/react/lib/MessageBar';
import { AnswerText } from './AnswerText';
import { ChatErrorKind } from '../a2aClient';
import styles from './AgentChat.module.scss';

export interface IChatMessage {
  id: string;
  role: 'user' | 'agent';
  text: string;
  status?: string;
  error?: { kind: ChatErrorKind; detail: string };
}

const ERROR_TEXT: Record<ChatErrorKind, string> = {
  unauthorized: 'Sign-in to the agent failed. The API permission (sp-agent-poc / access_as_user) may not be approved yet.',
  network: 'Cannot reach the agent. Is the A2A server running, and did the browser allow access to the local network?',
  aws_credentials: 'The agent\'s AWS credentials have expired. Refresh them (aws sso login) and try again.',
  agent_failed: 'The agent failed while answering.',
  rpc: 'The agent returned a protocol error.'
};

export interface IMessageListProps { messages: IChatMessage[] }

export const MessageList: React.FunctionComponent<IMessageListProps> = ({ messages }) => {
  const endRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => { endRef.current?.scrollIntoView({ block: 'nearest' }); }, [messages]);
  return (
    <Stack tokens={{ childrenGap: 10 }} className={styles.messages}>
      {messages.map(m => (
        <div key={m.id} className={m.role === 'user' ? styles.user : styles.agent}>
          {m.role === 'user'
            ? <Text block>{m.text}</Text>
            : <AnswerText text={m.text} />}
          {m.status && (
            <Stack horizontal tokens={{ childrenGap: 8 }} verticalAlign="center">
              <Spinner size={SpinnerSize.xSmall} />
              <Text variant="small">{m.status}</Text>
            </Stack>
          )}
          {m.error && (
            <MessageBar messageBarType={MessageBarType.error} isMultiline>
              {ERROR_TEXT[m.error.kind]} {m.error.detail}
            </MessageBar>
          )}
        </div>
      ))}
      <div ref={endRef} />
    </Stack>
  );
};
