import { HttpClient } from './http-client';
import type { ACPDiscovery, ACPDiscoveryRequest } from '../models/acp-discovery';

export interface ACPClientOptions {
  host: string;
  apiKey?: string;
  timeout?: number;
}

export class ACPClient {
  public readonly host: string;
  public readonly apiKey?: string;
  private readonly client: HttpClient;

  constructor(options: ACPClientOptions) {
    this.host = options.host.replace(/\/$/, '');
    this.apiKey = options.apiKey;
    this.client = new HttpClient({
      baseUrl: this.host,
      apiKey: this.apiKey,
      timeout: options.timeout || 180000,
    });
  }

  /** Start the ACP server in a throwaway session and report its models and slash commands. */
  async discover(request: ACPDiscoveryRequest): Promise<ACPDiscovery> {
    const response = await this.client.post<ACPDiscovery>('/api/acp/discover', request);
    return response.data;
  }

  /** @deprecated Use `discover`. */
  async discoverModels(request: ACPDiscoveryRequest): Promise<ACPDiscovery> {
    return this.discover(request);
  }

  close(): void {
    this.client.close();
  }
}
