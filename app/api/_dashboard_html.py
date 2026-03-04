"""Dashboard HTML — inlined to avoid Vercel serverless file-system issues."""

DASHBOARD_HTML: str = """<!DOCTYPE html>
<html lang="en" class="h-full">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Webhook Bridge — Admin Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.14.1/dist/cdn.min.js"></script>
  <style>
    [x-cloak] { display: none !important; }
    .log-stream::-webkit-scrollbar { width: 6px; }
    .log-stream::-webkit-scrollbar-track { background: #111827; }
    .log-stream::-webkit-scrollbar-thumb { background: #374151; border-radius: 3px; }
  </style>
</head>
<body class="h-full bg-gray-950 text-gray-100 font-sans" x-data="dashboard()" x-cloak>

  <!-- NAV BAR -->
  <nav class="bg-gray-900 border-b border-gray-800 px-4 py-3 flex items-center justify-between sticky top-0 z-50">
    <div class="flex items-center gap-3">
      <svg class="w-7 h-7 text-indigo-400" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
      <span class="text-lg font-semibold tracking-tight">Webhook Bridge</span>
    </div>
    <div class="flex items-center gap-3" x-show="authenticated">
      <span class="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full"
            :class="wsConnected ? 'bg-emerald-900/50 text-emerald-400' : 'bg-gray-800 text-gray-400'">
        <span class="w-2 h-2 rounded-full" :class="wsConnected ? 'bg-emerald-400' : 'bg-gray-500'"></span>
        <span x-text="wsConnected ? 'Live' : 'Polling'"></span>
      </span>
      <button @click="logout()" class="text-xs text-gray-400 hover:text-gray-200 px-2 py-1 rounded hover:bg-gray-800 transition">Logout</button>
    </div>
  </nav>

  <!-- AUTH GATE -->
  <div x-show="!authenticated" class="flex items-center justify-center min-h-[80vh]">
    <div class="bg-gray-900 rounded-xl border border-gray-800 p-8 w-full max-w-md mx-4">
      <h2 class="text-xl font-semibold mb-1">Admin Dashboard</h2>
      <p class="text-gray-400 text-sm mb-6">Enter your API key to continue.</p>
      <div class="space-y-4">
        <input type="password" x-model="apiKey" placeholder="Admin API Key"
               @keydown.enter="login()"
               class="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent placeholder-gray-500" />
        <p x-show="authError" x-text="authError" class="text-red-400 text-sm"></p>
        <button @click="login()" :disabled="!apiKey || authLoading"
                class="w-full bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium rounded-lg px-4 py-2.5 text-sm transition">
          <span x-show="!authLoading">Connect</span>
          <span x-show="authLoading">Connecting...</span>
        </button>
      </div>
    </div>
  </div>

  <!-- MAIN DASHBOARD -->
  <main x-show="authenticated" class="max-w-7xl mx-auto px-4 py-6 space-y-6">

    <!-- HEALTH CARDS -->
    <section>
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-sm font-medium text-gray-400 uppercase tracking-wider">System Health</h2>
        <button @click="fetchHealth()" class="text-xs text-gray-500 hover:text-gray-300 transition">Refresh</button>
      </div>
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <!-- Service Status -->
        <div class="bg-gray-900 rounded-xl border border-gray-800 p-4">
          <div class="text-xs text-gray-500 mb-1">Service</div>
          <template x-if="health">
            <div>
              <span class="text-lg font-semibold" :class="health.status === 'ok' ? 'text-emerald-400' : 'text-red-400'" x-text="health.status === 'ok' ? 'Healthy' : 'Degraded'"></span>
            </div>
          </template>
          <template x-if="!health">
            <span class="text-gray-600 text-sm">Loading...</span>
          </template>
        </div>
        <!-- Telegram -->
        <div class="bg-gray-900 rounded-xl border border-gray-800 p-4">
          <div class="text-xs text-gray-500 mb-1">Telegram</div>
          <template x-if="health && health.telegram">
            <div>
              <span class="text-lg font-semibold" :class="health.telegram.connected ? 'text-emerald-400' : 'text-red-400'" x-text="health.telegram.connected ? 'Connected' : 'Disconnected'"></span>
              <div x-show="health.telegram.bot_username" class="text-xs text-gray-500 mt-0.5">@<span x-text="health.telegram.bot_username"></span></div>
              <div x-show="health.telegram.error" class="text-xs text-red-400 mt-0.5" x-text="health.telegram.error"></div>
            </div>
          </template>
          <template x-if="!health">
            <span class="text-gray-600 text-sm">Loading...</span>
          </template>
        </div>
        <!-- Circuit Breaker -->
        <div class="bg-gray-900 rounded-xl border border-gray-800 p-4">
          <div class="text-xs text-gray-500 mb-1">Circuit Breaker</div>
          <template x-if="health && health.circuit_breaker">
            <span class="text-lg font-semibold"
                  :class="health.circuit_breaker.state === 'closed' ? 'text-emerald-400' : health.circuit_breaker.state === 'half_open' ? 'text-amber-400' : 'text-red-400'"
                  x-text="health.circuit_breaker.state"></span>
          </template>
          <template x-if="!health">
            <span class="text-gray-600 text-sm">Loading...</span>
          </template>
        </div>
        <!-- Storage -->
        <div class="bg-gray-900 rounded-xl border border-gray-800 p-4">
          <div class="text-xs text-gray-500 mb-1">Storage</div>
          <template x-if="health && health.storage">
            <div>
              <span class="text-lg font-semibold" :class="health.storage.fallback_active ? 'text-amber-400' : 'text-emerald-400'" x-text="health.storage.effective_backend"></span>
              <div x-show="health.storage.fallback_active" class="text-xs text-amber-400 mt-0.5" x-text="health.storage.fallback_reason"></div>
            </div>
          </template>
          <template x-if="!health">
            <span class="text-gray-600 text-sm">Loading...</span>
          </template>
        </div>
      </div>
    </section>

    <!-- DELIVERIES TABLE -->
    <section>
      <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h2 class="text-sm font-medium text-gray-400 uppercase tracking-wider">Deliveries</h2>
        <div class="flex items-center gap-2 flex-wrap">
          <select x-model="deliveriesFilter.source" @change="deliveriesPage = 0; fetchDeliveries()"
                  class="bg-gray-800 border border-gray-700 text-sm rounded-lg px-2 py-1 focus:outline-none focus:ring-1 focus:ring-indigo-500">
            <option value="">All Sources</option>
            <option value="github">GitHub</option>
            <option value="generic">Generic</option>
          </select>
          <select x-model="deliveriesFilter.status" @change="deliveriesPage = 0; fetchDeliveries()"
                  class="bg-gray-800 border border-gray-700 text-sm rounded-lg px-2 py-1 focus:outline-none focus:ring-1 focus:ring-indigo-500">
            <option value="">All Statuses</option>
            <option value="delivered">Delivered</option>
            <option value="failed">Failed</option>
            <option value="pending">Pending</option>
          </select>
          <button @click="replayAllFailed()" class="bg-red-600 hover:bg-red-500 text-white text-xs font-medium rounded-lg px-3 py-1.5 transition">
            Replay All Failed
          </button>
        </div>
      </div>

      <div class="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-gray-800 text-gray-500 text-xs uppercase">
                <th class="text-left px-4 py-3 font-medium">ID</th>
                <th class="text-left px-4 py-3 font-medium">Source</th>
                <th class="text-left px-4 py-3 font-medium">Event</th>
                <th class="text-left px-4 py-3 font-medium">Status</th>
                <th class="text-left px-4 py-3 font-medium">Time</th>
                <th class="text-right px-4 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              <template x-if="deliveriesLoading && deliveries.length === 0">
                <tr><td colspan="6" class="text-center py-8 text-gray-600">Loading deliveries...</td></tr>
              </template>
              <template x-if="!deliveriesLoading && deliveries.length === 0">
                <tr><td colspan="6" class="text-center py-8 text-gray-600">No deliveries found.</td></tr>
              </template>
              <template x-for="d in deliveries" :key="d.delivery_id || d.id">
                <tr class="border-b border-gray-800/50 hover:bg-gray-800/50 transition cursor-pointer"
                    @click="toggleRow(d.delivery_id || d.id)">
                  <td class="px-4 py-3 font-mono text-xs text-gray-400" x-text="(d.delivery_id || d.id || '').slice(0, 8)"></td>
                  <td class="px-4 py-3" x-text="d.source || 'github'"></td>
                  <td class="px-4 py-3" x-text="d.event_type || d.event || '-'"></td>
                  <td class="px-4 py-3">
                    <span class="px-2 py-0.5 rounded-full text-xs font-medium"
                          :class="statusColor(d.status)" x-text="d.status"></span>
                  </td>
                  <td class="px-4 py-3 text-gray-400 text-xs" x-text="timeAgo(d.timestamp || d.created_at)"></td>
                  <td class="px-4 py-3 text-right">
                    <button @click.stop="replayDelivery(d.delivery_id || d.id)"
                            class="bg-indigo-600 hover:bg-indigo-500 text-white text-xs rounded px-2 py-1 transition">
                      Replay
                    </button>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>

        <!-- Expanded Row Payload -->
        <template x-for="d in deliveries" :key="'detail-' + (d.delivery_id || d.id)">
          <div x-show="expandedRows[d.delivery_id || d.id]"
               x-transition
               class="bg-gray-950 border-t border-gray-800 px-4 py-3">
            <pre class="text-xs text-gray-400 overflow-auto max-h-64 whitespace-pre-wrap" x-text="JSON.stringify(d, null, 2)"></pre>
          </div>
        </template>

        <!-- Pagination -->
        <div class="flex items-center justify-between px-4 py-3 border-t border-gray-800 text-xs text-gray-500">
          <span>Showing <span x-text="deliveries.length"></span> of <span x-text="deliveriesTotal"></span></span>
          <div class="flex gap-2">
            <button @click="deliveriesPage = Math.max(0, deliveriesPage - 1); fetchDeliveries()"
                    :disabled="deliveriesPage === 0"
                    class="px-3 py-1 rounded bg-gray-800 hover:bg-gray-700 disabled:opacity-30 disabled:cursor-not-allowed transition">
              Prev
            </button>
            <button @click="deliveriesPage++; fetchDeliveries()"
                    :disabled="(deliveriesPage + 1) * deliveriesPageSize >= deliveriesTotal"
                    class="px-3 py-1 rounded bg-gray-800 hover:bg-gray-700 disabled:opacity-30 disabled:cursor-not-allowed transition">
              Next
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- LIVE LOG STREAM -->
    <section>
      <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h2 class="text-sm font-medium text-gray-400 uppercase tracking-wider">Live Stream</h2>
        <div class="flex items-center gap-2 flex-wrap">
          <input type="text" x-model="logFilter.event_type" placeholder="Event type"
                 @input.debounce.300ms="reconnectWs()"
                 class="bg-gray-800 border border-gray-700 text-sm rounded-lg px-2 py-1 w-28 focus:outline-none focus:ring-1 focus:ring-indigo-500 placeholder-gray-600" />
          <input type="text" x-model="logFilter.status" placeholder="Status"
                 @input.debounce.300ms="reconnectWs()"
                 class="bg-gray-800 border border-gray-700 text-sm rounded-lg px-2 py-1 w-24 focus:outline-none focus:ring-1 focus:ring-indigo-500 placeholder-gray-600" />
          <input type="text" x-model="logFilter.repo" placeholder="Repo"
                 @input.debounce.300ms="reconnectWs()"
                 class="bg-gray-800 border border-gray-700 text-sm rounded-lg px-2 py-1 w-32 focus:outline-none focus:ring-1 focus:ring-indigo-500 placeholder-gray-600" />
          <button @click="logs = []" class="text-xs text-gray-500 hover:text-gray-300 transition">Clear</button>
        </div>
      </div>
      <div class="bg-gray-900 rounded-xl border border-gray-800 p-4">
        <div x-show="wsError" class="text-xs text-amber-400 mb-2" x-text="wsError"></div>
        <div class="log-stream overflow-y-auto max-h-96 space-y-1 font-mono text-xs" x-ref="logContainer">
          <template x-if="logs.length === 0">
            <p class="text-gray-600 text-center py-8">Waiting for events...</p>
          </template>
          <template x-for="(log, i) in logs" :key="i">
            <div class="flex gap-3 py-1 px-2 rounded hover:bg-gray-800/50">
              <span class="text-gray-600 shrink-0" x-text="log.time"></span>
              <span class="shrink-0 px-1.5 rounded text-xs font-medium"
                    :class="statusColor(log.status)" x-text="log.status || 'event'"></span>
              <span class="text-gray-400" x-text="log.event_type || '-'"></span>
              <span class="text-gray-500 truncate" x-text="log.summary || ''"></span>
            </div>
          </template>
        </div>
      </div>
    </section>
  </main>

  <script>
    function dashboard() {
      return {
        apiKey: localStorage.getItem('dwb_api_key') || '',
        authenticated: false,
        authLoading: false,
        authError: '',
        health: null,
        deliveries: [],
        deliveriesTotal: 0,
        deliveriesPage: 0,
        deliveriesPageSize: 20,
        deliveriesFilter: { source: '', status: '' },
        deliveriesLoading: false,
        expandedRows: {},
        logs: [],
        wsConnected: false,
        wsError: '',
        logFilter: { event_type: '', status: '', repo: '' },
        _ws: null,
        _healthInterval: null,
        _pollInterval: null,
        _wsGeneration: 0,

        async init() {
          if (this.apiKey) await this.login(true);
        },

        async login(silent = false) {
          this.authLoading = true;
          this.authError = '';
          try {
            const res = await fetch('/deliveries?limit=1', {
              headers: { 'X-Api-Key': this.apiKey }
            });
            if (res.ok) {
              this.authenticated = true;
              localStorage.setItem('dwb_api_key', this.apiKey);
              this.fetchHealth();
              this.startHealthRefresh();
              this.fetchDeliveries();
              this.connectWebSocket();
            } else if (!silent) {
              const data = await res.json().catch(() => ({}));
              this.authError = data.message || `Authentication failed (${res.status})`;
            }
          } catch (e) {
            if (!silent) this.authError = 'Connection failed: ' + e.message;
          } finally {
            this.authLoading = false;
          }
        },

        logout() {
          this.authenticated = false;
          this.apiKey = '';
          this.health = null;
          this.deliveries = [];
          this.logs = [];
          localStorage.removeItem('dwb_api_key');
          if (this._ws) { this._ws.close(); this._ws = null; }
          if (this._healthInterval) { clearInterval(this._healthInterval); this._healthInterval = null; }
          if (this._pollInterval) { clearInterval(this._pollInterval); this._pollInterval = null; }
          this.wsConnected = false;
        },

        async fetchHealth() {
          try {
            const res = await fetch('/health/deep', {
              headers: { 'X-Api-Key': this.apiKey }
            });
            const data = await res.json().catch(() => null);
            if (data && (res.ok || res.status === 503)) {
              this.health = data;
              return;
            }
            console.warn('Health fetch unexpected response:', res.status, data);
          } catch (e) {
            console.warn('Health fetch failed:', e);
          }
        },

        startHealthRefresh() {
          if (this._healthInterval) clearInterval(this._healthInterval);
          this._healthInterval = setInterval(() => this.fetchHealth(), 30000);
        },

        async fetchDeliveries() {
          this.deliveriesLoading = true;
          try {
            const params = new URLSearchParams({
              limit: String(this.deliveriesPageSize),
              offset: String(this.deliveriesPage * this.deliveriesPageSize),
            });
            if (this.deliveriesFilter.source) params.set('source', this.deliveriesFilter.source);
            if (this.deliveriesFilter.status) params.set('status', this.deliveriesFilter.status);
            const res = await fetch(`/deliveries?${params}`, {
              headers: { 'X-Api-Key': this.apiKey }
            });
            if (res.ok) {
              const data = await res.json();
              this.deliveries = data.deliveries || [];
              this.deliveriesTotal = data.total || 0;
            }
          } catch (e) {
            console.warn('Deliveries fetch failed:', e);
          } finally {
            this.deliveriesLoading = false;
          }
        },

        async replayDelivery(id) {
          if (!id) return;
          try {
            const res = await fetch(`/deliveries/${id}/replay`, {
              method: 'POST',
              headers: { 'X-Api-Key': this.apiKey }
            });
            if (res.ok) {
              this.fetchDeliveries();
            } else {
              const data = await res.json().catch(() => ({}));
              alert(data.message || 'Replay failed');
            }
          } catch (e) {
            alert('Replay failed: ' + e.message);
          }
        },

        async replayAllFailed() {
          if (!confirm('Replay all failed deliveries?')) return;
          try {
            const res = await fetch('/deliveries/replay-all', {
              method: 'POST',
              headers: { 'X-Api-Key': this.apiKey }
            });
            if (res.ok) {
              const data = await res.json();
              alert(`Queued ${data.queued || 0} deliveries for replay.`);
              this.fetchDeliveries();
            } else {
              const data = await res.json().catch(() => ({}));
              alert(data.message || 'Replay all failed');
            }
          } catch (e) {
            alert('Replay all failed: ' + e.message);
          }
        },

        toggleRow(id) {
          this.expandedRows[id] = !this.expandedRows[id];
          this.expandedRows = { ...this.expandedRows };
        },

        connectWebSocket() {
          const generation = ++this._wsGeneration;
          if (this._ws) { this._ws.close(); this._ws = null; }
          if (this._pollInterval) { clearInterval(this._pollInterval); this._pollInterval = null; }

          const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
          const params = new URLSearchParams({ token: this.apiKey });
          if (this.logFilter.event_type) params.set('event_type', this.logFilter.event_type);
          if (this.logFilter.status) params.set('status', this.logFilter.status);
          if (this.logFilter.repo) params.set('repo', this.logFilter.repo);

          try {
            const ws = new WebSocket(`${proto}//${location.host}/stream/logs?${params}`);
            this._ws = ws;

            ws.onopen = () => {
              this.wsConnected = true;
              this.wsError = '';
            };

            ws.onmessage = (e) => {
              try {
                const event = JSON.parse(e.data);
                const now = new Date();
                const time = now.toLocaleTimeString('en-US', { hour12: false });
                this.logs.push({
                  time,
                  event_type: event.event_type || event.event || '',
                  status: event.status || '',
                  summary: event.delivery_id ? `delivery=${event.delivery_id.slice(0, 8)}` : JSON.stringify(event).slice(0, 120),
                  raw: event,
                });
                if (this.logs.length > 200) this.logs.splice(0, this.logs.length - 200);
                this.$nextTick(() => {
                  const el = this.$refs.logContainer;
                  if (el) el.scrollTop = el.scrollHeight;
                });
              } catch (err) {
                console.warn('WS message parse error:', err);
              }
            };

            ws.onclose = () => {
              if (generation !== this._wsGeneration) return;
              this.wsConnected = false;
              this._ws = null;
              if (this.authenticated) {
                this.wsError = 'WebSocket disconnected. Falling back to polling.';
                this.startPollingFallback();
              }
            };

            ws.onerror = () => {
              if (generation !== this._wsGeneration) return;
              this.wsConnected = false;
              this.wsError = 'WebSocket error. Falling back to polling.';
            };
          } catch (e) {
            this.wsError = 'WebSocket unavailable. Using polling fallback.';
            this.startPollingFallback();
          }
        },

        reconnectWs() {
          if (this.authenticated) this.connectWebSocket();
        },

        startPollingFallback() {
          if (this._pollInterval) clearInterval(this._pollInterval);
          this._pollInterval = setInterval(async () => {
            if (!this.authenticated) return;
            await this.fetchDeliveries();
            const seenIds = new Set(this.logs.map(l => l._id).filter(Boolean));
            const newEntries = this.deliveries
              .filter(d => {
                const id = d.delivery_id || d.id;
                return id && !seenIds.has(id);
              })
              .map(d => ({
                _id: d.delivery_id || d.id,
                time: new Date().toLocaleTimeString('en-US', { hour12: false }),
                event_type: d.event_type || d.event || 'delivery',
                status: d.status || '',
                summary: `id=${(d.delivery_id || d.id || '').slice(0, 8)} (polled)`,
              }));
            if (newEntries.length) {
              this.logs.unshift(...newEntries);
              if (this.logs.length > 200) this.logs.splice(200);
            }
          }, 5000);
        },

        timeAgo(ts) {
          if (!ts) return '-';
          const seconds = typeof ts === 'number'
            ? Math.floor(Date.now() / 1000) - ts
            : Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
          if (seconds < 0) return 'just now';
          if (seconds < 60) return seconds + 's ago';
          if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
          if (seconds < 86400) return Math.floor(seconds / 3600) + 'h ago';
          return Math.floor(seconds / 86400) + 'd ago';
        },

        statusColor(status) {
          if (!status) return 'bg-gray-800 text-gray-400';
          const s = status.toLowerCase();
          if (s === 'delivered' || s === 'ok' || s === 'connected' || s === 'closed')
            return 'bg-emerald-900/50 text-emerald-400';
          if (s === 'failed' || s === 'error' || s === 'disconnected' || s === 'open')
            return 'bg-red-900/50 text-red-400';
          if (s === 'pending' || s === 'warning' || s === 'half_open')
            return 'bg-amber-900/50 text-amber-400';
          return 'bg-gray-800 text-gray-400';
        },
      };
    }
  </script>
</body>
</html>
"""
