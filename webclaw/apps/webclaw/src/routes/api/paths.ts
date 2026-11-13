import os from 'node:os'
import path from 'node:path'
import { createFileRoute } from '@tanstack/react-router'
import { json } from '@tanstack/react-start'
import {
  getAutoplanBaseUrl,
  isOpenClawGatewayConfigured,
} from '../../server/autoplan'

function resolveSessionsDir() {
  if (!isOpenClawGatewayConfigured()) {
    const stateDir = path.resolve(process.cwd(), '../../.planai-queue')
    return {
      agentId: 'chief-of-staff',
      stateDir,
      sessionsDir: stateDir,
      storePath: path.join(stateDir, 'queue.db'),
      backendUrl: getAutoplanBaseUrl(),
    }
  }
  const agentId = (process.env.CLAWDBOT_AGENT_ID || 'main').trim() || 'main'
  const stateDir = (
    process.env.CLAWDBOT_STATE_DIR || path.join(os.homedir(), '.clawdbot')
  ).trim()
  return {
    agentId,
    stateDir,
    sessionsDir: path.join(stateDir, 'agents', agentId, 'sessions'),
    storePath: path.join(
      stateDir,
      'agents',
      agentId,
      'sessions',
      'sessions.json',
    ),
  }
}

export const Route = createFileRoute('/api/paths')({
  server: {
    handlers: {
      GET: () => {
        return json(resolveSessionsDir())
      },
    },
  },
})
