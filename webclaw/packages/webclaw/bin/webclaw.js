#!/usr/bin/env node

import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import readline from 'node:readline/promises'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const LOCAL_TEMPLATE_ROOT = path.resolve(__dirname, '..', '..', '..')
const REPO_URL = 'https://github.com/ibelick/webclaw'

function printBanner() {
  process.stdout.write(`              ▄▄          ▄▄               \n`)
  process.stdout.write(`              ██          ██               \n`)
  process.stdout.write(`██   ██ ▄█▀█▄ ████▄ ▄████ ██  ▀▀█▄ ██   ██ \n`)
  process.stdout.write(`██ █ ██ ██▄█▀ ██ ██ ██    ██ ▄█▀██ ██ █ ██ \n`)
  process.stdout.write(` ██▀██  ▀█▄▄▄ ████▀ ▀████ ██ ▀█▄██  ██▀██ \n\n`)
  process.stdout.write(`Fast web client for OpenClaw\n`)
  process.stdout.write(`https://webclaw.dev/\n\n`)
}

function printHelp() {
  process.stdout.write(`webclaw CLI\n\n`)
  process.stdout.write(`Usage:\n`)
  process.stdout.write(`  webclaw                 Create and start a new project\n`)
  process.stdout.write(`  webclaw init [dir]      Initialize a new project (legacy)\n`)
  process.stdout.write(`  webclaw dev             Run development server\n`)
  process.stdout.write(`  webclaw build           Build project\n`)
  process.stdout.write(`  webclaw preview         Preview production build\n`)
  process.stdout.write(`  webclaw test            Run tests\n`)
  process.stdout.write(`  webclaw lint            Run lint\n`)
  process.stdout.write(`  webclaw doctor          Validate local setup\n`)
  process.stdout.write(`\nOptions:\n`)
  process.stdout.write(`  --project-name <name>   Project directory name\n`)
  process.stdout.write(`  --gateway-url <url>     CLAWDBOT_GATEWAY_URL value\n`)
  process.stdout.write(`  --gateway-token <token> CLAWDBOT_GATEWAY_TOKEN value\n`)
  process.stdout.write(`  --gateway-password <pw> CLAWDBOT_GATEWAY_PASSWORD value\n`)
  process.stdout.write(`  --port <port>           Dev server port\n`)
  process.stdout.write(`  --yes                   Accept defaults (non-interactive)\n`)
  process.stdout.write(`  --no-start              Do not auto-run install + dev\n`)
  process.stdout.write(`  --force                 Allow init in non-empty directory\n`)
  process.stdout.write(`  --skip-env              Skip .env.local setup prompts\n`)
  process.stdout.write(`  -h, --help              Show help\n`)
}

function parseCliArgs(args) {
  const flags = new Set()
  const values = new Map()
  const positionals = []
  const optionsWithValues = new Set([
    '--project-name',
    '--gateway-url',
    '--gateway-token',
    '--gateway-password',
    '--port',
  ])

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index]
    if (!arg.startsWith('-')) {
      positionals.push(arg)
      continue
    }

    if (arg === '-h' || arg === '--help') {
      flags.add(arg)
      continue
    }

    if (!arg.startsWith('--')) {
      flags.add(arg)
      continue
    }

    const equalIndex = arg.indexOf('=')
    if (equalIndex !== -1) {
      const key = arg.slice(0, equalIndex)
      const value = arg.slice(equalIndex + 1)
      values.set(key, value)
      continue
    }

    const nextArg = args[index + 1]
    if (optionsWithValues.has(arg) && nextArg && !nextArg.startsWith('-')) {
      values.set(arg, nextArg)
      index += 1
      continue
    }

    flags.add(arg)
  }

  return { flags, values, positionals }
}

function runCommand(command, args, cwd) {
  const result = spawnSync(command, args, {
    cwd,
    stdio: 'inherit',
    env: process.env,
  })
  if (result.error) {
    throw result.error
  }
  if (typeof result.status === 'number' && result.status !== 0) {
    process.exit(result.status)
  }
}

function detectPackageManager(cwd) {
  if (fs.existsSync(path.join(cwd, 'pnpm-lock.yaml'))) return 'pnpm'
  if (fs.existsSync(path.join(cwd, 'yarn.lock'))) return 'yarn'
  return 'npm'
}

function detectProjectRoot(cwd) {
  const appDir = path.join(cwd, 'apps', 'webclaw')
  const appPackage = path.join(appDir, 'package.json')
  if (fs.existsSync(appPackage)) {
    return { mode: 'monorepo', appDir }
  }
  const packagePath = path.join(cwd, 'package.json')
  if (fs.existsSync(packagePath)) {
    return { mode: 'single', appDir: cwd }
  }
  return null
}

