type SlackWebhookPayload = {
  text: string;
};

type Env = {
  SLACK_WEBHOOK_URL: string;
  ASSETS: {
    fetch: (request: Request) => Promise<Response>;
  };
};

type LeadPayload = {
  workEmail: string;
  companyName: string;
  companySize: string;
  role: string;
  usage: string;
  website?: string;
  submittedAt?: string;
};

type RateLimitState = {
  count: number;
  resetAt: number;
};

const ALLOWED_ORIGINS = new Set(["https://webclaw.dev"]);
const RATE_LIMIT_WINDOW_MS = 60_000;
const RATE_LIMIT_MAX = 8;
const rateLimitCache = new Map<string, RateLimitState>();

function buildSlackMessage(payload: LeadPayload) {
  const fields = [
    `Work email: ${payload.workEmail || "-"}`,
    `Company / team: ${payload.companyName || "-"}`,
    `Company size: ${payload.companySize || "-"}`,
    `Role: ${payload.role || "-"}`,
    `Usage: ${payload.usage || "-"}`,
  ];

  return fields.join("\n");
}

export default {
  async fetch(request: Request, env: Env) {
    const url = new URL(request.url);

    if (url.pathname === "/api/lead") {
      if (request.method === "OPTIONS") {
        return new Response(null, {
          status: 204,
          headers: {
            "Access-Control-Allow-Origin": "https://webclaw.dev",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
          },
        });
      }

      if (request.method !== "POST") {
        return new Response("Method Not Allowed", { status: 405 });
      }

      const originHeader = request.headers.get("Origin");
      const refererHeader = request.headers.get("Referer");
      const originToCheck = originHeader ?? refererHeader;

      if (!originToCheck) {
        return new Response("Missing origin", { status: 403 });
      }

      let origin: string;

      try {
        origin = new URL(originToCheck).origin;
      } catch (error) {
        return new Response("Invalid origin", { status: 403 });
      }

      if (!ALLOWED_ORIGINS.has(origin)) {
        return new Response("Forbidden", { status: 403 });
      }

      const ip =
        request.headers.get("CF-Connecting-IP") ??
        request.headers.get("X-Forwarded-For") ??
        "unknown";
      const now = Date.now();
      const rateState = rateLimitCache.get(ip);

      if (!rateState || rateState.resetAt < now) {
        rateLimitCache.set(ip, { count: 1, resetAt: now + RATE_LIMIT_WINDOW_MS });
      } else {
        rateState.count += 1;
        if (rateState.count > RATE_LIMIT_MAX) {
          return new Response("Too many requests", { status: 429 });
        }
      }

      let payload: LeadPayload;

      try {
        payload = (await request.json()) as LeadPayload;
      } catch (error) {
        return new Response("Invalid JSON", { status: 400 });
      }

      if (!payload.workEmail) {
        return new Response("Missing work email", { status: 400 });
      }

      if (payload.website) {
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": origin,
          },
        });
      }

      if (payload.submittedAt) {
        const submittedTime = Number(payload.submittedAt);
        const maxAgeMs = 15 * 60_000;

        if (!Number.isFinite(submittedTime)) {
          return new Response("Invalid submission time", { status: 400 });
        }

        if (submittedTime > now + 5_000) {
          return new Response("Invalid submission time", { status: 400 });
        }

        if (now - submittedTime > maxAgeMs) {
          return new Response("Submission expired", { status: 400 });
        }
      }

      const webhookPayload: SlackWebhookPayload = {
        text: `New WebClaw workspace lead\n${buildSlackMessage(payload)}`,
      };

      const slackResponse = await fetch(env.SLACK_WEBHOOK_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(webhookPayload),
      });

      if (!slackResponse.ok) {
        return new Response("Slack webhook failed", { status: 502 });
      }

      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": origin,
        },
      });
    }

    return env.ASSETS.fetch(request);
  },
};
