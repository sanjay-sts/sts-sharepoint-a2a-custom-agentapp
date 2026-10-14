/**
 * Minimal browser client for the A2A server (a2a-sdk 1.x JSON-RPC binding).
 *
 * Plain fetch + hand-rolled SSE parsing: the server's wire format was verified
 * directly (method "SendStreamingMessage", proto-JSON params, mandatory
 * A2A-Version header), and this avoids pulling an SDK into the SPFx bundle.
 */

export type ChatErrorKind = 'unauthorized' | 'network' | 'aws_credentials' | 'agent_failed' | 'rpc';

export class ChatError extends Error {
  public constructor(public readonly kind: ChatErrorKind, message: string) {
    super(message);
    this.name = 'ChatError';
  }
}

export interface StreamHandlers {
  /** Full answer text so far (chunks are concatenated here). */
  onText(text: string): void;
  /** Progress line such as "Calling list_sites...". */
  onStatus(status: string): void;
}

interface Part { text?: string; mediaType?: string }
interface StatusUpdate { status?: { state?: string; message?: { parts?: Part[] } } }
interface ArtifactUpdate { artifact?: { artifactId?: string; parts?: Part[] }; append?: boolean; lastChunk?: boolean }
interface RpcEnvelope {
  result?: { task?: unknown; statusUpdate?: StatusUpdate; artifactUpdate?: ArtifactUpdate; message?: { parts?: Part[] } };
  error?: { code?: number; message?: string };
}

const AWS_PREFIX = 'ERROR_AWS_CREDENTIALS:';

function partsText(parts: Part[] | undefined): string {
  return (parts || []).map(p => p.text || '').join('');
}

function newId(): string {
  const c = (window as unknown as { crypto?: Crypto }).crypto;
  if (c && typeof c.randomUUID === 'function') { return c.randomUUID(); }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, ch => {
    const r = Math.floor(Math.random() * 16);
    return (ch === 'x' ? r : (r % 4) + 8).toString(16);
  });
}

/**
 * Sends one question and streams the answer. Resolves when the task completes;
 * rejects with ChatError on any failure.
 */
export async function streamAnswer(
  agentUrl: string,
  token: string,
  question: string,
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const body = {
    jsonrpc: '2.0',
    id: newId(),
    method: 'SendStreamingMessage',
    params: { message: { role: 'ROLE_USER', messageId: newId(), parts: [{ text: question }] } }
  };

  let response: Response;
  try {
    response = await fetch(agentUrl.replace(/\/+$/, '') + '/', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
        'A2A-Version': '1.0'
      },
      body: JSON.stringify(body),
      signal
    });
  } catch (e) {
    throw new ChatError('network', `Cannot reach the agent at ${agentUrl}. ${(e as Error).message || ''}`.trim());
  }

  if (response.status === 401) {
    throw new ChatError('unauthorized', 'The agent rejected the sign-in token (401).');
  }
  const contentType = response.headers.get('content-type') || '';
  if (!response.ok || contentType.indexOf('text/event-stream') < 0) {
    let detail = `HTTP ${response.status}`;
    try {
      const j = (await response.json()) as RpcEnvelope;
      if (j.error) { detail = `${j.error.code}: ${j.error.message}`; }
    } catch { /* not JSON */ }
    throw new ChatError('rpc', detail);
  }
  if (!response.body) {
    throw new ChatError('network', 'The browser did not expose a readable response body.');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let answer = '';
  let completed = false;

  const handleEvent = (data: string): void => {
    let ev: RpcEnvelope;
    try { ev = JSON.parse(data) as RpcEnvelope; } catch { return; }
    if (ev.error) {
      throw new ChatError('rpc', `${ev.error.code}: ${ev.error.message}`);
    }
    const res = ev.result || {};
    if (res.artifactUpdate) {
      const a = res.artifactUpdate;
      if (!a.artifact || a.artifact.artifactId !== 'answer') { return; }
      const chunk = partsText(a.artifact.parts);
      answer = a.append ? answer + chunk : chunk;
      handlers.onText(answer);
    } else if (res.statusUpdate) {
      const st = res.statusUpdate.status || {};
      const text = partsText(st.message && st.message.parts);
      if (st.state === 'TASK_STATE_FAILED') {
        if (text.indexOf(AWS_PREFIX) === 0) {
          throw new ChatError('aws_credentials', text.substring(AWS_PREFIX.length).trim());
        }
        throw new ChatError('agent_failed', text || 'The agent failed without a message.');
      }
      if (st.state === 'TASK_STATE_COMPLETED') { completed = true; }
      else if (text) { handlers.onStatus(text); }
    } else if (res.message) {
      answer += partsText(res.message.parts);
      handlers.onText(answer);
    }
  };

  // SSE: events are separated by a blank line; each may carry several "data:" lines.
  let dataLines: string[] = [];
  const flush = (): void => {
    if (dataLines.length) { handleEvent(dataLines.join('\n')); dataLines = []; }
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) { break; }
    buffer += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buffer.indexOf('\n')) >= 0) {
      const line = buffer.substring(0, nl).replace(/\r$/, '');
      buffer = buffer.substring(nl + 1);
      if (line === '') { flush(); }
      else if (line.indexOf('data:') === 0) { dataLines.push(line.substring(5).replace(/^ /, '')); }
      // "event:", "id:", ":" comments are ignored
    }
  }
  flush();
  if (!completed) {
    throw new ChatError('network', 'The stream ended before the agent finished.');
  }
}
