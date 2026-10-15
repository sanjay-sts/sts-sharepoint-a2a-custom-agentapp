export interface IAgentChatProps {
  agentUrl: string;
  /** Returns a fresh bearer token for the agent's API (api://<client-id>). */
  getToken: () => Promise<string>;
  userDisplayName: string;
}
