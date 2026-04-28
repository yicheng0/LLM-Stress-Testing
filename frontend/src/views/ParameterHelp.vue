<template>
  <div class="help-page">
    <div class="section">
      <div class="section-header">
        <h2 class="section-title">测试参数总览</h2>
        <el-tag effect="plain">APIPro 团队</el-tag>
      </div>
      <div class="section-body">
        <div class="intro-grid">
          <div>
            <div class="intro-title">国内节点</div>
            <code>https://api.wenwen-ai.com</code>
          </div>
          <div>
            <div class="intro-title">海外节点</div>
            <code>https://api.apipro.ai</code>
          </div>
          <div>
            <div class="intro-title">支持协议</div>
            <span>OpenAI-compatible / Anthropic / Gemini</span>
          </div>
        </div>
      </div>
    </div>

    <div v-for="group in groups" :key="group.title" class="section">
      <div class="section-header">
        <h2 class="section-title">{{ group.title }}</h2>
        <span class="muted">{{ group.description }}</span>
      </div>
      <div class="section-body">
        <el-table :data="group.items" border>
          <el-table-column prop="name" label="参数" min-width="150" />
          <el-table-column prop="field" label="字段" min-width="170">
            <template #default="{ row }">
              <code>{{ row.field }}</code>
            </template>
          </el-table-column>
          <el-table-column prop="meaning" label="作用" min-width="260" />
          <el-table-column prop="recommendation" label="建议" min-width="220" />
          <el-table-column prop="note" label="注意事项" min-width="260" />
        </el-table>
      </div>
    </div>

    <div class="section">
      <div class="section-header">
        <h2 class="section-title">报告指标说明</h2>
      </div>
      <div class="section-body">
        <div class="metric-doc-grid">
          <div v-for="metric in metrics" :key="metric.name" class="metric-doc">
            <div class="metric-doc-name">{{ metric.name }}</div>
            <div class="metric-doc-desc">{{ metric.description }}</div>
          </div>
        </div>
      </div>
    </div>

    <div class="section dashboard-entry">
      <div class="section-header">
        <h2 class="section-title">实时测试数据面板</h2>
        <el-button type="primary" :icon="DataAnalysis" @click="router.push('/dashboard/realtime')">
          打开实时面板
        </el-button>
      </div>
      <div class="section-body">
        <div class="dashboard-entry-body">
          <div>
            <strong>查看运行中任务的 RPM、TPM、成功率、P95 和协议分布。</strong>
            <span>面板会自动刷新，适合在压测过程中单独打开观察整体表现。</span>
          </div>
          <el-button :icon="ArrowRight" @click="router.push('/dashboard/realtime')">进入页面</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { ArrowRight, DataAnalysis } from '@element-plus/icons-vue'

const router = useRouter()

