'use strict';

/**
 * Nucleus Chromium Prompt API UtilityProcess Handler (Electron 45.3.2 / Chromium 156)
 *
 * Implements Electron's `LanguageModelUtility` (`require('electron/utility')`) and
 * registers it via `localAIHandler.setPromptAPIHandler(...)` so that standard
 * Chromium `window.LanguageModel.availability()` and `window.LanguageModel.create()`
 * execute on-device Apple Silicon Metal inference via `mlx_lm.server`
 * (`mlx-community/Qwen3-4B-Instruct-2507-4bit`).
 */

const http = require('node:http');
const { LanguageModelUtility, localAIHandler } = require('electron/utility');

const MLX_PORT = Number(process.env.AUTOPLAN_MLX_PORT || 18089);
const MLX_MODEL =
  process.env.AUTOPLAN_MLX_MODEL || 'mlx-community/Qwen3-4B-Instruct-2507-4bit';
const CONTEXT_WINDOW = 32768;

function notifyParent(payload) {
  try {
    if (process.parentPort && typeof process.parentPort.postMessage === 'function') {
      process.parentPort.postMessage(payload);
    }
  } catch {
    // ignore IPC teardown races
  }
}

function httpJsonRequest(method, reqPath, bodyObj, timeoutMs = 45000) {
  return new Promise((resolve, reject) => {
    const bodyStr = bodyObj ? JSON.stringify(bodyObj) : '';
    const req = http.request(
      {
        hostname: '127.0.0.1',
        port: MLX_PORT,
        path: reqPath,
        method,
        headers: bodyObj
          ? {
              'content-type': 'application/json',
              'content-length': Buffer.byteLength(bodyStr),
            }
          : {},
        timeout: timeoutMs,
      },
      (res) => {
        const chunks = [];
        res.on('data', (chunk) => chunks.push(chunk));
        res.on('end', () => {
          const raw = Buffer.concat(chunks).toString('utf8');
          if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) {
            try {
              resolve(JSON.parse(raw));
            } catch (err) {
              reject(new Error(`Invalid JSON from local MLX server: ${err.message}`));
            }
          } else {
            reject(
              new Error(
                `Local MLX HTTP ${res.statusCode || 0}: ${raw.slice(0, 240)}`
              )
            );
          }
        });
      }
    );
    req.on('timeout', () => {
      req.destroy(new Error(`Local MLX request timed out after ${timeoutMs}ms`));
    });
    req.on('error', reject);
    if (bodyStr) {
      req.write(bodyStr);
    }
    req.end();
  });
}

function extractTextFromLMMessage(msg) {
  if (!msg) return '';
  if (typeof msg.content === 'string') return msg.content;
  if (Array.isArray(msg.content)) {
    return msg.content
      .map((part) => {
        if (!part) return '';
        if (typeof part === 'string') return part;
        if (part.type === 'text' && typeof part.value === 'string') {
          return part.value;
        }
        return '';
      })
      .filter(Boolean)
      .join('\n');
  }
  return String(msg.value || '');
}

function toOpenAIMessages(lmMessages) {
  if (!Array.isArray(lmMessages)) return [];
  return lmMessages
    .map((m) => ({
      role:
        m.role === 'system' || m.role === 'assistant' || m.role === 'user'
          ? m.role
          : 'user',
      content: extractTextFromLMMessage(m),
    }))
    .filter((m) => m.content.trim().length > 0);
}

function stripReasoningTags(text) {
  if (typeof text !== 'string') return '';
  return text.replace(/<think>[\s\S]*?<\/think>/gi, '').trim();
}

function approxTokens(messages) {
  const chars = messages.reduce(
    (sum, m) => sum + (typeof m.content === 'string' ? m.content.length : 0),
    0
  );
  return Math.max(1, Math.ceil(chars / 4));
}

class NucleusMetalLanguageModel extends LanguageModelUtility {
  constructor(initialMessages = [], initialUsage = 0) {
    super({
      contextUsage: initialUsage,
      contextWindow: CONTEXT_WINDOW,
    });
    this._messages = Array.isArray(initialMessages) ? [...initialMessages] : [];
    this._destroyed = false;
  }

  static async availability(_options) {
    try {
      await httpJsonRequest('GET', '/v1/models', null, 2500);
      return 'available';
    } catch {
      return 'unavailable';
    }
  }

  static async create(options) {
    const avail = await NucleusMetalLanguageModel.availability(options);
    if (avail !== 'available') {
      throw new Error(
        `Local Metal MLX server on 127.0.0.1:${MLX_PORT} is not listening.`
      );
    }
    const initMsgs = toOpenAIMessages(options?.initialPrompts || []);
    return new NucleusMetalLanguageModel(initMsgs, approxTokens(initMsgs));
  }

  async append(input, _options) {
    if (this._destroyed) throw new Error('LanguageModel session destroyed');
    const converted = toOpenAIMessages(input);
    this._messages.push(...converted);
    this.contextUsage = Math.min(CONTEXT_WINDOW, approxTokens(this._messages));
    return undefined;
  }

  async clone(_options) {
    if (this._destroyed) throw new Error('LanguageModel session destroyed');
    return new NucleusMetalLanguageModel(
      this._messages.map((m) => ({ ...m })),
      this.contextUsage
    );
  }

  async measureContextUsage(input, _options) {
    const converted = toOpenAIMessages(input);
    return approxTokens(converted);
  }

  async prompt(input, options) {
    if (this._destroyed) throw new Error('LanguageModel session destroyed');
    const startedAt = Date.now();
    const userTurns = toOpenAIMessages(input);
    const fullConversation = [...this._messages, ...userTurns];

    if (options && options.responseConstraint) {
      let schemaDesc = '';
      if (options.responseConstraint instanceof RegExp) {
        schemaDesc = `Respond ONLY with text matching regex ${options.responseConstraint.toString()}.`;
      } else {
        try {
          schemaDesc = `Respond ONLY with valid JSON matching this schema (no markdown fences): ${JSON.stringify(
            options.responseConstraint
          )}`;
        } catch {
          schemaDesc = 'Respond ONLY with valid JSON (no markdown fences).';
        }
      }
      fullConversation.unshift({
        role: 'system',
        content: schemaDesc,
      });
    }

    const res = await httpJsonRequest(
      'POST',
      '/v1/chat/completions',
      {
        model: MLX_MODEL,
        messages: fullConversation,
        temperature: 0.2,
        max_tokens: 1024,
      },
      60000
    );

    const rawReply =
      res?.choices?.[0]?.message?.content ||
      res?.choices?.[0]?.text ||
      '';
    const cleanReply = stripReasoningTags(rawReply);

    this._messages.push(...userTurns, {
      role: 'assistant',
      content: cleanReply,
    });
    const usedTokens =
      typeof res?.usage?.total_tokens === 'number'
        ? res.usage.total_tokens
        : approxTokens(this._messages);
    this.contextUsage = Math.min(CONTEXT_WINDOW, usedTokens);

    const latencyMs = Date.now() - startedAt;
    notifyParent({
      type: 'prompt_completed',
      model: MLX_MODEL,
      latencyMs,
      tokens: usedTokens,
    });

    return cleanReply;
  }

  destroy() {
    this._destroyed = true;
    this._messages = [];
  }
}

localAIHandler.setPromptAPIHandler((details) => {
  notifyParent({
    type: 'binding_requested',
    securityOrigin: details?.securityOrigin || '',
    webContentsId: details?.webContentsId || 0,
  });
  return NucleusMetalLanguageModel;
});

notifyParent({
  type: 'ready',
  mlxPort: MLX_PORT,
  mlxModel: MLX_MODEL,
});
