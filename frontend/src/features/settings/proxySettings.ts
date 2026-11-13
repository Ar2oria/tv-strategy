export type ProxyProtocol = "http" | "https" | "socks5" | "socks5h";

export interface ProxyParts {
  protocol: ProxyProtocol;
  host: string;
  port: number | null;
}

const PROTOCOLS = new Set<ProxyProtocol>(["http", "https", "socks5", "socks5h"]);

function emptyParts(): ProxyParts {
  return { protocol: "http", host: "", port: null };
}

export function parseProxyUrl(value: string | null): ProxyParts {
  if (value === null) {
    return emptyParts();
  }
  try {
    const parsed = new URL(value);
    const protocol = parsed.protocol.slice(0, -1) as ProxyProtocol;
    if (!PROTOCOLS.has(protocol)) {
      return { ...emptyParts(), host: value };
    }
    const explicitPort = /:(\d+)(?:[/?#]|$)/.exec(value);
    return {
      protocol,
      host: parsed.hostname,
      port:
        parsed.port === "" && explicitPort !== null
          ? Number(explicitPort[1])
          : parsed.port === ""
            ? null
            : Number(parsed.port),
    };
  } catch {
    return { ...emptyParts(), host: value };
  }
}

export function composeProxyUrl(parts: ProxyParts): string | null {
  const host = parts.host.trim();
  if (host === "" && parts.port === null) {
    return null;
  }
  const port = parts.port === null ? "" : `:${parts.port}`;
  return `${parts.protocol}://${host}${port}`;
}