const groups = [
  {
    title: '基础配置',
    description: '决定请求发往哪里，以及用什么协议构造请求。',
    items: [
      {
        name: '接口协议',
        field: 'api_protocol',
        meaning: '决定请求体结构、鉴权请求头和 token 用量字段的解析方式。',
        recommendation: 'GLM/Qwen/DeepSeek/OpenAI 兼容接口选择 OpenAI-compatible；Claude 选择 Anthropic；Gemini 选择 Gemini。',
        note: '协议只改变请求格式，不改变压测并发模型。'
      },
      {
        name: '接入域名',
        field: 'base_url',
        meaning: 'APIPro 网关入口域名。',
        recommendation: '国内用户选国内节点，海外用户选海外节点。',
        note: '页面已固定为国内和海外两个节点，不需要手动填写。'
      },
      {
        name: 'Endpoint',
        field: 'endpoint',
        meaning: '协议下的具体接口路径。',
        recommendation: '通常使用默认值；OpenAI-compatible 为 /chat/completions，Anthropic 为 /messages，Gemini 为 generateContent。',
        note: 'Gemini 的 {model} 会在发送请求时替换为模型名称。'
      },
      {
        name: '模型名称',
        field: 'model',
        meaning: '目标模型 ID。',
        recommendation: '填写网关支持的精确模型名。',
        note: '模型上下文窗口不足时，长输入测试可能失败。'
      },
      {
        name: 'API Key',
        field: 'api_key',
        meaning: '访问目标协议接口所需的密钥。',
        recommendation: '使用临时或受限权限 Key。',
        note: 'MVP 中 API Key 只用于当前任务，不写入数据库。'
      }
    ]
  },
  {
    title: '负载配置',
    description: '决定压测强度、输入规模和输出规模。',
    items: [
      {
        name: '并发数',
        field: 'concurrency',
        meaning: '同时运行的请求 worker 数。',
        recommendation: '先从 10、50、100 逐级增加。',
        note: '并发过高会同时压垮本机、网关或目标模型服务。'
      },
      {
        name: '测试时长',
        field: 'duration_sec',
        meaning: '单次压测持续时间，单位秒。',
        recommendation: '功能验证 30-60 秒，稳定性观察 300 秒以上。',
        note: '时长越长，报告越稳定，但成本也越高。'
      },
      {
        name: '输入 Token 数',
        field: 'input_tokens',
        meaning: '生成合成 prompt 的目标 token 长度。',
        recommendation: '按真实业务输入规模选择，例如 1k、10k、100k。',
        note: '实际 token 数会受 tokenizer 估算影响，报告会展示实际值。'
      },
      {
        name: '最大输出 Token 数',
        field: 'max_output_tokens',
        meaning: '单次请求允许模型最多生成的 token 数。',
        recommendation: '吞吐测试可设小一些，生成速度测试可适当增加。',
        note: '输出越长，Decode 阶段占比越高。'
      },
      {
        name: '预热请求数',
        field: 'warmup_requests',
        meaning: '正式计数前先发送的请求数量。',
        recommendation: '生产测试可设置 3-10 个。',
        note: '预热请求不计入最终统计。'
      },
      {
        name: '流式模式',
        field: 'enable_stream',
        meaning: '是否使用流式响应读取首 token。',
        recommendation: '需要 TTFT 指标时开启。',
        note: '非流式模式无法准确测量 TTFT 和 Decode。'
      }
    ]
  },
  {
    title: '高级配置',
    description: '控制请求超时、重试和发送节奏。',
    items: [
      {
        name: 'Temperature',
        field: 'temperature',
        meaning: '模型采样随机性参数。',
        recommendation: '性能基准测试建议设为 0。',
        note: '随机性越高，输出长度和耗时可能更不稳定。'
      },
      {
        name: '请求超时',
        field: 'timeout_sec',
        meaning: '单个请求的最长等待时间。',
        recommendation: '长上下文测试建议设置较大，例如 300-600 秒。',
        note: '过短会把慢请求记为超时失败。'
      },
      {
        name: '连接超时',
        field: 'connect_timeout_sec',
        meaning: '建立连接的最长等待时间。',
        recommendation: '一般 10-30 秒足够。',
        note: '网络跨境或代理链路较长时可适当提高。'
      },
      {
        name: '最大重试次数',
        field: 'max_retries',
        meaning: '遇到 429、5xx、超时时的最多重试次数。',
        recommendation: '基准测试建议 0-2 次。',
        note: '重试会改善成功率，但也可能掩盖真实限流情况。'
      },
      {
        name: '重试退避',
        field: 'retry_backoff_base / retry_backoff_max',
        meaning: '失败后等待多久再重试。',
        recommendation: '默认 1 到 8 秒适合大多数场景。',
        note: '高并发下过短的退避会放大拥塞。'
      },
      {
        name: '请求间隔',
        field: 'think_time_ms',
        meaning: '每个 worker 两次请求之间的等待时间。',
        recommendation: '模拟真实用户节奏时设置，纯吞吐测试可设 0。',
        note: '设置后实际 QPS 会下降。'
      }
    ]
  },
  {
    title: '矩阵测试',
    description: '批量探索不同输入长度和并发组合下的性能边界。',
    items: [
      {
        name: '矩阵模式',
        field: 'matrix_mode',
        meaning: '是否启用批量参数组合测试。',
        recommendation: '寻找最佳并发区间时开启。',
        note: '矩阵测试会按组合顺序依次执行，耗时更长。'
      },
      {
        name: '输入 Token 列表',
        field: 'input_tokens_list',
        meaning: '多个输入长度，逗号分隔。',
        recommendation: '例如 1000,10000,100000。',
        note: '组合数量不宜过多，避免测试时间和成本失控。'
      },
      {
        name: '并发列表',
        field: 'concurrency_list',
        meaning: '多个并发数，逗号分隔。',
        recommendation: '例如 10,50,100,200。',
        note: '最大并发仍受后端安全上限限制。'
      },
      {
        name: '单点时长',
        field: 'matrix_duration_sec',
        meaning: '矩阵中每个测试点运行多久。',
        recommendation: '快速摸底 30-60 秒，正式测试 180 秒以上。',
        note: '总耗时约等于测试点数量乘以单点时长，再加冷却时间。'
      }
    ]
  }
]

const metrics = [
  { name: 'RPM', description: '每分钟成功请求数，用于衡量请求吞吐。' },
  { name: 'TPM', description: '每分钟 token 数，包含输入、输出和总 token。' },
  { name: 'TPS', description: '每秒 token 数，是 TPM 的秒级表示。' },
  { name: 'TTFT', description: 'Time To First Token，流式模式下从发起请求到首个 token 到达的时间。' },
  { name: 'Decode', description: '从首 token 到完整响应结束的耗时，反映生成阶段性能。' },
  { name: 'P50/P90/P95/P99', description: '延迟百分位，P95/P99 更能反映尾延迟和拥塞。' },
  { name: '成功率', description: '成功请求数除以总请求数，低成功率通常意味着限流、超时或服务端错误。' },
  { name: '错误分布', description: '按 HTTP 状态码和错误类型聚合，便于区分限流、超时和网关错误。' }
]
</script>

<style scoped>
.help-page {
  max-width: 1480px;
}

.intro-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.intro-grid > div,
.metric-doc {
  padding: 14px;
  border: 1px solid #dfe7f2;
  border-radius: 8px;
  background: #ffffff;
}

.intro-title,
.metric-doc-name {
  margin-bottom: 8px;
  color: #334155;
  font-weight: 800;
}

.intro-grid code {
  color: #1d4ed8;
  font-family: "Fira Code", Consolas, monospace;
  font-size: 13px;
}

.metric-doc-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.metric-doc-desc {
  color: #475569;
  font-size: 13px;
  line-height: 1.55;
}

.dashboard-entry-body {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px;
  border: 1px solid #dbeafe;
  border-radius: 8px;
  background: linear-gradient(135deg, #eff6ff 0%, #f8fbff 48%, #fff7ed 100%);
}

.dashboard-entry-body > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
}

.dashboard-entry-body strong {
  color: #1e293b;
  font-size: 15px;
}

.dashboard-entry-body span {
  color: #64748b;
  font-size: 13px;
}

code {
  color: #1d4ed8;
  font-family: "Fira Code", Consolas, monospace;
}

@media (max-width: 1180px) {
  .intro-grid,
  .metric-doc-grid {
    grid-template-columns: 1fr;
  }

  .dashboard-entry-body {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
