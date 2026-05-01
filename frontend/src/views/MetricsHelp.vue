<template>
  <div class="metrics-help">
    <div class="section">
      <div class="section-header">
        <h2 class="section-title">指标科普</h2>
        <el-tag effect="plain">给第一次压测的人看</el-tag>
      </div>
      <div class="section-body">
        <div class="hero-grid">
          <div>
            <span>核心关系</span>
            <strong>并发不是 RPM</strong>
            <p>并发是同一时间有多少请求在路上；RPM 是一分钟内真正完成了多少成功请求。</p>
          </div>
          <div>
            <span>启动前预期</span>
            <strong>先估算，再压测</strong>
            <p>配置页会按假设单请求耗时估算 RPM、TPM、TPS，真实结果以运行报告为准。</p>
          </div>
          <div>
            <span>看报告顺序</span>
            <strong>成功率优先</strong>
            <p>吞吐再高，如果成功率低或 P99 很差，也不能作为稳定容量基线。</p>
          </div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-header">
        <h2 class="section-title">常用指标怎么理解</h2>
      </div>
      <div class="section-body">
        <el-table :data="metricRows" border>
          <el-table-column prop="name" label="指标" width="130" />
          <el-table-column prop="plain" label="小白理解" min-width="230" />
          <el-table-column prop="formula" label="近似公式" min-width="250">
            <template #default="{ row }">
              <code>{{ row.formula }}</code>
            </template>
          </el-table-column>
          <el-table-column prop="watch" label="主要看什么" min-width="260" />
        </el-table>
      </div>
    </div>

    <div class="grid-2">
      <div class="section">
        <div class="section-header">
          <h2 class="section-title">并发、RPM、TPM 的关系</h2>
        </div>
        <div class="section-body">
          <div class="formula-stack">
            <div>
              <span>请求吞吐</span>
              <code>RPM ≈ 并发数 ÷ 单请求平均耗时 × 60</code>
            </div>
            <div>
              <span>Token 吞吐</span>
              <code>TPM ≈ RPM × 单请求总 Token</code>
            </div>
            <div>
              <span>秒级 Token 吞吐</span>
              <code>TPS = TPM ÷ 60</code>
            </div>
          </div>
          <el-alert
            class="formula-alert"
            title="例子：500 并发不等于 500 RPM"
            description="如果每个请求平均 10 秒完成，500 并发大约是 3,000 RPM；如果每个请求平均 60 秒完成，才接近 500 RPM。"
            type="info"
            show-icon
            :closable="false"
          />
        </div>
      </div>

      <div class="section">
        <div class="section-header">
          <h2 class="section-title">启动前估算器</h2>
          <span class="muted">用于理解公式，不会发起测试</span>
        </div>
        <div class="section-body">
          <div class="calculator-grid">
            <el-form-item label="并发数">
              <el-input-number v-model="demo.concurrency" :min="1" :max="5000" controls-position="right" />
            </el-form-item>
            <el-form-item label="单请求平均耗时">
              <el-segmented v-model="demo.latencySec" :options="latencyOptions" />
            </el-form-item>
            <el-form-item label="输入 Token">
              <el-input-number v-model="demo.inputTokens" :min="1" :step="1000" controls-position="right" />
            </el-form-item>
            <el-form-item label="最大输出 Token">
              <el-input-number v-model="demo.outputTokens" :min="1" :step="128" controls-position="right" />
            </el-form-item>
          </div>
          <div class="estimate-grid">
            <div>
              <span>预期 RPM</span>
              <strong>{{ number(demoRpm) }}</strong>
              <em>每分钟成功请求数</em>
            </div>
            <div>
              <span>预期 TPM</span>
              <strong>{{ number(demoTpm) }}</strong>
              <em>每分钟总 Token</em>
            </div>
            <div>
              <span>预期 TPS</span>
              <strong>{{ number(demoTps) }}</strong>
              <em>每秒总 Token</em>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-header">
        <h2 class="section-title">新手看报告的顺序</h2>
      </div>
      <div class="section-body">
        <div class="check-grid">
          <div v-for="item in checklist" :key="item.title" class="check-card">
            <span>{{ item.step }}</span>
            <strong>{{ item.title }}</strong>
            <p>{{ item.description }}</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive } from 'vue'

const latencyOptions = [
  { label: '2s', value: 2 },
  { label: '5s', value: 5 },
  { label: '10s', value: 10 },
  { label: '30s', value: 30 },
  { label: '60s', value: 60 }
]

