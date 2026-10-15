import * as React from 'react';
import * as ReactDom from 'react-dom';
import { Version } from '@microsoft/sp-core-library';
import {
  type IPropertyPaneConfiguration,
  PropertyPaneTextField
} from '@microsoft/sp-property-pane';
import { BaseClientSideWebPart } from '@microsoft/sp-webpart-base';

import * as strings from 'AgentChatWebPartStrings';
import AgentChat from './components/AgentChat';
import { IAgentChatProps } from './components/IAgentChatProps';

export interface IAgentChatWebPartProps {
  /** Base URL of the A2A server, e.g. http://127.0.0.1:8002 */
  agentUrl: string;
  /** Resource the token is requested for: the API's Application ID URI (api://<client-id>). */
  apiResource: string;
}

const DEFAULT_AGENT_URL = 'http://127.0.0.1:8002';
const DEFAULT_API_RESOURCE = 'api://1162088a-3e99-4dad-b52e-d1f2ce5f1c72';

export default class AgentChatWebPart extends BaseClientSideWebPart<IAgentChatWebPartProps> {

  private get _agentUrl(): string {
    return (this.properties.agentUrl || DEFAULT_AGENT_URL).trim();
  }

  private get _apiResource(): string {
    return (this.properties.apiResource || DEFAULT_API_RESOURCE).trim();
  }

  public render(): void {
    const element: React.ReactElement<IAgentChatProps> = React.createElement(
      AgentChat,
      {
        agentUrl: this._agentUrl,
        getToken: () => this._getToken(),
        userDisplayName: this.context.pageContext.user.displayName
      }
    );
    ReactDom.render(element, this.domElement);
  }

  /** Delegated token for the agent API via SharePoint's AadTokenProvider. */
  private async _getToken(): Promise<string> {
    const provider = await this.context.aadTokenProviderFactory.getTokenProvider();
    return provider.getToken(this._apiResource);
  }

  protected onDispose(): void {
    ReactDom.unmountComponentAtNode(this.domElement);
  }

  protected get dataVersion(): Version {
    return Version.parse('1.0');
  }

  protected getPropertyPaneConfiguration(): IPropertyPaneConfiguration {
    return {
      pages: [
        {
          header: { description: strings.PropertyPaneDescription },
          groups: [
            {
              groupName: strings.BasicGroupName,
              groupFields: [
                PropertyPaneTextField('agentUrl', { label: strings.AgentUrlFieldLabel }),
                PropertyPaneTextField('apiResource', { label: strings.ApiResourceFieldLabel })
              ]
            }
          ]
        }
      ]
    };
  }
}
