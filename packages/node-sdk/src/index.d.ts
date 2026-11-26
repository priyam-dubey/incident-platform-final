export interface InitOptions {
  endpoint?: string;        // INCIDENT_PLATFORM_ENDPOINT, e.g. https://ingest.example.com
  key?: string;             // INCIDENT_PLATFORM_KEY (ipk_...)
  serviceName?: string;     // INCIDENT_PLATFORM_APP
  environment?: string;     // INCIDENT_PLATFORM_ENV (development | staging | production)
  release?: string;         // INCIDENT_PLATFORM_RELEASE, e.g. 1.4.2
  commitSha?: string;       // INCIDENT_PLATFORM_COMMIT, git SHA of the running build
  metricIntervalMs?: number;
  captureConsole?: boolean; // forward console.warn/error as logs
  extraSensitiveKeys?: string[];
  debug?: boolean;
}
export function init(options?: InitOptions): { started: boolean; problems: string[] };
export function shutdown(): Promise<void>;
export function captureException(err: unknown, attributes?: Record<string, string | number | boolean>): void;
export function expressErrorHandler(): (err: any, req: any, res: any, next: (e?: any) => void) => void;
export const logger: {
  debug(message: string, attributes?: Record<string, unknown>): void;
  info(message: string, attributes?: Record<string, unknown>): void;
  warn(message: string, attributes?: Record<string, unknown>): void;
  error(message: string, attributes?: Record<string, unknown>): void;
};
export interface DeploymentOptions {
  key?: string;            // defaults to INCIDENT_PLATFORM_KEY
  apiUrl?: string;         // defaults to INCIDENT_PLATFORM_API_URL, then the ingestion endpoint
  version?: string;        // defaults to INCIDENT_PLATFORM_RELEASE
  commitSha?: string;      // defaults to INCIDENT_PLATFORM_COMMIT
  branch?: string;
  repository?: string;     // owner/name
  deployedBy?: string;
  deployedAt?: string | Date;
  environment?: string;
  metadata?: Record<string, unknown>;
  timeoutMs?: number;
}
/** Never throws. Deployments are shown as possible causes, never as proof. */
export function registerDeployment(options?: DeploymentOptions): Promise<{ ok: boolean; status?: number; id?: string; error?: string }>;
