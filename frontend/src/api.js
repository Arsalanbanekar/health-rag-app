const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

/**
 * Send a health query and get a complete response.
 */
export async function queryHealth(query, sessionId = 'anonymous', language = 'English') {
  const res = await fetch(`${API_URL}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, session_id: sessionId, language }),
  });
  if (!res.ok) {
    throw new Error(`Server error: ${res.status}`);
  }
  return res.json();
}

/**
 * Send a health query and get a streaming response (SSE).
 * Calls onToken for each token, onDone when complete.
 */
export async function queryHealthStream(query, sessionId, { onToken, onDone, onError }, language = 'English', history = []) {
  try {
    const res = await fetch(`${API_URL}/query/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, session_id: sessionId, language, history }),
    });

    if (!res.ok) {
      throw new Error(`Server error: ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete line in buffer

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const dataStr = line.slice(6);
          if (dataStr === '[DONE]') {
            onDone?.();
            return;
          }
          try {
            const token = JSON.parse(dataStr);
            onToken?.(token);
          } catch (e) {
            // Unparseable token, ignore gracefully
          }
        }
      }
    }
    onDone?.();
  } catch (err) {
    onError?.(err);
  }
}

/**
 * Fetch health check from backend.
 */
export async function getHealthStatus() {
  try {
    const res = await fetch(`${API_URL}/health`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

/**
 * Fetch supported health domains.
 */
export async function getDomains() {
  try {
    const res = await fetch(`${API_URL}/domains`);
    if (!res.ok) return [];
    const data = await res.json();
    return data.domains || [];
  } catch {
    return [];
  }
}