function runProjectScript(scriptName) {
  const detected = detectProjectRoot(process.cwd())
  if (!detected) {
    process.stderr.write(
      `No WebClaw project found in this directory. Run \`npx webclaw\` first.\n`,
    )
    process.exit(1)
  }

  const packageManager = detectPackageManager(process.cwd())

  if (detected.mode === 'monorepo') {
    if (packageManager === 'pnpm') {
      runCommand('pnpm', ['-C', 'apps/webclaw', scriptName], process.cwd())
      return
    }
    runCommand(packageManager, ['run', scriptName], detected.appDir)
    return
  }

  runCommand(packageManager, ['run', scriptName], detected.appDir)
}

function ensureDir(targetDir) {
  if (!fs.existsSync(targetDir)) {
    fs.mkdirSync(targetDir, { recursive: true })
  }
}

function copyDir(sourceDir, targetDir) {
  ensureDir(targetDir)
  const entries = fs.readdirSync(sourceDir, { withFileTypes: true })
  for (const entry of entries) {
    if (entry.name === 'node_modules') continue
    if (entry.name === '.git') continue
    if (entry.name === '.env.local') continue
    if (entry.name === '.openclaw') continue
    if (entry.name === '.webclaw') continue
    if (entry.name === '.tanstack') continue
    if (entry.name === '.DS_Store') continue
    const sourcePath = path.join(sourceDir, entry.name)
    const targetPath = path.join(targetDir, entry.name)
    if (entry.isDirectory()) {
      copyDir(sourcePath, targetPath)
    } else {
      fs.copyFileSync(sourcePath, targetPath)
    }
  }
}

function isDirEmpty(targetDir) {
  if (!fs.existsSync(targetDir)) return true
  const files = fs
    .readdirSync(targetDir)
    .filter((file) => file !== '.DS_Store' && file !== '.git')
  return files.length === 0
}

function cloneRepo(targetDir) {
  runCommand('git', ['clone', '--depth', '1', REPO_URL, targetDir], process.cwd())
}

function getLocalTemplateSource() {
  const rootPackage = path.join(LOCAL_TEMPLATE_ROOT, 'package.json')
  const appPackage = path.join(LOCAL_TEMPLATE_ROOT, 'apps', 'webclaw', 'package.json')
  if (!fs.existsSync(rootPackage) || !fs.existsSync(appPackage)) {
    return null
  }
  return LOCAL_TEMPLATE_ROOT
}

function populateTemplate(targetDir, isCurrentDir) {
  const localTemplateSource = getLocalTemplateSource()
  if (localTemplateSource) {
    if (!isCurrentDir) {
      copyDir(localTemplateSource, targetDir)
      return
    }

    copyDir(localTemplateSource, targetDir)
    return
  }

  if (!isCurrentDir) {
    cloneRepo(targetDir)
    return
  }

  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'webclaw-'))
  const tempCloneDir = path.join(tempRoot, 'repo')
  cloneRepo(tempCloneDir)
  copyDir(tempCloneDir, targetDir)
  fs.rmSync(tempRoot, { recursive: true, force: true })
}

function ensureGitRepository(targetDir) {
  if (fs.existsSync(path.join(targetDir, '.git'))) {
    return
  }

  const result = spawnSync('git', ['init'], {
    cwd: targetDir,
    stdio: 'ignore',
    env: process.env,
  })

  if (result.status === 0) {
    process.stdout.write('Initialized git repository\n')
  }
}

function resolveEnvFile(targetDir) {
  const monorepoEnv = path.join(targetDir, 'apps', 'webclaw', '.env.local')
  if (fs.existsSync(path.join(targetDir, 'apps', 'webclaw'))) {
    return monorepoEnv
  }
  return path.join(targetDir, '.env.local')
}

async function askQuestion(rl, question) {
  const answer = await rl.question(question)
  return answer.trim()
}

function parsePort(value, fallback) {
  const parsed = Number(value)
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535) {
    return fallback
  }
  return parsed
}

function setDevPort(targetDir, port) {
  const appPackagePath = fs.existsSync(path.join(targetDir, 'apps', 'webclaw'))
    ? path.join(targetDir, 'apps', 'webclaw', 'package.json')
    : path.join(targetDir, 'package.json')

  if (!fs.existsSync(appPackagePath)) return

  const packageJson = JSON.parse(fs.readFileSync(appPackagePath, 'utf8'))
  if (!packageJson.scripts || typeof packageJson.scripts.dev !== 'string') return

  if (packageJson.scripts.dev.includes('--port')) {
    packageJson.scripts.dev = packageJson.scripts.dev.replace(
      /--port\s+\d+/,
      `--port ${port}`,
    )
  } else {
    packageJson.scripts.dev = `${packageJson.scripts.dev} --port ${port}`
  }

  fs.writeFileSync(appPackagePath, `${JSON.stringify(packageJson, null, 2)}\n`)
}

