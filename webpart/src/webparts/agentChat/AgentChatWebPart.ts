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

export default class AgentChatWebPart extends BaseClientSideWebPart<IAgentChatWebPartProps> {

  public render(): void {
    const element: React.ReactElement<IAgentChatProps> = React.createElement(
      AgentChat,
      {
        agentUrl: this.properties.agentUrl,
        getToken: () => this._getToken(),
        userDisplayName: this.context.pageContext.user.displayName
      }
    );
    ReactDom.render(element, this.domElement);
  }

  /** Delegated token for the agent API via SharePoint's AadTokenProvider. */
  private async _getToken(): Promise<string> {
    const provider = await this.context.aadTokenProviderFactory.getTokenProvider();
    return provider.getToken(this.properties.apiResource);
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
