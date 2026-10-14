import * as React from 'react';
import { Stack } from '@fluentui/react/lib/Stack';
import { TextField } from '@fluentui/react/lib/TextField';
import { PrimaryButton } from '@fluentui/react/lib/Button';

export interface IChatInputProps {
  disabled: boolean;
  onSend(question: string): void;
}

export const ChatInput: React.FunctionComponent<IChatInputProps> = ({ disabled, onSend }) => {
  const [value, setValue] = React.useState('');
  const send = (): void => {
    const q = value.trim();
    if (!q || disabled) { return; }
    onSend(q);
    setValue('');
  };
  return (
    <Stack horizontal tokens={{ childrenGap: 8 }} verticalAlign="end">
      <Stack.Item grow>
        <TextField
          placeholder="Ask about files in your SharePoint sites"
          value={value}
          multiline autoAdjustHeight rows={1}
          disabled={disabled}
          onChange={(_, v) => setValue(v || '')}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
        />
      </Stack.Item>
      <PrimaryButton text="Send" onClick={send} disabled={disabled || !value.trim()} />
    </Stack>
  );
};