function writeEnvFile(targetDir, envValues) {
  const envFile = resolveEnvFile(targetDir)
  ensureDir(path.dirname(envFile))

  const lines = [
    `CLAWDBOT_GATEWAY_URL=${envValues.gatewayUrl}`,
    `CLAWDBOT_GATEWAY_TOKEN=${envValues.gatewayToken}`,
  ]

  if (envValues.gatewayPassword.length > 0) {
    lines.push(`CLAWDBOT_GATEWAY_PASSWORD=${envValues.gatewayPassword}`)
  }

  fs.writeFileSync(envFile, `${lines.join('\n')}\n`)
  process.stdout.write(`Wrote ${envFile}\n\n`)
}

async function maybeSetupEnv(targetDir, options, envValues) {
  if (options.has('--skip-env')) return

  if (envValues) {
    writeEnvFile(targetDir, envValues)
    return
  }

  if (!process.stdin.isTTY || !process.stdout.isTTY) return

  const envFile = resolveEnvFile(targetDir)
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  })

  try {
    const createAnswer = await askQuestion(
      rl,
      `Create ${envFile} now? [Y/n]: `,
    )
    const shouldCreate =
      createAnswer.length === 0 ||
      createAnswer.toLowerCase() === 'y' ||
      createAnswer.toLowerCase() === 'yes'

    if (!shouldCreate) {
      process.stdout.write(
        `Skipping env file. Create it later at ${envFile} with:\n` +
          `CLAWDBOT_GATEWAY_URL=...\n` +
          `CLAWDBOT_GATEWAY_TOKEN=...\n\n`,
      )
      return
    }

    if (fs.existsSync(envFile)) {
      const overwriteAnswer = await askQuestion(
        rl,
        `${envFile} already exists. Overwrite? [y/N]: `,
      )
      const shouldOverwrite =
        overwriteAnswer.toLowerCase() === 'y' ||
        overwriteAnswer.toLowerCase() === 'yes'
      if (!shouldOverwrite) {
        process.stdout.write(`Keeping existing ${envFile}\n\n`)
        return
      }
    }

    const gatewayUrl = await askQuestion(rl, 'CLAWDBOT_GATEWAY_URL: ')
    const gatewayToken = await askQuestion(rl, 'CLAWDBOT_GATEWAY_TOKEN: ')

    writeEnvFile(targetDir, {
      gatewayUrl,
      gatewayToken,
      gatewayPassword: '',
    })
  } finally {
    rl.close()
  }
}

function installDependencies(targetDir) {
  const packageManager = detectPackageManager(targetDir)
  if (packageManager === 'yarn') {
    runCommand('yarn', ['install'], targetDir)
    return
  }

  runCommand(packageManager, ['install'], targetDir)
}

function startProject(targetDir) {
  const packageManager = detectPackageManager(targetDir)
  runCommand(packageManager, ['run', 'dev'], targetDir)
}

async function initProject(rawTarget, options, bootstrapConfig) {
  if (!bootstrapConfig) {
    printBanner()
  }
  const targetDir = path.resolve(process.cwd(), rawTarget ?? '.')
  const force = options.has('--force')
  const isCurrentDir = targetDir === process.cwd()

  ensureDir(targetDir)
  if (!force && !isDirEmpty(targetDir)) {
    process.stderr.write(
      `Target directory is not empty. Use --force to continue: ${targetDir}\n`,
    )
    process.exit(1)
  }

  if (force && !isDirEmpty(targetDir) && isCurrentDir) {
    process.stderr.write(
      'Refusing to overwrite current directory. Use an empty directory for init.\n',
    )
    process.exit(1)
  }

  if (force && !isDirEmpty(targetDir) && !isCurrentDir) {
    for (const entry of fs.readdirSync(targetDir)) {
      if (entry === '.git') continue
      fs.rmSync(path.join(targetDir, entry), { recursive: true, force: true })
    }
  }

  if (!fs.existsSync(path.join(targetDir, '.git')) && isDirEmpty(targetDir)) {
    populateTemplate(targetDir, isCurrentDir)
  }

  ensureGitRepository(targetDir)

  if (bootstrapConfig) {
    setDevPort(targetDir, bootstrapConfig.port)
  }

  await maybeSetupEnv(targetDir, options, bootstrapConfig?.envValues)

  process.stdout.write(`\nWebClaw project created at ${targetDir}\n\n`)

  if (bootstrapConfig && bootstrapConfig.autoStart) {
    process.stdout.write(`Installing dependencies...\n`)
    installDependencies(targetDir)
    process.stdout.write(`Starting WebClaw on port ${bootstrapConfig?.port ?? 3000}...\n\n`)
    startProject(targetDir)
    return
  }

  process.stdout.write(`Next steps:\n`)
  process.stdout.write(`  cd ${path.relative(process.cwd(), targetDir) || '.'}\n`)
  process.stdout.write(`  pnpm install\n`)
  process.stdout.write(`  pnpm dev\n\n`)
}

