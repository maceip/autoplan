import { describe, expect, it } from 'vitest'
import {
  assistantPartRenderOrder,
  mapStandaloneToolResultToToolPart,
} from './message-item'
import type { GatewayMessage } from '../types'

describe('assistantPartRenderOrder', function () {
  it('keeps assistant content order from message parts', function () {
    const message: GatewayMessage = {
      role: 'assistant',
      content: [
        { type: 'thinking', thinking: 'first' },
        { type: 'text', text: 'second' },
        {
          type: 'toolCall',
          id: 'functions.read:17',
          name: 'read',
          arguments: { file_path: '/tmp/a.md' },
        },
        { type: 'text', text: 'third' },
      ],
    }

    expect(assistantPartRenderOrder(message, true, true)).toEqual([
      'thinking',
      'text',
      'toolCall',
      'text',
    ])
  })
})

describe('mapStandaloneToolResultToToolPart', function () {
  it('maps text-only toolResult content to visible output', function () {
    const message: GatewayMessage = {
      role: 'toolResult',
      toolCallId: 'functions.read:9',
      toolName: 'read',
      isError: false,
      content: [{ type: 'text', text: 'file contents' }],
      timestamp: 1,
    }

    expect(mapStandaloneToolResultToToolPart(message)).toEqual({
      type: 'read',
      state: 'output-available',
      output: { text: 'file contents' },
      toolCallId: 'functions.read:9',
      errorText: undefined,
    })
  })
})