const demo = reactive({
  concurrency: 500,
  latencySec: 10,
  inputTokens: 1000,
  outputTokens: 128
})

const demoRpm = computed(() => Number(demo.concurrency || 0) / Number(demo.latencySec || 1) * 60)
const demoTpm = computed(() => demoRpm.value * (Number(demo.inputTokens || 0) + Number(demo.outputTokens || 0)))
const demoTps = computed(() => demoTpm.value / 60)

const metricRows = [
  {
    name: '并发',
    plain: '同一时间最多有多少请求在执行。',
    formula: 'worker 数 / in-flight 请求数',
    watch: '它是压测强度设置，不是最终吞吐结果。'
  },
  {
    name: 'RPM',
    plain: '一分钟内成功完成了多少请求。',
    formula: '成功请求数 × 60 ÷ 测试秒数',
    watch: '判断请求吞吐，和平均耗时强相关。'
  },
  {
    name: 'TPM',
    plain: '一分钟内处理了多少 token。',
    formula: '总 Token × 60 ÷ 测试秒数',
    watch: '判断模型/网关 token 吞吐上限。'
  },
  {
    name: 'TPS',
    plain: '每秒处理多少 token。',
    formula: 'TPM ÷ 60',
    watch: '适合和服务端秒级指标对齐。'
  },
  {
    name: 'TTFT',
    plain: '从请求发出到第一个 token 返回的时间。',
    formula: '首 token 时间 - 请求开始时间',
    watch: '只在流式模式下准确，反映排队和 prefill。'
  },
  {
    name: 'P95 / P99',
    plain: '最慢那部分请求有多慢。',
    formula: '延迟分布百分位',
    watch: '比平均值更能发现拥塞和抖动。'
  },
  {
    name: '成功率',
    plain: '请求成功的比例。',
    formula: '成功请求数 ÷ 总请求数',
    watch: '低于 99% 时不要只看高吞吐。'
  }
]

const checklist = [
  {
    step: '01',
    title: '先看成功率',
    description: '成功率低时，RPM/TPM 只能说明压力打上去了，不能说明系统稳定。'
  },
  {
    step: '02',
    title: '再看 RPM 和 TPM',
    description: 'RPM 看请求吞吐，TPM 看 token 吞吐。长上下文场景更应该重点看 TPM。'
  },
  {
    step: '03',
    title: '接着看 P95/P99',
    description: '平均延迟好看但 P99 很差，说明用户里会有一部分体验很差。'
  },
  {
    step: '04',
    title: '最后拆 TTFT 和 Decode',
    description: 'TTFT 高通常偏排队或输入预填充瓶颈，Decode 高通常偏输出生成瓶颈。'
  }
]

function number(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return '-'
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })
}
</script>

<style scoped>
.metrics-help {
  max-width: 1480px;
}

.hero-grid,
.estimate-grid,
.check-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.hero-grid > div,
.estimate-grid > div,
.check-card {
  padding: 14px;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
  background: #ffffff;
}

.hero-grid span,
.estimate-grid span,
.check-card span {
  display: block;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.hero-grid strong,
.estimate-grid strong,
.check-card strong {
  display: block;
  margin-top: 6px;
  color: #1e293b;
  font-size: 18px;
  font-weight: 800;
}

.hero-grid p,
.check-card p {
  margin: 8px 0 0;
  color: #475569;
  font-size: 13px;
  line-height: 1.55;
}

.formula-stack {
  display: grid;
  gap: 10px;
}

.formula-stack > div {
  display: grid;
  gap: 6px;
  padding: 12px;
  border: 1px solid #dbeafe;
  border-radius: 8px;
  background: #f8fbff;
}

.formula-stack span {
  color: #475569;
  font-size: 12px;
  font-weight: 700;
}

.formula-alert {
  margin-top: 12px;
}

.calculator-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.estimate-grid {
  margin-top: 4px;
}

.estimate-grid strong {
  color: #2563eb;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 22px;
}

.estimate-grid em {
  display: block;
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
  font-style: normal;
}

code {
  color: #1d4ed8;
  font-family: "Fira Code", Consolas, monospace;
}

:deep(.el-input-number) {
  width: 100%;
}

@media (max-width: 1180px) {
  .hero-grid,
  .estimate-grid,
  .check-grid,
  .calculator-grid {
    grid-template-columns: 1fr;
  }
}
</style>
