# webclaw

Official CLI for WebClaw. It initializes a new project by cloning the WebClaw repository.

## Usage

```bash
npx webclaw
```

You will be prompted for:
- project name
- environment keys (`CLAWDBOT_GATEWAY_URL`, token/password)
- local dev port

Then the CLI creates the project folder, installs dependencies, and starts WebClaw.

Run project commands from a WebClaw project directory:

```bash
webclaw dev
webclaw build
webclaw preview
webclaw test
webclaw lint
```

## Commands

- `webclaw` - create and start a new project
- `webclaw init [dir]` - initialize a project in `dir` (legacy)
- `webclaw doctor` - validate local prerequisites
