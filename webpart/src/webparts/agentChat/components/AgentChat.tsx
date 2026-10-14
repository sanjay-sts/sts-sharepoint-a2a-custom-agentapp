import * as React from 'react';
import { Stack } from '@fluentui/react/lib/Stack';
import { Text } from '@fluentui/react/lib/Text';
import styles from './AgentChat.module.scss';
import type { IAgentChatProps } from './IAgentChatProps';
import { MessageList, IChatMessage } from './MessageList';
import { ChatInput } from './ChatInput';
import { streamAnswer, ChatError } from '../a2aClient';

let counter = 0;
const nextId = (): string => `m${++counter}`;

const AgentChat: React.FunctionComponent<IAgentChatProps> = ({ agentUrl, getToken, userDisplayName }) => {
  const [messages, setMessages] = React.useState<IChatMessage[]>([]);
  const [busy, setBusy] = React.useState(false);
  const abortRef = React.useRef<AbortController | null>(null);

  React.useEffect(() => () => abortRef.current?.abort(), []);

  const patch = (id: string, change: Partial<IChatMessage>): void =>
    setMessages(ms => ms.map(m => (m.id === id ? { ...m, ...change } : m)));

  const ask = async (question: string): Promise<void> => {
    const agentId = nextId();
    setMessages(ms => [...ms,
      { id: nextId(), role: 'user', text: question },
      { id: agentId, role: 'agent', text: '', status: 'Working...' }
    ]);
    setBusy(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      let token: string;
      try {
        token = await getToken();
      } catch (e) {
        throw new ChatError('unauthorized', `Could not get a token: ${(e as Error).message || e}`);
      }
      await streamAnswer(agentUrl, token, question, {
        onText: text => patch(agentId, { text, status: undefined }),
        onStatus: status => patch(agentId, { status })
      }, controller.signal);
      patch(agentId, { status: undefined });
    } catch (e) {
      const err = e instanceof ChatError ? e : new ChatError('agent_failed', String(e));
      console.error('AgentChat', err.kind, err.message);
      patch(agentId, { status: undefined, error: { kind: err.kind, detail: err.message } });
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  };

  return (
    <section className={styles.agentChat}>
      <Stack tokens={{ childrenGap: 12 }}>
        <Text variant="large">SharePoint discovery agent</Text>
        <Text variant="small">Signed in as {userDisplayName}. Answers only cover files you can open.</Text>
        <MessageList messages={messages} />
        <ChatInput disabled={busy} onSend={q => { ask(q).catch(() => undefined); }} />
      </Stack>
    </section>
  );
};

export default AgentChat;