async function askBootstrapConfig(defaultProjectName, parsedArgs) {
  const nonInteractive =
    parsedArgs.flags.has('--yes') || !process.stdin.isTTY || !process.stdout.isTTY

  const initialProjectName =
    parsedArgs.values.get('--project-name') || defaultProjectName || 'webclaw'
  const initialGatewayUrl =
    parsedArgs.values.get('--gateway-url') || 'ws://127.0.0.1:18789'
  const initialGatewayToken = parsedArgs.values.get('--gateway-token') || ''
  const initialGatewayPassword = parsedArgs.values.get('--gateway-password') || ''
  const initialPort = parsePort(parsedArgs.values.get('--port') || 3000, 3000)

  if (nonInteractive) {
    return {
      projectName: initialProjectName,
      envValues: {
        gatewayUrl: initialGatewayUrl,
        gatewayToken: initialGatewayToken,
        gatewayPassword: initialGatewayPassword,
      },
      port: initialPort,
      autoStart: !parsedArgs.flags.has('--no-start'),
    }
  }

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  })

  try {
    const projectNameInput = await askQuestion(
      rl,
      `Project name [${initialProjectName}]: `,
    )
    const projectName = projectNameInput || initialProjectName

    const gatewayUrlInput = await askQuestion(
      rl,
      `CLAWDBOT_GATEWAY_URL [${initialGatewayUrl}]: `,
    )
    const gatewayUrl = gatewayUrlInput || initialGatewayUrl

    const gatewayTokenInput = await askQuestion(
      rl,
      'CLAWDBOT_GATEWAY_TOKEN (optional): ',
    )
    const gatewayPasswordInput = await askQuestion(
      rl,
      'CLAWDBOT_GATEWAY_PASSWORD (optional): ',
    )

    const portInput = await askQuestion(rl, `Port [${initialPort}]: `)
    const port = parsePort(portInput || initialPort, initialPort)

    return {
      projectName,
      envValues: {
        gatewayUrl,
        gatewayToken: gatewayTokenInput || initialGatewayToken,
        gatewayPassword: gatewayPasswordInput || initialGatewayPassword,
      },
      port,
      autoStart: !parsedArgs.flags.has('--no-start'),
    }
  } finally {
    rl.close()
  }
}

function doctor() {
  const nodeMajor = Number(process.versions.node.split('.')[0] || 0)
  const hasPnpm = spawnSync('pnpm', ['--version'], { stdio: 'ignore' }).status === 0
  const issues = []

  if (nodeMajor < 20) {
    issues.push('Node.js >= 20 is required.')
  }
  if (!hasPnpm) {
    issues.push('pnpm is recommended but was not found in PATH.')
  }

  if (issues.length === 0) {
    process.stdout.write('Environment looks good.\n')
    return
  }

  for (const issue of issues) {
    process.stderr.write(`- ${issue}\n`)
  }
  process.exit(1)
}

async function main() {
  const args = process.argv.slice(2)
  const parsedArgs = parseCliArgs(args)
  const options = parsedArgs.flags
  const command = parsedArgs.positionals[0]

  if (options.has('-h') || options.has('--help')) {
    printHelp()
    return
  }

  if (!command) {
    printBanner()
    const bootstrapConfig = await askBootstrapConfig(null, parsedArgs)
    await initProject(bootstrapConfig.projectName, options, bootstrapConfig)
    return
  }

  if (command === 'init') {
    const target = parsedArgs.positionals[1]
    await initProject(target, options)
    return
  }

  if (command === 'doctor') {
    doctor()
    return
  }

  if (
    command === 'dev' ||
    command === 'build' ||
    command === 'preview' ||
    command === 'test' ||
    command === 'lint'
  ) {
    runProjectScript(command)
    return
  }

  process.stderr.write(`Unknown command: ${command}\n\n`)
  printHelp()
  process.exit(1)
}

void main().catch((error) => {
  process.stderr.write(
    `${error instanceof Error ? error.message : String(error)}\n`,
  )
  process.exit(1)
})
