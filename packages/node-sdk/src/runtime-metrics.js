'use strict';

const { monitorEventLoopDelay } = require('node:perf_hooks');
const os = require('node:os');

/**
 * Process-level metrics only. These describe THIS Node.js process, not the host or container:
 * the platform labels them `scope=process` and never presents them as machine CPU/memory.
 */
function registerRuntimeMetrics(meter) {
  const loop = monitorEventLoopDelay({ resolution: 20 });
  loop.enable();
  let lastCpu = process.cpuUsage();
  let lastT = process.hrtime.bigint();
  let lastUtil = 0;
  const cores = Math.max(os.availableParallelism ? os.availableParallelism() : os.cpus().length, 1);
  const attrs = { scope: 'process' };

  const gauge = (name, unit, description, read) =>
    meter.createObservableGauge(name, { unit, description }).addCallback((r) => {
      const v = read();
      if (Number.isFinite(v)) r.observe(v, attrs);
    });

  gauge('process.memory.usage', 'By', 'Resident set size of this process', () => process.memoryUsage().rss);
  gauge('nodejs.heap.used', 'By', 'V8 heap used', () => process.memoryUsage().heapUsed);
  gauge('nodejs.heap.total', 'By', 'V8 heap total', () => process.memoryUsage().heapTotal);
  gauge('process.uptime', 's', 'Process uptime', () => process.uptime());
  gauge('nodejs.eventloop.lag.p99', 'ms', 'Event loop delay p99 since last export', () => {
    const v = loop.percentile(99) / 1e6;
    loop.reset();
    return Number.isFinite(v) ? v : 0;
  });
  gauge('process.cpu.utilization', '1', 'Fraction of one-core-normalised CPU used by this process', () => {
    const now = process.hrtime.bigint();
    const cpu = process.cpuUsage(lastCpu);
    const elapsedUs = Number(now - lastT) / 1000;
    if (elapsedUs > 0) lastUtil = Math.min((cpu.user + cpu.system) / (elapsedUs * cores), 1);
    lastCpu = process.cpuUsage();
    lastT = now;
    return lastUtil;
  });
  return () => loop.disable();
}

module.exports = { registerRuntimeMetrics };
