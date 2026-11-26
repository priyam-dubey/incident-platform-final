import type { Onboarding } from "./types";

export function snippet(o: Onboarding, key: string, name: string, env = "production") {
  return `# 1. install
npm install @incident-platform/node

# 2. environment (never commit the key)
INCIDENT_PLATFORM_ENDPOINT=${o.env.INCIDENT_PLATFORM_ENDPOINT}
INCIDENT_PLATFORM_KEY=${key}
INCIDENT_PLATFORM_APP=${name}
INCIDENT_PLATFORM_ENV=${env}
INCIDENT_PLATFORM_RELEASE=1.0.0         # optional
INCIDENT_PLATFORM_COMMIT=$GIT_SHA       # optional: enables deployment correlation

// 3. first lines of your server entry, before express / mongodb:
const incident = require("@incident-platform/node");
incident.init();`;
}
